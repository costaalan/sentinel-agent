# Arquitetura — Sentinel Agent

## Visao Geral

O Sentinel Agent e um sistema multiagente onde agentes especialistas
monitoram componentes de infraestrutura, diagnosticam anomalias
colaborativamente e reportam a um Supervisor Geral.

## Decisoes Tecnicas

### Por que Ollama (LLM local)?

- Custo zero de inferencia
- Privacidade: dados nunca saem da maquina
- 100% offline apos baixar o modelo
- Modelos como qwen2.5:7b oferecem bom equilibrio entre qualidade e hardware

### Por que comunicacao horizontal entre agentes?

O padrao comum em demos de multiagente e supervisor -> especialista -> supervisor.
No Sentinel, agentes especialistas conversam entre si primeiro (ex: Dashboard pergunta
a Jobs), e so depois reportam ao supervisor. Isso:
- Reduz carga no supervisor
- Permite diagnosticos mais rapidos
- Simula como times reais de SRE trabalham

### Por que o simulador e separado dos agentes?

O simulador e um pipeline de dados, nao um agente. Ele:
- Nao raciocina
- Nao le mensagens de outros agentes
- Apenas escreve metricas e incidentes no banco
Isso segue o padrao real de observabilidade: fonte de dados -> storage -> consumidores.

### Por que SQLite (e nao Postgres)?

SQLite e suficiente para demonstracao com ate ~10 agentes.
Para producao, recomenda-se PostgreSQL (basta mudar DATABASE_URL).

## Fluxo de Dados

```
Simulador (processo separado)
  │
  ▼
SQLite (metricas, incidentes_injetados)
  │
  ├── Agente Especialista 1 (le metricas periodicamente)
  │     ├── Detecta anomalia
  │     ├── Consulta Agente 2 (se necessario)
  │     ├── Classifica nivel de autonomia
  │     ├── Executa acao ou propoe ao Supervisor
  │     └── Notifica Supervisor
  │
  ├── Agente Especialista 2 (le metricas periodicamente)
  │     └── (mesmo ciclo)
  │
  └── Supervisor Geral
        ├── Recebe notificacoes
        ├── Atualiza central de estado
        └── Decide o que reportar ao humano
              │
              ▼
          WebSocket → Frontend (grafo animado + chat log)
```

## Tabelas do Banco

### metricas
| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER | PK |
| componente | TEXT | Nome do componente |
| tipo_metrica | TEXT | latency_ms, error_rate, etc |
| valor | REAL | Valor numerico |
| timestamp | DATETIME | Momento da coleta |

### incidentes_injetados
| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER | PK |
| nome | TEXT | Nome do cenario |
| causa_raiz_real | TEXT | Causa conhecida (para comparar) |
| componente_afetado | TEXT | Componente principal |
| ativo | INTEGER | 1 = ativo, 0 = resolvido |

### mensagens_agentes
| Coluna | Tipo | Descricao |
|---|---|---|
| id | INTEGER | PK |
| remetente | TEXT | Quem enviou |
| destinatario | TEXT | Quem recebeu |
| tipo | TEXT | pergunta, resposta, notificacao, proposta |
| conteudo | TEXT | Corpo da mensagem |
| incidente_id | INTEGER | Para agrupar conversa |

## Como Adicionar um Novo Agente

```python
from agent.core import SpecialistAgent, agent_registry

class RedeMonitor(SpecialistAgent):
    name = "RedeMonitor"
    description = "Monitora conectividade e saturacao de rede"
    components_monitored = ["link_principal", "dns", "firewall"]

    def detectar_anomalia(self, conn):
        # Implementar logica de deteccao
        pass

    def diagnosticar(self, anomalia, conn):
        # Implementar diagnostico
        pass

# Registrar
agent_registry["RedeMonitor"] = RedeMonitor
```

O orquestrador e o frontend descobrem automaticamente.
