"""
RAG de Politicas - Documentacao dos limites de atuacao dos agentes.

Cada agente consulta este RAG para saber:
- Que acoes pode tomar (nivel de autonomia)
- Qual o blast radius de cada componente
- Regras de reincidencia
- Runbooks de procedimentos

Assim a logica nao fica embutida no codigo.
"""

import os
import json
from pathlib import Path

DB_PATH = os.environ.get("SENTINEL_DB", str(Path(__file__).parent.parent / "data" / "sentinel.db"))

# Documentos de politica que serao indexados no RAG
POLICY_DOCUMENTS = [
    {
        "id": "matriz_autonomia_n1",
        "titulo": "Nivel 1 - Auto-resolve",
        "conteudo": """ACOES DE NIVEL 1 - AUTO-RESOLVE
Caracteristicas: acao reversivel, baixo blast radius (afeta apenas 1 componente), risco minimo.
O agente pode executar sozinho, sem aprovacao. Apenas reporta ao supervisor depois.
Exemplos:
- DashboardMonitor: forcar refresh de cache do dashboard
- JobsMonitor: matar step travado, reiniciar processo
- IAMonitor: escalar replica do modelo de IA
- RedeMonitor: nenhuma acao N1 (rede tem blast radius alto por padrao)
Regra: se o mesmo incidente reaparecer em menos de 15 minutos, nao insistir - escalar para N3.""",
        "agentes": ["DashboardMonitor", "JobsMonitor", "IAMonitor"],
        "componentes": ["dashboard_vendas", "job_sync_vendas", "fila_jobs", "agente_ia_recomendacao"],
    },
    {
        "id": "matriz_autonomia_n2",
        "titulo": "Nivel 2 - Auto-resolve com verificacao",
        "conteudo": """ACOES DE NIVEL 2 - AUTO-RESOLVE COM VERIFICACAO
Caracteristicas: acao reversivel, impacto temporario, risco medio.
O agente executa, verifica o resultado, e reverte ou escala se nao resolver.
Exemplos:
- JobsMonitor: reiniciar job inteiro quando step reiniciado nao resolver
- DashboardMonitor: recarregar fonte de dados do dashboard
Regra: se a verificacao falhar, escalar para N3 automaticamente.
Tempo de verificacao: 30 segundos apos execucao da acao.""",
        "agentes": ["DashboardMonitor", "JobsMonitor"],
        "componentes": ["dashboard_vendas", "job_sync_vendas"],
    },
    {
        "id": "matriz_autonomia_n3",
        "titulo": "Nivel 3 - Sugere e aguarda aprovacao",
        "conteudo": """ACOES DE NIVEL 3 - SUGERE E AGUARDA APROVACAO HUMANA
Caracteristicas: alto impacto, irreversivel ou dificil de reverter, afeta multiplos sistemas.
O agente NAO executa nada sozinho. Gera uma proposta detalhada com:
- Diagnostico da causa raiz
- Acao proposta
- Justificativa (por que essa acao e necessaria)
- Riscos de nao agir
O Supervisor apresenta a proposta ao humano, que autoriza ou nega.
Exemplos:
- RedeMonitor: alterar rota de rede, modificar configuracao de firewall
- JobsMonitor: reiniciar servidor de banco de dados
- Qualquer acao em componente com blast radius ALTO (api_gateway, servico_a, servico_b)
Regra de reincidencia N3: se for a segunda ocorrencia do mesmo incidente em menos de 15 minutos,
o agente deve mencionar a reincidencia na proposta para o humano decidir.""",
        "agentes": ["DashboardMonitor", "JobsMonitor", "RedeMonitor", "IAMonitor"],
        "componentes": ["api_gateway", "servico_a", "servico_b"],
    },
    {
        "id": "matriz_autonomia_n4",
        "titulo": "Nivel 4 - Observa e documenta",
        "conteudo": """ACOES DE NIVEL 4 - OBSERVA E DOCUMENTA
Caracteristicas: anomalia sem causa clara, sem acao disponivel.
O agente NAO age. Apenas registra a anomalia no banco e notifica o Supervisor.
O Supervisor consolida no relatorio como "pendente de investigacao", sem acao sugerida.
Exemplos:
- Latencia alta sem correlacao com outros componentes
- Erro intermitente sem padrao identificado
- Qualquer anomalia onde a confianca no diagnostico seja menor que 0.5""",
        "agentes": ["DashboardMonitor", "JobsMonitor", "RedeMonitor", "IAMonitor"],
        "componentes": ["*"],
    },
    {
        "id": "runbook_job_travado",
        "titulo": "Runbook: Job travado bloqueando fila",
        "conteudo": """RUNBOOK: JOB TRAVADO BLOQUEANDO FILA
Sintomas: step com duracao > 120s, fila acumulando, dashboard parando de atualizar.
1. JOBSMONITOR: detecta step travado (step_duration_seconds > 120)
2. JOBSMONITOR: classifica como N1 (auto-resolve) - mata o step e reinicia
3. JOBSMONITOR: verifica se o job voltou a executar normalmente apos 30s
4. Se resolveu: notifica DASHBOARDMONITOR e SUPERVISOR
5. Se nao resolveu: escala para N3
6. DASHBOARDMONITOR: verifica se dashboard voltou a atualizar
7. SUPERVISOR: registra incidente como resolvido ou pendente
Causas comuns:
- Lock de banco no step de sync
- Timeout em API externa
- Memoria insuficiente no worker
Reincidencia: se ocorrer de novo em < 15min, nao reiniciar - escalar para N3.""",
        "agentes": ["JobsMonitor", "DashboardMonitor"],
        "componentes": ["job_sync_vendas", "fila_jobs", "dashboard_vendas"],
    },
    {
        "id": "runbook_erro_500",
        "titulo": "Runbook: Servico retornando erro 500",
        "conteudo": """RUNBOOK: SERVICO RETORNANDO ERRO 500
Sintomas: error_rate > 0.10, latency alta, possivelmente correlacionado com deploy recente.
1. DASHBOARDMONITOR: detecta erro 500 no servico
2. DASHBOARDMONITOR: verifica com REDEMONITOR se ha problema de rede
3. REDEMONITOR: investiga conectividade com o servico
4. Se for problema de rede: REDEMONITOR propoe acao N3
5. Se nao for rede: DASHBOARDMONITOR verifica metricas de deploy
6. Se deploy recente identificado: propoe rollback (N3)
7. Se for erro em servico especifico: JOBSMONITOR verifica jobs relacionados
Causas comuns:
- Regression em deploy recente
- Sobrecarga no servico
- Dependencia externa indisponivel
Blast radius: ALTO (afeta todos os clientes do servico) - requer aprovacao humana.""",
        "agentes": ["DashboardMonitor", "RedeMonitor", "JobsMonitor"],
        "componentes": ["api_gateway", "servico_a", "servico_b"],
    },
    {
        "id": "runbook_latencia_ia",
        "titulo": "Runbook: Latencia alta em agente de IA",
        "conteudo": """RUNBOOK: LATENCIA ALTA EM AGENTE DE IA
Sintomas: inference_latency_ms > 3000, error_rate > 0.05, requests_per_min alto.
1. IAMONITOR: detecta latencia alta no modelo de IA
2. IAMONITOR: verifica requests_per_min para confirmar sobrecarga
3. IAMONITOR: classifica como N1 (auto-resolve) - escala replica
4. IAMONITOR: verifica se latencia normalizou apos 30s
5. Se resolveu: notifica SUPERVISOR
6. Se nao resolveu: escala para N3 (pode precisar de mais recursos)
7. Se for erro (nao latencia): IAMONITOR verifica integridade do modelo
Causas comuns:
- Alta demanda (black friday, promocao)
- Modelo grande demais para o hardware
- Problema no provedor de API (se for API externa)
Nota: acao N1 segura porque escalar replica e reversivel e nao afeta outros componentes.""",
        "agentes": ["IAMonitor"],
        "componentes": ["agente_ia_recomendacao"],
    },
    {
        "id": "runbook_rede",
        "titulo": "Runbook: Incidente de rede/infraestrutura",
        "conteudo": """RUNBOOK: INCIDENTE DE REDE/INFRAESTRUTURA
Sintomas: latency_ms > 10000, error_rate > 0.30, multiplos componentes afetados.
1. REDEMONITOR: detecta latencia alta no API Gateway
2. REDEMONITOR: verifica correlacao com outros componentes
3. Se multiplos componentes afetados: confirma incidente de rede
4. REDEMONITOR: classifica como N3 (sempre requer aprovacao - blast radius ALTO)
5. REDEMONITOR: gera proposta contendo:
   - Componentes afetados
   - Possivel causa (saturacao de banda, rota instavel, DNS)
   - Acao proposta (alterar rota, acionar link backup)
   - Risco de nao agir (indisponibilidade total)
6. SUPERVISOR: apresenta ao humano e aguarda decisao
Regra: NUNCA executar acao de rede sem aprovacao humana.
Blast radius: ALTO - afeta todos os servicos que dependem do gateway.""",
        "agentes": ["RedeMonitor"],
        "componentes": ["api_gateway", "servico_a", "servico_b"],
    },
]


class PolicyRAG:
    """RAG simples que consulta documentos de politica."""

    def __init__(self):
        self.documents = POLICY_DOCUMENTS

    def consultar(self, agente_nome: str, componente: str = None, incidente_tipo: str = None) -> list[dict]:
        """Retorna os documentos de politica relevantes para o contexto.
        
        Isso e um RAG simplificado (busca por keywords). Em producao,
        usaria ChromaDB com embeddings para busca semantica.
        """
        resultados = []

        for doc in self.documents:
            score = 0

            # Match por agente
            if agente_nome in doc["agentes"]:
                score += 3

            # Match por componente
            if componente and componente in doc["componentes"]:
                score += 2
            if componente == "*" or componente in [c for c in doc["componentes"]]:
                pass

            # Match por tipo de incidente
            if incidente_tipo and incidente_tipo.lower() in doc["titulo"].lower():
                score += 2
            if incidente_tipo and incidente_tipo.lower() in doc["conteudo"].lower():
                score += 1

            if score > 0:
                resultados.append({"documento": doc["id"], "titulo": doc["titulo"],
                                   "conteudo": doc["conteudo"], "relevancia": score})

        # Ordenar por relevancia
        resultados.sort(key=lambda x: x["relevancia"], reverse=True)
        return resultados

    def classificar_nivel_por_politica(self, agente_nome: str, componente: str) -> dict:
        """Consulta a politica para determinar o nivel de autonomia."""
        docs = self.consultar(agente_nome, componente)

        # Procurar match exato de componente na matriz de autonomia
        for nivel_id in ["matriz_autonomia_n1", "matriz_autonomia_n2",
                         "matriz_autonomia_n3", "matriz_autonomia_n4"]:
            for doc in docs:
                if doc["documento"] == nivel_id:
                    # Verificar se o agente aparece no documento
                    if agente_nome in doc["conteudo"] or any(c in doc["conteudo"] for c in [componente]):
                        nivel = int(nivel_id[-1])
                        return {"nivel": nivel, "justificativa": doc["conteudo"][:200],
                                "runbook": self._get_runbook(agente_nome, componente)}
                    # Se o documento lista explicitamente os componentes
                    for doc_def in self.documents:
                        if doc_def["id"] == nivel_id and (componente in doc_def["componentes"] or "*" in doc_def["componentes"]):
                            if agente_nome in doc_def["agentes"]:
                                nivel = int(nivel_id[-1])
                                return {"nivel": nivel, "justificativa": doc_def["conteudo"][:200],
                                        "runbook": self._get_runbook(agente_nome, componente)}

        # Fallback: nivel 2 padrao
        return {"nivel": 2, "justificativa": "Nivel padrao (N2) quando nao ha politica especifica",
                "runbook": None}

    def _get_runbook(self, agente_nome: str, componente: str):
        docs = self.consultar(agente_nome, componente)
        for doc in docs:
            if doc["documento"].startswith("runbook_"):
                return doc["conteudo"]
        return None


# Singleton
_policy_rag = None

def get_policy_rag() -> PolicyRAG:
    global _policy_rag
    if _policy_rag is None:
        _policy_rag = PolicyRAG()
    return _policy_rag
