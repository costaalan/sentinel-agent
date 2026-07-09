"""
Sentinel Agent - Core de agentes especialistas.

Arquitetura escalavel: todo agente especialista herda de SpecialistAgent.
Para adicionar um novo agente, basta criar uma subclasse e registrar.
"""

import os
import sqlite3
import json
import datetime
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from abc import ABC, abstractmethod

# Config
DB_PATH = os.environ.get("SENTINEL_DB", str(Path(__file__).parent.parent / "data" / "sentinel.db"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
AGENT_CHECK_INTERVAL = int(os.environ.get("AGENT_INTERVAL", 10))

# Niveis de autonomia
AUTONOMY_LEVELS = {
    1: "auto_resolve",
    2: "auto_resolve_com_verificacao",
    3: "sugere_e_aguarda",
    4: "observa_e_documenta",
}


def call_llm(prompt: str, system: str = "", max_tokens: int = 300) -> str:
    """Chama Ollama local."""
    url = f"{OLLAMA_HOST}/api/generate"
    data = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.1, "max_tokens": max_tokens},
    }).encode()

    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        print(f"[LLM ERROR] {e}")
        return ""


def get_db():
    return sqlite3.connect(DB_PATH)


class AgentMessage:
    """Mensagem estruturada entre agentes."""
    def __init__(self, remetente: str, destinatario: str, tipo: str, conteudo: str,
                 incidente_id: Optional[int] = None):
        self.remetente = remetente
        self.destinatario = destinatario
        self.tipo = tipo  # pergunta, resposta, notificacao, proposta_de_acao, resultado
        self.conteudo = conteudo
        self.incidente_id = incidente_id
        self.timestamp = datetime.datetime.now().isoformat()

    def save(self):
        conn = get_db()
        conn.execute(
            "INSERT INTO mensagens_agentes (remetente, destinatario, tipo, conteudo, incidente_id) VALUES (?, ?, ?, ?, ?)",
            (self.remetente, self.destinatario, self.tipo, self.conteudo, self.incidente_id)
        )
        conn.commit()
        conn.close()

    def to_dict(self):
        return {
            "remetente": self.remetente,
            "destinatario": self.destinatario,
            "tipo": self.tipo,
            "conteudo": self.conteudo,
            "incidente_id": self.incidente_id,
            "timestamp": self.timestamp,
        }


class SpecialistAgent(ABC):
    """Classe base para todos os agentes especialistas.
    
    Para adicionar um novo agente:
    1. Crie uma subclasse de SpecialistAgent
    2. Defina nome, descricao e componentes_monitorados
    3. Implemente detectar_anomalia() e diagnosticar()
    4. Registre em agent_registry
    """
    
    name: str = ""
    description: str = ""
    components_monitored: list[str] = []
    MIN_CONFIDENCE_THRESHOLD: float = 0.6
    
    def __init__(self, supervisor):
        self.supervisor = supervisor
        from agent.policy_rag import get_policy_rag
        self._rag = get_policy_rag()
    
    @abstractmethod
    def detectar_anomalia(self, conn) -> Optional[dict]:
        """Verifica metricas no banco e retorna anomalia detectada ou None."""
        pass
    
    @abstractmethod
    def diagnosticar(self, anomalia: dict, conn) -> dict:
        """Diagnostica a causa raiz da anomalia."""
        pass
    
    def classificar_nivel(self, anomalia: dict) -> int:
        """Classifica o nivel de autonomia baseado na politica (RAG)."""
        componente = anomalia.get("componente", "")
        resultado = self._rag.classificar_nivel_por_politica(self.name, componente)
        nivel = resultado["nivel"]
        
        # Log da politica consultada
        print(f"[{self.name}] RAG consultado: nivel={nivel}, justificativa={resultado['justificativa'][:60]}...")
        
        # Se tem runbook, registrar no diagnostico
        if resultado.get("runbook"):
            print(f"[{self.name}] Runbook aplicavel: {resultado['runbook'][:80]}...")
        
        return nivel
    
    def _validate_confidence(self, diagnostico: dict) -> bool:
        """Verifica se a confianca do diagnostico atinge o threshold minimo.
        
        Retorna True se confianca >= MIN_CONFIDENCE_THRESHOLD, False caso contrario.
        Agentes podem sobrescrever MIN_CONFIDENCE_THRESHOLD para ajustar por dominio.
        """
        confianca = diagnostico.get("confianca", 0.0)
        if confianca < self.MIN_CONFIDENCE_THRESHOLD:
            print(f"[{self.name}] CONFIANCA BAIXA: {confianca:.2f} < {self.MIN_CONFIDENCE_THRESHOLD} "
                  f"- escalando para revisao humana (N3)")
            return False
        print(f"[{self.name}] Confianca OK: {confianca:.2f} >= {self.MIN_CONFIDENCE_THRESHOLD}")
        return True
    
    def executar_acao(self, anomalia: dict, diagnostico: dict) -> dict:
        """Executa a acao e retorna resultado."""
        return {"sucesso": True, "detalhes": "Acao simulada executada com sucesso."}
    
    def verificar_resultado(self, acao: dict) -> bool:
        """Verifica se a acao resolveu o problema."""
        return True
    
    def consultar_outro_agente(self, agente_nome: str, pergunta: str, incidente_id: int) -> str:
        """Envia uma mensagem para outro agente especialista."""
        msg = AgentMessage(
            remetente=self.name,
            destinatario=agente_nome,
            tipo="pergunta",
            conteudo=pergunta,
            incidente_id=incidente_id,
        )
        msg.save()
        print(f"[{self.name}] -> {agente_nome}: {pergunta}")
        
        # O outro agente responde via supervisor
        resposta = self.supervisor.encaminhar_pergunta(agente_nome, pergunta, incidente_id, self.name)
        return resposta
    
    def notificar_supervisor(self, tipo: str, conteudo: str, incidente_id: int, nivel: int):
        """Notifica o supervisor sobre o que aconteceu."""
        msg = AgentMessage(
            remetente=self.name,
            destinatario="Supervisor",
            tipo=tipo,
            conteudo=conteudo,
            incidente_id=incidente_id,
        )
        msg.save()
        print(f"[{self.name}] -> Supervisor [{tipo}]: {conteudo[:80]}...")
        self.supervisor.receber_notificacao(self.name, tipo, conteudo, incidente_id, nivel)
    
    def run_cycle(self):
        """Ciclo completo do agente especialista."""
        conn = get_db()
        try:
            anomalia = self.detectar_anomalia(conn)
            if not anomalia:
                return None
            
            print(f"[{self.name}] Anomalia detectada: {anomalia.get('descricao', anomalia)}")
            
            # Diagnosticar
            diagnostico = self.diagnosticar(anomalia, conn)
            incidente_id = anomalia.get("incidente_id", int(datetime.datetime.now().timestamp()))
            
            # --- GUARDRAIL: verificar confianca do diagnostico ---
            if not self._validate_confidence(diagnostico):
                # Confianca baixa: forcar N3 (propor ao supervisor, NAO agir)
                self.notificar_supervisor("proposta_de_acao",
                    json.dumps({
                        "diagnostico": diagnostico,
                        "acao_proposta": self.executar_acao(anomalia, diagnostico),
                        "nivel": 3,
                        "justificativa": f"Confianca do diagnostico ({diagnostico.get('confianca', 0.0):.2f}) "
                                         f"abaixo do threshold ({self.MIN_CONFIDENCE_THRESHOLD}). "
                                         f"Requer revisao humana antes de qualquer acao."
                    }),
                    incidente_id, 3)
                conn.commit()
                return {"anomalia": anomalia, "nivel": 3, "incidente_id": incidente_id,
                        "confianca_baixa": True}
            
            # Nivel de autonomia (RAG)
            nivel = self.classificar_nivel(anomalia)
            
            if nivel <= 2:
                # Executar acao (N1/N2 - autonomo)
                self.notificar_supervisor("acao_em_andamento",
                    f"Diagnostiquei: {diagnostico.get('causa', 'causa desconhecida')}. Assumindo acao Nivel {nivel}.",
                    incidente_id, nivel)
                
                acao = self.executar_acao(anomalia, diagnostico)
                
                if self.verificar_resultado(acao):
                    self.notificar_supervisor("resultado",
                        f"Incidente resolvido: {acao.get('detalhes', 'acao concluida')}",
                        incidente_id, nivel)
                else:
                    self.notificar_supervisor("resultado",
                        f"Falha ao resolver. Escalando para investigacao.",
                        incidente_id, nivel)
            else:
                # N3/N4 - propor ao supervisor
                self.notificar_supervisor("proposta_de_acao",
                    json.dumps({
                        "diagnostico": diagnostico,
                        "acao_proposta": self.executar_acao(anomalia, diagnostico),
                        "nivel": nivel,
                        "justificativa": f"Acao de nivel {nivel} requer autorizacao humana."
                    }),
                    incidente_id, nivel)
            
            conn.commit()
            return {"anomalia": anomalia, "nivel": nivel, "incidente_id": incidente_id}
            
        finally:
            conn.close()


# --- AGENTES ESPECIALISTAS ---

class DashboardMonitor(SpecialistAgent):
    """Monitora paineis e dashboards - verifica se estao atualizando."""
    name = "DashboardMonitor"
    description = "Monitora se paineis, endpoints e interfaces estao respondendo"
    components_monitored = ["dashboard_vendas"]
    
    def detectar_anomalia(self, conn) -> Optional[dict]:
        cursor = conn.execute(
            "SELECT valor, timestamp FROM metricas WHERE componente = 'dashboard_vendas' "
            "AND tipo_metrica = 'last_update_seconds_ago' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row[0] > 30:  # mais de 30s sem atualizar
            return {
                "componente": "dashboard_vendas",
                "metrica": "last_update_seconds_ago",
                "valor": row[0],
                "descricao": f"Dashboard nao atualiza ha {row[0]:.0f}s",
                "timestamp": row[1],
            }
        return None
    
    def classificar_nivel(self, anomalia: dict) -> int:
        if anomalia["valor"] > 300:
            return 3  # muito tempo parado, pode ser grave
        return 2
    
    def diagnosticar(self, anomalia: dict, conn) -> dict:
        # Antes de assumir, pergunta ao JobsMonitor se ha algo relacionado
        prompt = f"""Dashboard '{anomalia['componente']}' parou de atualizar ha {anomalia['valor']:.0f}s.
Analise: qual a causa mais provavel para um dashboard parar de atualizar?
Responda em JSON: {{"causa": "...", "confianca": 0.0-1.0, "sugestao": "..."}}"""
        
        resposta = call_llm(prompt, system="Voce e um analista de sistemas diagnosticando problemas.")
        
        try:
            return json.loads(resposta)
        except:
            return {"causa": "job de sync travado (provarel)", "confianca": 0.7, "sugestao": "verificar job_sync_vendas"}
    
    def executar_acao(self, anomalia: dict, diagnostico: dict) -> dict:
        # Simular: forcar refresh do cache
        return {"sucesso": True, "detalhes": "Refresh de cache forçado no dashboard"}


class JobsMonitor(SpecialistAgent):
    """Monitora jobs e processos."""
    name = "JobsMonitor"
    description = "Monitora duracao de jobs, steps travados e filas"
    components_monitored = ["job_sync_vendas", "fila_jobs"]
    
    def detectar_anomalia(self, conn) -> Optional[dict]:
        # Verificar job sync_vendas
        cursor = conn.execute(
            "SELECT valor, timestamp FROM metricas WHERE componente = 'job_sync_vendas' "
            "AND tipo_metrica = 'step_duration_seconds' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row[0] > 120:
            return {
                "componente": "job_sync_vendas",
                "metrica": "step_duration_seconds",
                "valor": row[0],
                "descricao": f"Step do job sync_vendas travado ha {row[0]:.0f}s",
                "timestamp": row[1],
            }
        
        # Verificar fila
        cursor = conn.execute(
            "SELECT valor, timestamp FROM metricas WHERE componente = 'fila_jobs' "
            "AND tipo_metrica = 'queue_size' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row[0] > 100:
            return {
                "componente": "fila_jobs",
                "metrica": "queue_size",
                "valor": row[0],
                "descricao": f"Fila de jobs acumulando: {row[0]:.0f} itens",
                "timestamp": row[1],
            }
        return None
    
    def classificar_nivel(self, anomalia: dict) -> int:
        if anomalia["componente"] == "fila_jobs" and anomalia["valor"] > 200:
            return 2
        return 1  # step travado pode ser reiniciado com seguranca
    
    def diagnosticar(self, anomalia: dict, conn) -> dict:
        prompt = f"""Job '{anomalia['componente']}' apresenta anomalia: {anomalia['descricao']}
Diagnostique a causa raiz e sugira uma acao.
Responda em JSON: {{"causa": "...", "confianca": 0.0-1.0, "sugestao": "..."}}"""
        
        resposta = call_llm(prompt, system="Voce e um engenheiro de software debugando processos.")
        
        try:
            return json.loads(resposta)
        except:
            return {"causa": "step travado por lock de banco", "confianca": 0.8, "sugestao": "reiniciar step"}
    
    def executar_acao(self, anomalia: dict, diagnostico: dict) -> dict:
        return {"sucesso": True, "detalhes": f"Step reiniciado. Job {anomalia['componente']}恢复正常."}


class RedeMonitor(SpecialistAgent):
    """Monitora conectividade e saturacao de rede."""
    name = "RedeMonitor"
    description = "Monitora disponibilidade de servicos e saturacao de rede"
    components_monitored = ["api_gateway", "servico_b"]
    
    def detectar_anomalia(self, conn) -> Optional[dict]:
        cursor = conn.execute(
            "SELECT valor, timestamp FROM metricas WHERE componente = 'api_gateway' "
            "AND tipo_metrica = 'latency_ms' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row[0] > 5000:
            return {
                "componente": "api_gateway",
                "metrica": "latency_ms",
                "valor": row[0],
                "descricao": f"Latencia alta no API Gateway: {row[0]:.0f}ms",
                "timestamp": row[1],
            }
        return None
    
    def classificar_nivel(self, anomalia: dict) -> int:
        return 3  # rede tem blast radius alto, sempre Nivel 3
    
    def diagnosticar(self, anomalia: dict, conn) -> dict:
        return {"causa": "possivel saturacao de banda ou rota instavel", "confianca": 0.6, "sugestao": "verificar link primario"}
    
    def executar_acao(self, anomalia: dict, diagnostico: dict) -> dict:
        return {"sucesso": False, "detalhes": "Requer autorizacao humana - acao de rede Nivel 3"}


class IAMonitor(SpecialistAgent):
    """Monitora SLA e performance de agentes/servicos de IA."""
    name = "IAMonitor"
    description = "Monitora latencia e taxa de erro de servicos de IA"
    components_monitored = ["agente_ia_recomendacao"]
    
    def detectar_anomalia(self, conn) -> Optional[dict]:
        cursor = conn.execute(
            "SELECT valor, timestamp FROM metricas WHERE componente = 'agente_ia_recomendacao' "
            "AND tipo_metrica = 'inference_latency_ms' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row[0] > 3000:
            return {
                "componente": "agente_ia_recomendacao",
                "metrica": "inference_latency_ms",
                "valor": row[0],
                "descricao": f"Latencia de inferencia alta: {row[0]:.0f}ms",
                "timestamp": row[1],
            }
        return None
    
    def classificar_nivel(self, anomalia: dict) -> int:
        return 1  # escalar replica e seguro e reversivel
    
    def diagnosticar(self, anomalia: dict, conn) -> dict:
        cursor = conn.execute(
            "SELECT valor FROM metricas WHERE componente = 'agente_ia_recomendacao' "
            "AND tipo_metrica = 'requests_per_min' ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        rps = row[0] if row else 0
        return {"causa": f"alta demanda ({rps:.0f} req/min) sobrecarregando o modelo", "confianca": 0.8, "sugestao": "escalar replica do modelo"}
    
    def executar_acao(self, anomalia: dict, diagnostico: dict) -> dict:
        return {"sucesso": True, "detalhes": "Replica do modelo escalada automaticamente (Nivel 1)"}


# Registry de agentes - para adicionar novo agente, registre aqui
# Basta: from agent.novo_agente import NovoAgente
#        agent_registry["NovoAgente"] = NovoAgente
agent_registry: dict[str, type[SpecialistAgent]] = {
    "DashboardMonitor": DashboardMonitor,
    "JobsMonitor": JobsMonitor,
    "RedeMonitor": RedeMonitor,
    "IAMonitor": IAMonitor,
}


def get_agent_names() -> list[str]:
    return list(agent_registry.keys())
