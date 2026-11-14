# triagem-n1-agentes

Sistema multiagente de triagem N1 para o Tema 1 do Hackathon UNIFEI 2026. O fluxo
usa Triador, Revisor, políticas determinísticas, Executor MCP e fila local para
aprovação humana.

## Requisitos

- Python 3.12
- Um servidor MCP Streamable HTTP acessível em `http://localhost:8765/mcp`

## Preparação do ambiente

Crie e ative um ambiente virtual com Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Copie `.env.example` para `.env` e ajuste as variáveis conforme necessário.
Não armazene chaves ou credenciais no repositório.

## Variáveis de ambiente

| Variável | Descrição | Padrão |
| --- | --- | --- |
| `TRIAGEM_MCP_URL` | URL do servidor MCP Streamable HTTP | `http://localhost:8765/mcp` |
| `TRIAGEM_BANCO_CAMINHO` | Caminho do arquivo SQLite local | `data/triagem.db` |
| `TRIAGEM_NIVEL_LOG` | Nível mínimo dos logs | `INFO` |
| `TRIAGEM_APROVADOR` | E-mail interno que recebe eventos escalados | não configurado |
| `AI_API_KEY` | Chave do gateway de IA | obrigatório para usar a IA |
| `AI_BASE_URL` | Endereço compatível com a API OpenAI | obrigatório para usar a IA |
| `AI_MODEL` | Modelo liberado pela organização | obrigatório para usar a IA |

## Estrutura

```text
src/triagem_n1_agentes/
├── banco.py       # Acesso inicial ao SQLite
├── configuracao.py # Configuração tipada por ambiente
├── conexao_mcp.py # Diagnóstico de conexão e listagem de ferramentas MCP
├── logs.py        # Configuração de logs estruturados
├── modelos.py     # Modelos tipados com Pydantic
├── orquestrador.py # Máquina de estados persistente
├── politicas.py   # Políticas de criticidade e segurança
└── __init__.py
tests/
├── test_bases_mcp.py
├── test_conexao_mcp.py
├── test_decisao_triagem.py
├── test_orquestrador.py
├── test_politicas.py
└── test_estrutura.py
```

## Teste de conexão MCP

Com o ambiente virtual ativado e o servidor MCP em execução, rode:

```bash
testar-conexao-mcp
```

O comando inicializa uma sessão Streamable HTTP, lista e imprime os nomes das
ferramentas disponíveis e fecha a sessão ao terminar. Ele não executa nenhuma
ferramenta, incluindo `proximo_evento`. Se o servidor não responder, exibe uma
mensagem de erro e termina com código de saída diferente de zero.

## Descoberta de bases

Para consultar as bases e regras disponíveis no início da execução, rode:

```bash
listar-bases-mcp
```

O comando chama somente `listar_bases`, com o agente `orquestrador`, valida a
resposta com modelos Pydantic e imprime o nome, a chave, os campos e as
permissões de registro e atualização de cada base. Ele não consulta nem processa
eventos.

## Classificação de e-mails

Para classificar os e-mails novos usando o Triador e o contexto autorizado do
MCP, execute:

```bash
classificar-emails
```

O comando consulta a base `eventos` e classifica os registros com status `novo`;
não usa `proximo_evento` nem `ler_evento`, e não responde nem altera registros.
A decisão é impressa em JSON, sem o corpo do e-mail. Mensagens com sinais de
credenciais, phishing ou dados pessoais sensíveis são encaminhadas para revisão
humana local e não são enviadas ao modelo. Nos demais casos, e-mails, telefones,
CPFs e o nome do remetente são pseudonimizados antes da análise.

As chamadas a ferramentas MCP e a agentes são registradas como logs JSON na
saída padrão. Os registros identificam o agente (`triador`, `revisor` ou
`executor`), o evento e o resultado, além da ferramenta MCP chamada. Não
registram assunto, remetente ou corpo do e-mail. O nível de log é controlado
por `TRIAGEM_NIVEL_LOG`.

## Teste de conexão com a IA

Depois de preencher o `.env`, execute:

```bash
testar-conexao-ia
```

O diagnóstico faz uma solicitação mínima e informa somente se a conexão foi
confirmada. A chave e a resposta bruta não são exibidas.

## Teste do Triador inteligente

Para validar o prompt e a saída estruturada sem consumir eventos do servidor:

```bash
testar-triador-ia
```

O teste usa um evento fictício de VPN, carrega `prompts/TRIADOR.md`, consulta a
IA e valida a resposta com o modelo Pydantic `DecisaoTriagem`.

## Fluxo LangChain/LangGraph

O primeiro grafo seguro executa:

```text
Triador → Revisor → políticas determinísticas → humano/executor simulado
```

Para executar a demonstração fictícia:

```bash
.venv/bin/python -m triagem_n1_agentes.grafo_langchain
```

A demonstração não chama `proximo_evento` e não executa ferramentas de escrita
do MCP. O nó Executor devolve apenas `EXECUCAO_SIMULADA`.

## Processar um evento real

Com o servidor MCP ativo, execute:

```bash
.venv/bin/python -m triagem_n1_agentes.fluxo_mcp
```

O comando busca um evento, consulta contexto, executa o LangGraph e registra as
conversas entre agentes. Se o Revisor aprovar sem exigir aprovação humana, o
Executor pode responder ao evento ou registrar chamado/incidente pelo MCP. Use
isso somente com um servidor MCP de desenvolvimento e dados de demonstração.

Quando houver escalação, o evento e as decisões dos agentes ficam salvos na fila
SQLite local como `PENDENTE`. O ID, a criticidade e a ação proposta são registrados
na conversa MCP. Se
`TRIAGEM_APROVADOR` estiver configurado com um e-mail `@t4h.exemplo`, o sistema
também tenta enviar uma notificação pelo MCP. Sem esse endereço, a tarefa fica
na fila local, mas não há notificação externa.

Veja as pendências:

```bash
.venv/bin/python -m triagem_n1_agentes.aprovacoes_humanas listar
```

Registre a decisão humana e, se aprovada, continue para o Executor:

```bash
.venv/bin/python -m triagem_n1_agentes.aprovacoes_humanas decidir \
  --evento-id EVENTO-123 \
  --decisao aprovar \
  --aprovador "Nome do responsável" \
  --motivo "Justificativa da aprovação"
```

Para rejeitar, troque `aprovar` por `rejeitar`. O campo `--aprovador` fica no
registro de auditoria; a autenticação da pessoa ainda depende do controle de
acesso ao terminal que executa o comando. Uma aprovação humana não libera uma
ação que o Revisor tenha rejeitado ou deixado sem ação confirmada. O estado da
tarefa impede uma segunda decisão ou execução após uma tentativa iniciada.

## Modelo de decisão de triagem

`DecisaoTriagem` em `modelos.py` representa a classificação e a ação proposta
para um evento. Criticidade, categoria, risco de segurança e ação usam enums;
a confiança é limitada ao intervalo de 0 a 1. O modelo descreve uma proposta,
mas não executa nenhuma ação.

As regras determinísticas em `politicas.py` recebem impacto, risco e presença de
dado pessoal sensível em campos estruturados. A urgência no assunto não altera a
criticidade; P0/P1 exigem incidente e escalação imediata, P2 exige incidente, e
P3/P4 permitem chamado ou resposta. Risco de segurança ou dado pessoal sensível
exige escalação humana. A função retorna apenas um resultado tipado e não executa
as ações permitidas.

## Máquina de estados do orquestrador

`Orquestrador` em `orquestrador.py` valida e persiste as transições na tabela
`historico_transicoes` do SQLite; o estado atual e a reivindicação de execução
ficam em `eventos_orquestracao`. A transição inicial para `RECEBIDO` também é
registrada. Somente eventos `APROVADO` podem começar a execução, por meio de
`executar_uma_vez`.

A reivindicação é gravada atomicamente antes de chamar a ação, impedindo uma
segunda chamada para o mesmo ID mesmo após reinício. Uma falha `FalhaRecuperavel`
é persistida como `ERRO_RECUPERAVEL`; `executar_lote` continua com os demais
eventos. Uma falha anterior à execução pode retornar à análise; depois que a
execução foi reivindicada, ela não é repetida, pois o resultado externo pode ser
incerto.

## Testes

```bash
pytest
```

