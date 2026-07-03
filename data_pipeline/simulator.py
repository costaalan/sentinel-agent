# Sentinel Agent - Sistema Multiagente Autonomo de AIOps

"""
Simulador de metricas de infraestrutura que gera series temporais sinteticas com incidentes programados.
Componente separado - nao e um agente, nao raciocina. Apenas persiste dados no banco.
"""

import os
import time
import random
import sqlite3
import datetime
import json
import threading
from pathlib import Path

# Config
DB_PATH = os.environ.get("SENTINEL_DB", str(Path(__file__).parent.parent / "data" / "sentinel.db"))
INTERVAL_SECONDS = int(os.environ.get("SIMULATOR_INTERVAL", 8))

# Componentes simulados
COMPONENTS = {
    "api_gateway": {"type": "api", "metrics": ["latency_ms", "error_rate", "requests_per_min"]},
    "servico_a": {"type": "service", "metrics": ["latency_ms", "error_rate"]},
    "servico_b": {"type": "service", "metrics": ["latency_ms", "error_rate"]},
    "fila_jobs": {"type": "queue", "metrics": ["queue_size", "processing_time_avg"]},
    "job_sync_vendas": {"type": "job", "metrics": ["duration_seconds", "step_duration_seconds", "status"]},
    "agente_ia_recomendacao": {"type": "ai_agent", "metrics": ["inference_latency_ms", "error_rate", "requests_per_min"]},
    "dashboard_vendas": {"type": "dashboard", "metrics": ["last_update_seconds_ago", "refresh_status"]},
}

# Cenários de incidente
INCIDENT_SCENARIOS = [
    {
        "name": "job_travado",
        "trigger_after": 4,
        "component": "job_sync_vendas",
        "metrics": {"duration_seconds": 300, "step_duration_seconds": 280, "status": 2},
        "causa_real": "step sync_vendas travado bloqueando fila",
        "correlated_components": {"dashboard_vendas": {"last_update_seconds_ago": 360, "refresh_status": 0}},
    },
    {
        "name": "erro_500_servico",
        "trigger_after": 8,
        "component": "servico_a",
        "metrics": {"latency_ms": 5000, "error_rate": 0.35},
        "causa_real": "deploy recente com regression no endpoint /api/orders",
        "correlated_components": {"api_gateway": {"error_rate": 0.25, "latency_ms": 3000}},
    },
    {
        "name": "latencia_ia",
        "trigger_after": 12,
        "component": "agente_ia_recomendacao",
        "metrics": {"inference_latency_ms": 8000, "error_rate": 0.12, "requests_per_min": 450},
        "causa_real": "sobrecarga de fila de requisições no modelo de recomendação",
        "correlated_components": {"fila_jobs": {"queue_size": 250}},
    },
    {
        "name": "incidente_rede",
        "trigger_after": 16,
        "component": "api_gateway",
        "metrics": {"latency_ms": 15000, "error_rate": 0.5, "requests_per_min": 50},
        "causa_real": "saturação de banda no link primário",
        "correlated_components": {"servico_b": {"latency_ms": 12000, "error_rate": 0.4}},
    },
    {
        "name": "dashboard_parou",
        "trigger_after": 6,
        "component": "dashboard_vendas",
        "metrics": {"last_update_seconds_ago": 420, "refresh_status": 0},
        "causa_real": "job sync_vendas travado (mesma causa do incidente 1)",
        "correlated_components": {"job_sync_vendas": {"duration_seconds": 350, "step_duration_seconds": 330}},
    },
]


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS metricas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            componente TEXT NOT NULL,
            tipo_metrica TEXT NOT NULL,
            valor REAL NOT NULL,
            timestamp DATETIME DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_metricas_comp ON metricas(componente, timestamp);
        
        CREATE TABLE IF NOT EXISTS incidentes_injetados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL,
            causa_raiz_real TEXT NOT NULL,
            componente_afetado TEXT NOT NULL,
            timestamp_inicio DATETIME DEFAULT (datetime('now')),
            timestamp_fim DATETIME,
            ativo INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS mensagens_agentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remetente TEXT NOT NULL,
            destinatario TEXT NOT NULL,
            tipo TEXT NOT NULL,
            conteudo TEXT NOT NULL,
            incidente_id INTEGER,
            timestamp DATETIME DEFAULT (datetime('now'))
        );
        
        CREATE TABLE IF NOT EXISTS estado_incidentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incidente_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'em_resolucao',
            resolvido_por TEXT,
            nivel_autonomia INTEGER,
            detalhes TEXT,
            timestamp DATETIME DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def gerar_metricas_normais():
    """Gera métricas com valores dentro da faixa normal (com ruído)."""
    normals = {
        "api_gateway": {"latency_ms": (80, 200), "error_rate": (0, 0.03), "requests_per_min": (800, 1200)},
        "servico_a": {"latency_ms": (50, 150), "error_rate": (0, 0.02)},
        "servico_b": {"latency_ms": (60, 180), "error_rate": (0, 0.02)},
        "fila_jobs": {"queue_size": (5, 30), "processing_time_avg": (2, 8)},
        "job_sync_vendas": {"duration_seconds": (30, 90), "step_duration_seconds": (10, 40), "status": (1, 1)},
        "agente_ia_recomendacao": {"inference_latency_ms": (200, 800), "error_rate": (0, 0.02), "requests_per_min": (200, 400)},
        "dashboard_vendas": {"last_update_seconds_ago": (0, 10), "refresh_status": (1, 1)},
    }
    
    metrics = []
    for comp, type in COMPONENTS.items():
        for metrica in type["metrics"]:
            if comp in normals and metrica in normals[comp]:
                lo, hi = normals[comp][metrica]
                val = round(random.uniform(lo, hi), 2)
            else:
                val = round(random.uniform(0, 100), 2)
            metrics.append((comp, metrica, val))
    return metrics


def aplicar_incidente(conn, incidente):
    """Aplica métricas anômalas de um incidente nos componentes afetados."""
    now = datetime.datetime.now()
    
    # Métrica anômala no componente principal
    for metrica, valor in incidente["metrics"].items():
        conn.execute(
            "INSERT INTO metricas (componente, tipo_metrica, valor, timestamp) VALUES (?, ?, ?, ?)",
            (incidente["component"], metrica, valor, now.isoformat())
        )
    
    # Componentes correlacionados
    for comp, metrics in incidente.get("correlated_components", {}).items():
        for metrica, valor in metrics.items():
            conn.execute(
                "INSERT INTO metricas (componente, tipo_metrica, valor, timestamp) VALUES (?, ?, ?, ?)",
                (comp, metrica, valor, now.isoformat())
            )
    
    # Registrar incidente
    conn.execute(
        "INSERT INTO incidentes_injetados (nome, tipo, causa_raiz_real, componente_afetado) VALUES (?, ?, ?, ?)",
        (incidente["name"], incidente["name"], incidente["causa_real"], incidente["component"])
    )
    conn.commit()


def run_simulator():
    """Loop principal do simulador."""
    print(f"[SIMULATOR] Iniciando... DB={DB_PATH}, intervalo={INTERVAL_SECONDS}s")
    init_db()
    conn = sqlite3.connect(DB_PATH)
    
    tick = 0
    incident_timers = {s["name"]: 0 for s in INCIDENT_SCENARIOS}
    
    try:
        while True:
            tick += 1
            now = datetime.datetime.now().isoformat()
            
            # Gerar métricas normais para todos os componentes
            metrics = gerar_metricas_normais()
            for comp, metrica, valor in metrics:
                conn.execute(
                    "INSERT INTO metricas (componente, tipo_metrica, valor, timestamp) VALUES (?, ?, ?, ?)",
                    (comp, metrica, valor, now)
                )
            
            # Verificar incidentes programados
            for incidente in INCIDENT_SCENARIOS:
                incident_timers[incidente["name"]] += INTERVAL_SECONDS
                if incident_timers[incidente["name"]] >= incidente["trigger_after"] * INTERVAL_SECONDS:
                    incident_timers[incidente["name"]] = 0
                    print(f"[SIMULATOR] ⚠️ Injetando incidente: {incidente['name']}")
                    aplicar_incidente(conn, incidente)
            
            conn.commit()
            
            # Log periódico
            if tick % 5 == 0:
                print(f"[SIMULATOR] Tick {tick}  -  {len(metrics)} métricas geradas, {len(INCIDENT_SCENARIOS)} cenários de incidente")
            
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("[SIMULATOR] Parando...")
    finally:
        conn.close()


if __name__ == "__main__":
    run_simulator()
