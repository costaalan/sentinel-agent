"""
Orquestrador LangGraph - coordena o ciclo dos agentes.
"""

import os
import time
import threading
import json
from pathlib import Path

DB_PATH = os.environ.get("SENTINEL_DB", str(Path(__file__).parent.parent / "data" / "sentinel.db"))
AGENT_CHECK_INTERVAL = int(os.environ.get("AGENT_INTERVAL", 10))


class SentinelOrchestrator:
    """Orquestrador que coordena o ciclo de todos os agentes.
    
    Arquitetura escalavel: usa agent_registry, que pode ser estendido
    registrando novas classes de agente.
    """
    
    def __init__(self):
        from agent.core import agent_registry
        from agent.supervisor import SupervisorGeral
        
        self.supervisor = SupervisorGeral()
        self.agents = {}
        self._running = False
        self._thread = None
        self._event_callbacks = []
        
        # Instanciar todos os agentes do registry
        for name, cls in agent_registry.items():
            self.agents[name] = cls(self.supervisor)
        
        print(f"[ORCHESTRATOR] {len(self.agents)} agentes carregados: {', '.join(self.agents.keys())}")
    
    def on_event(self, callback):
        """Registra callback para eventos em tempo real."""
        self._event_callbacks.append(callback)
        self.supervisor.on_update(callback)
    
    def _notify(self, evento: str, dados: dict):
        for cb in self._event_callbacks:
            try:
                cb(evento, dados)
            except Exception as e:
                print(f"[ORCHESTRATOR] Callback error: {e}")
    
    def run_cycle(self):
        """Executa um ciclo completo de todos os agentes."""
        results = []
        for name, agent in self.agents.items():
            try:
                result = agent.run_cycle()
                if result:
                    results.append(result)
                    self._notify("agente_atuou", {
                        "agente": name,
                        "resultado": result,
                    })
            except Exception as e:
                print(f"[ORCHESTRATOR] Erro no agente {name}: {e}")
        return results
    
    def start(self):
        """Inicia o loop em background."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[ORCHESTRATOR] Iniciado (intervalo={AGENT_CHECK_INTERVAL}s)")
    
    def stop(self):
        self._running = False
    
    def _loop(self):
        while self._running:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[ORCHESTRATOR] Erro no ciclo: {e}")
            time.sleep(AGENT_CHECK_INTERVAL)
    
    def get_estado(self) -> dict:
        return {
            "agentes": list(self.agents.keys()),
            "supervisor": self.supervisor.get_estado_resumido(),
        }
    
    def autorizar(self, incidente_id: int, autorizado: bool):
        self.supervisor.autorizar_acao(incidente_id, autorizado)
    
    def assumir_controle(self, incidente_id: int):
        self.supervisor.assumir_controle(incidente_id)
