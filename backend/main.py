"""
FastAPI Backend - API REST + WebSocket para o Sentinel Agent.
"""

import os
import sys
import json
import asyncio
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import Counter, Gauge, generate_latest

DB_PATH = os.environ.get("SENTINEL_DB", str(Path(__file__).parent.parent / "data" / "sentinel.db"))


class ConnectionManager:
    """Gerencia conexoes WebSocket."""
    def __init__(self):
        self.active: list[WebSocket] = []
    
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
    
    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
    
    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
orchestrator = None

# Prometheus metrics
SENTINEL_INCIDENTS = Counter("sentinel_incidents_total", "Total incidents detected", ["type"])
SENTINEL_AGENTS_ACTIVE = Gauge("sentinel_agents_active", "Number of active agents")
SENTINEL_ORCHESTRATOR_STATUS = Gauge("sentinel_orchestrator_status", "Orchestrator health 1=ok")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator
    from agent.orchestrator import SentinelOrchestrator
    
    orchestrator = SentinelOrchestrator()
    
    # Callback para broadcast em tempo real
    async def broadcast_callback(evento, dados):
        await manager.broadcast({"evento": evento, "dados": dados})
    
    # Envolver callback assincrono
    def sync_callback(evento, dados):
        asyncio.ensure_future(broadcast_callback(evento, dados))
    
    # Registrar e iniciar
    import threading
    def start_async_broadcast():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        orchestrator.on_event(lambda e, d: loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(manager.broadcast({"evento": e, "dados": d}))
        ))
        orchestrator.start()
        loop.run_forever()
    
    t = threading.Thread(target=start_async_broadcast, daemon=True)
    t.start()
    
    yield
    
    if orchestrator:
        orchestrator.stop()


app = FastAPI(title="Sentinel Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    return sqlite3.connect(DB_PATH)


# --- REST Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "service": "sentinel-agent"}


@app.get("/metrics")
def metrics():
    if orchestrator:
        SENTINEL_ORCHESTRATOR_STATUS.set(1)
    else:
        SENTINEL_ORCHESTRATOR_STATUS.set(0)
    return Response(content=generate_latest(), media_type="text/plain; charset=utf-8")


@app.get("/api/estado")
def get_estado():
    if not orchestrator:
        return {"error": "Orchestrator not ready"}
    return orchestrator.get_estado()


@app.get("/api/metricas/{componente}")
def get_metricas(componente: str, limit: int = 20):
    conn = get_db()
    cursor = conn.execute(
        "SELECT tipo_metrica, valor, timestamp FROM metricas WHERE componente = ? ORDER BY timestamp DESC LIMIT ?",
        (componente, limit)
    )
    rows = [{"metrica": r[0], "valor": r[1], "timestamp": r[2]} for r in cursor.fetchall()]
    conn.close()
    return {"componente": componente, "metricas": rows}


@app.get("/api/incidentes")
def get_incidentes(limit: int = 20):
    conn = get_db()
    cursor = conn.execute(
        "SELECT id, nome, tipo, causa_raiz_real, componente_afetado, timestamp_inicio, ativo "
        "FROM incidentes_injetados ORDER BY timestamp_inicio DESC LIMIT ?", (limit,)
    )
    rows = [{"id": r[0], "nome": r[1], "tipo": r[2], "causa": r[3],
             "componente": r[4], "inicio": r[5], "ativo": r[6]} for r in cursor.fetchall()]
    conn.close()
    return {"incidentes": rows}


@app.get("/api/mensagens")
def get_mensagens(incidente_id: int = None, limit: int = 50):
    conn = get_db()
    if incidente_id:
        cursor = conn.execute(
            "SELECT remetente, destinatario, tipo, conteudo, incidente_id, timestamp "
            "FROM mensagens_agentes WHERE incidente_id = ? ORDER BY timestamp ASC LIMIT ?",
            (incidente_id, limit)
        )
    else:
        cursor = conn.execute(
            "SELECT remetente, destinatario, tipo, conteudo, incidente_id, timestamp "
            "FROM mensagens_agentes ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
    rows = [{"remetente": r[0], "destinatario": r[1], "tipo": r[2],
             "conteudo": r[3], "incidente_id": r[4], "timestamp": r[5]} for r in cursor.fetchall()]
    conn.close()
    return {"mensagens": rows}


class AutorizarRequest(BaseModel):
    incidente_id: int
    autorizado: bool


@app.post("/api/autorizar")
def autorizar(req: AutorizarRequest):
    if orchestrator:
        orchestrator.autorizar(req.incidente_id, req.autorizado)
        return {"status": "ok"}
    return {"error": "Orchestrator not ready"}


class AssumirRequest(BaseModel):
    incidente_id: int


@app.post("/api/assumir")
def assumir(req: AssumirRequest):
    if orchestrator:
        orchestrator.assumir_controle(req.incidente_id)
        return {"status": "ok"}
    return {"error": "Orchestrator not ready"}


@app.get("/api/agentes")
def listar_agentes():
    from agent.core import get_agent_names
    return {"agentes": get_agent_names(), "total": len(get_agent_names())}


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Enviar estado inicial
        if orchestrator:
            estado = orchestrator.get_estado()
            await ws.send_json({"evento": "estado_inicial", "dados": estado})
        
        while True:
            data = await ws.receive_text()
            # Processar comandos do frontend
            try:
                msg = json.loads(data)
                if msg.get("comando") == "ping":
                    await ws.send_json({"evento": "pong"})
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Servir frontend estatico
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
