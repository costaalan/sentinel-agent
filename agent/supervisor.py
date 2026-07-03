"""
Sentinel Agent - Supervisor Geral.

Recebe notificacoes de todos os agentes especialistas, mantem a central de estado
(incidentes_resolvidos, em_resolucao, pendentes_de_decisao_humana) e coordena a
comunicacao entre agentes.
"""

import os
import sqlite3
import json
import datetime
import threading
from pathlib import Path

DB_PATH = os.environ.get("SENTINEL_DB", str(Path(__file__).parent.parent / "data" / "sentinel.db"))


def get_db():
    return sqlite3.connect(DB_PATH)


class SupervisorGeral:
    """Agente Supervisor Geral - central de estado e coordenacao.
    
    Mantem tres listas vivas:
    - incidentes_resolvidos
    - incidentes_em_resolucao
    - incidentes_pendentes_de_decisao_humana
    """
    
    def __init__(self):
        self.incidentes_resolvidos: list[dict] = []
        self.incidentes_em_resolucao: list[dict] = []
        self.incidentes_pendentes: list[dict] = []
        self._lock = threading.Lock()
        self._callbacks = []
    
    def on_update(self, callback):
        """Registra callback para notificar frontend de mudancas."""
        self._callbacks.append(callback)
    
    def _notify(self, evento: str, dados: dict):
        for cb in self._callbacks:
            try:
                cb(evento, dados)
            except Exception as e:
                print(f"[SUPERVISOR] Callback error: {e}")
    
    def receber_notificacao(self, agente: str, tipo: str, conteudo: str,
                           incidente_id: int, nivel: int):
        """Recebe notificacao de um agente especialista."""
        entry = {
            "agente": agente,
            "tipo": tipo,
            "conteudo": conteudo,
            "incidente_id": incidente_id,
            "nivel": nivel,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        
        with self._lock:
            if tipo == "resultado":
                # Verificar se foi sucesso
                if "resolvido" in conteudo.lower() or "sucesso" in conteudo.lower():
                    self.incidentes_resolvidos.append(entry)
                    self._remover_da_lista(incidente_id, "em_resolucao")
                self._atualizar_estado(incidente_id, "resolvido" if "resolvido" in conteudo.lower() else "falha")
                
            elif tipo == "acao_em_andamento":
                self.incidentes_em_resolucao.append(entry)
                self._atualizar_estado(incidente_id, "em_resolucao")
                
            elif tipo == "proposta_de_acao":
                self.incidentes_pendentes.append(entry)
                self._atualizar_estado(incidente_id, "pendente_decisao_humana")
        
        self._notify("incidente_atualizado", entry)
        print(f"[SUPERVISOR] {tipo} - {agente}: {conteudo[:60]}...")
    
    def encaminhar_pergunta(self, destinatario: str, pergunta: str,
                           incidente_id: int, remetente: str) -> str:
        """Encaminha uma pergunta de um agente para outro e retorna a resposta."""
        from agent.core import agent_registry, call_llm
        
        # Simular resposta do agente destinatario via LLM
        prompt = f"""Voce e o agente {destinatario}, especialista em monitoramento de infraestrutura.
O agente {remetente} perguntou: "{pergunta}"

Responda em JSON com: {{"resposta": "...", "evidencias": "...", "sugestao_acao": "..."}}"""
        
        resposta = call_llm(prompt, system=f"Voce e o agente {destinatario}. Responda de forma tecnica e objetiva.", max_tokens=200)
        
        # Salvar resposta como mensagem
        from agent.core import AgentMessage
        msg = AgentMessage(
            remetente=destinatario,
            destinatario=remetente,
            tipo="resposta",
            conteudo=resposta,
            incidente_id=incidente_id,
        )
        msg.save()
        print(f"[SUPERVISOR] {destinatario} -> {remetente}: {resposta[:60]}...")
        
        return resposta
    
    def autorizar_acao(self, incidente_id: int, autorizado: bool):
        """Humano autoriza ou nega uma acao de Nivel 3."""
        with self._lock:
            idx = None
            for i, item in enumerate(self.incidentes_pendentes):
                if item["incidente_id"] == incidente_id:
                    idx = i
                    break
            
            if idx is not None:
                entry = self.incidentes_pendentes.pop(idx)
                if autorizado:
                    entry["tipo"] = "autorizado"
                    self.incidentes_em_resolucao.append(entry)
                    self._atualizar_estado(incidente_id, "em_resolucao")
                else:
                    entry["tipo"] = "negado"
                    self.incidentes_resolvidos.append(entry)
                    self._atualizar_estado(incidente_id, "negado_pelo_humano")
        
        self._notify("decisao_humana", {"incidente_id": incidente_id, "autorizado": autorizado})
    
    def assumir_controle(self, incidente_id: int):
        """Humano assume controle total de um incidente."""
        with self._lock:
            # Remover de todas as listas
            for lista in [self.incidentes_resolvidos, self.incidentes_em_resolucao, self.incidentes_pendentes]:
                self._remover_da_lista(incidente_id, "todas")
            self._atualizar_estado(incidente_id, "controle_humano")
        
        self._notify("controle_humano", {"incidente_id": incidente_id})
    
    def get_estado_resumido(self) -> dict:
        with self._lock:
            return {
                "resolvidos": len(self.incidentes_resolvidos),
                "em_resolucao": len(self.incidentes_em_resolucao),
                "pendentes": len(self.incidentes_pendentes),
                "ultimos_resolvidos": self.incidentes_resolvidos[-5:] if self.incidentes_resolvidos else [],
                "ultimos_em_resolucao": self.incidentes_em_resolucao[-5:] if self.incidentes_em_resolucao else [],
                "ultimos_pendentes": self.incidentes_pendentes[-5:] if self.incidentes_pendentes else [],
            }
    
    def _atualizar_estado(self, incidente_id: int, status: str):
        conn = get_db()
        conn.execute(
            "INSERT INTO estado_incidentes (incidente_id, status) VALUES (?, ?)",
            (incidente_id, status)
        )
        conn.commit()
        conn.close()
    
    def _remover_da_lista(self, incidente_id: int, lista: str):
        if lista == "em_resolucao":
            self.incidentes_em_resolucao = [x for x in self.incidentes_em_resolucao
                                           if x["incidente_id"] != incidente_id]
        elif lista == "todas":
            self.incidentes_resolvidos = [x for x in self.incidentes_resolvidos
                                         if x["incidente_id"] != incidente_id]
            self.incidentes_em_resolucao = [x for x in self.incidentes_em_resolucao
                                           if x["incidente_id"] != incidente_id]
            self.incidentes_pendentes = [x for x in self.incidentes_pendentes
                                        if x["incidente_id"] != incidente_id]
