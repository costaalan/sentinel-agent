# Sentinel Agent ⚡

Sistema multiagente autonomo de AIOps (Auditoria de Sistemas Internos / Infraestrutura de Rede / Aplicacoes de IA).

**Diferencial:** Multiplos agentes especialistas que conversam entre si para diagnosticar e resolver incidentes colaborativamente, sob supervisao de um Agente Supervisor Geral que administra o que e resolvido automaticamente e o que precisa de decisao humana.

## Arquitetura

```

┌─────────────────────────────────────────────────────────────────┐
│                       SUPERVISOR GERAL                          │
│  Central de Estado: resolvidos │ em resolucao │ pendentes       │
└────┬────────────────────┬─────────────────────┬─────────────────┘
     │                    │                     │
┌────▼─────┐      ┌──────▼──────┐      ┌──────▼──────┐
│Dashboard  │◄────►│  Jobs       │      │  Rede       │  ← mais agentes
│Monitor    │      │  Monitor    │      │  Monitor    │    podem ser
└────┬─────┘      └──────┬──────┘      └──────┬──────┘    adicionados
     │                    │                     │
     └────────┬───────────┴──────────┬──────────┘
              │                      │
     ┌────────▼────────┐   ┌────────▼────────┐
     │   PostgreSQL    │   │    Ollama LLM   │
     │   (metricas,    │   │  (raciocinio    │
     │   mensagens,    │   │   local, sem    │
     │   incidentes)   │   │   API paga)     │
     └─────────────────┘   └─────────────────┘
              ▲
              │
     ┌────────┴────────┐
     │   Simulador     │  ← processo separado, NAO e um agente
     │  de Dados       │
     │  (incidentes    │
     │   programados)  │
     └─────────────────┘
```

### Comunicacao entre Agentes

Os agentes NAO seguem o modelo simples "supervisor -> especialista -> supervisor".
Eles se comunicam horizontalmente antes de subir ao supervisor:

```
DashboardMonitor → JobsMonitor: "Painel parou de atualizar, ha algo rodando?"
JobsMonitor → DashboardMonitor: "Step sync_vendas travado. Assumindo restart (N1)."
JobsMonitor → Supervisor: "Step reiniciado, incidente resolvido."
DashboardMonitor → Supervisor: "Confirmo, dashboard normalizado."
```

## Stack

| Componente | Tecnologia |
|---|---|
| Orquestracao multiagente | LangGraph (Python) |
| LLM de raciocinio | Ollama (local, sem API paga) |
| Persistencia | SQLite (viavel ate ~10 agentes; PostgreSQL recomendado em producao) |
| Backend | FastAPI + WebSocket |
| Frontend | HTML + Canvas puro |
| Containerizacao | Docker + docker-compose |

## Matriz de Autonomia

| Nivel | Tipo | Exemplo | Comportamento |
|---|---|---|---|
| N1 | Auto-resolve | Job travado → mata processo | Executa sozinho, reporta depois |
| N2 | Auto-resolve com verificacao | Servico com erro → restart | Executa, verifica, escala se falhar |
| N3 | Sugere e aguarda | Escalar cluster | Propoe ao Supervisor, humano autoriza |
| N4 | Observa e documenta | Latencia alta sem causa clara | Registra e notifica, sem acao |

## Escalabilidade

O sistema foi projetado para ser escalavel horizontalmente em numero de agentes:

1. **agent_registry** em `agent/core.py` — um dict que mapeia nome → classe
2. Para adicionar um novo agente: crie uma subclasse de `SpecialistAgent` e registre
3. O `SupervisorGeral` descobre automaticamente todos os agentes registrados
4. O frontend lista agentes dinamicamente via API

```python
from agent.core import SpecialistAgent, agent_registry

class RedeMonitor(SpecialistAgent):
    name = "RedeMonitor"
    components_monitored = ["link_principal", "dns"]
    ...

agent_registry["RedeMonitor"] = RedeMonitor  # pronto, 3 agentes
```

## Pre-requisitos

- Python 3.11+
- Ollama instalado e rodando (`ollama serve`)
- Modelo baixado (`ollama pull qwen2.5:7b` ou outro)

## Como rodar localmente

```bash
# 1. Clone
git clone https://github.com/costaalan/sentinel-agent.git
cd sentinel-agent

# 2. Ambiente Python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edite OLLAMA_HOST, OLLAMA_MODEL se necessario

# 4. Inicie o simulador (terminal 1)
python -m data_pipeline.simulator

# 5. Inicie o backend (terminal 2)
python -m backend.main

# Acesse: http://localhost:8701
```

### Com Docker

```bash
docker compose up -d
```

## Estrutura do Repositorio

```
sentinel-agent/
├── data_pipeline/       # Simulador de metricas (processo separado, nao e agente)
│   └── simulator.py     # Gera dados sinteticos com incidentes programados
├── agent/               # Nucleo multiagente
│   ├── core.py          # Base class SpecialistAgent + registry + agentes
│   ├── supervisor.py    # Agente Supervisor Geral
│   └── orchestrator.py  # Orquestrador LangGraph
├── backend/             # API REST + WebSocket
│   └── main.py          # FastAPI
├── frontend/            # Interface web
│   └── index.html       # Dashboard com grafo animado + chat log
├── docs/                # Documentacao
│   ├── ARQUITETURA.md
│   ├── MATRIZ_AUTONOMIA.md
│   └── SEGURANCA.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Diferenciais

- **Custo zero de inferencia** — LLM roda local via Ollama, sem API paga
- **100% offline** — possivel rodar sem internet apos baixar o modelo
- **Privacidade** — dados nunca saem da maquina
- **Conversa entre agentes** — nao e um mero roteador, agentes colaboram
- **Matriz de autonomia formal** — niveis de decisao claros, como em producao
- **Arquitetura escalavel** — adicionar agentes e registrar uma classe
