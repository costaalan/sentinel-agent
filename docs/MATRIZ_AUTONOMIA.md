# Matriz de Autonomia — Sentinel Agent

Documento formal definindo o que cada agente pode fazer sozinho,
o que requer autorizacao, e o que apenas observa.

## Tabela de Niveis

| Nivel | Tipo | Reversivel? | Blast Radius | Exemplo | Acao do Agente | Papel do Supervisor |
|---|---|---|---|---|---|---|
| **N1** | Auto-resolve | Sim | Baixo (1 componente) | Job travado bloqueando fila → mata o processo | Executa sozinho, sem aprovacao | Apenas registra e reporta ao humano depois (informativo) |
| **N2** | Auto-resolve com verificacao | Sim | Medio (impacto temporario) | Servico em erro 500 → restart → monitora N minutos | Executa, verifica resultado, reverte/escala se nao resolver | Acompanha e registra; escala para N3 se houver reincidencia |
| **N3** | Sugere e aguarda aprovacao | Nao | Alto (afeta multiplos sistemas) | Escalar cluster inteiro, alterar configuracao de rede | Gera proposta detalhada + justificativa, envia ao Supervisor | Apresenta a proposta ao humano, aguarda autorizacao, delega ou arquiva |
| **N4** | Observa e documenta | N/A | N/A (sem acao) | Latencia alta sem correlacao obvia entre agentes | Nao age, apenas registra e notifica o Supervisor | Consolida no relatorio como "pendente de investigacao" |

## Regra de Reincidencia

Se uma acao de N1 ou N2 resolver o problema mas o mesmo incidente
reaparecer em intervalo < 15 minutos (configuravel via `REINCIDENCE_WINDOW`),
o agente nao deve insistir automaticamente.

**Comportamento:** escala para N3 na segunda ocorrencia, pois
reincidencia rapida indica causa mais profunda.

## Mapa por Agente

| Agente | N1 | N2 | N3 | N4 |
|---|---|---|---|---|
| DashboardMonitor | Forcar refresh de cache | N/A | Dashboard parado > 5min | Leve degradacao de performance |
| JobsMonitor | Matar step travado | Reiniciar job inteiro | Job com reincidencia < 15min | Job lento mas dentro do esperado |
| RedeMonitor (futuro) | N/A | N/A | Alterar rota/configuracao | Saturação de banda |
| IAMonitor (futuro) | Escalar replica | N/A | Reduzir/reconfigurar modelo | Aumento de latencia sem causa |
