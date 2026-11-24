# Triagem N1 — time de agentes (Hackathon UNIFEI 2026, Tema 1)

Sete agentes de IA e uma pessoa fazem o primeiro atendimento dos e-mails internos da T4H: entendem o pedido,
respondem com o FAQ, juntam duplicados, pedem o que falta, abrem chamado ou incidente com a criticidade certa,
lançam férias pela tela do sistema antigo e chamam uma pessoa quando o caso não é deles. Segue o fluxo do
`triagem-n1-agentes.bpmn` (uma raia por agente) e a especificação `especificacao-agentes-triagem-n1.docx`.

## Rodar com um comando

1. Suba o servidor MCP do kit (na pasta `Servidor MCP (Compartilhado)`):
   `python mundo.py --tema triagem` (ou `TEMA=triagem docker compose up --build mundo`).
2. Preencha a IA no arquivo `.env` (já criado a partir de `.env.example`, fora do Git):
   ```
   LLM_API_KEY=sua-chave
   LLM_MODEL=nome-do-modelo
   LLM_BASE_URL=            # vazio para OpenAI; URL do gateway do evento, OpenRouter, Gemini, Ollama etc.
   LLM_MODEL_REVISOR=       # opcional: outro modelo para o Revisor
   ```
   Qualquer API compatível com a da OpenAI serve (Chat Completions). Exemplos de `LLM_BASE_URL`:
   Gemini `https://generativelanguage.googleapis.com/v1beta/openai/`, OpenRouter `https://openrouter.ai/api/v1`,
   Ollama `http://localhost:11434/v1`, Anthropic `https://api.anthropic.com/v1/`. Se o gateway recusar
   `response_format`, o cliente desliga o modo JSON sozinho (ou use `LLM_JSON_MODE=0`).
3. Rode:
   - Windows: `.\rodar.ps1`
   - macOS/Linux: `./rodar.sh`

   Na primeira vez o script cria o `.venv`, instala as dependências e o Chromium do Playwright.
   `.\rodar.ps1 --verificar` testa a conexão com o servidor MCP e com a IA e sai.

| O quê | Endereço |
| --- | --- |
| **Canal humano** (aprovações, escalações, painel de pendências, novo chamado) | http://127.0.0.1:8080 |
| Painel do servidor (ao vivo, com as conversas entre agentes) | http://localhost:8765 |
| Sistema de férias (só tela) | http://localhost:8765/legado |

Enquanto os agentes rodam, ninguém mexe neles (Regra R5): a pessoa fala com o time só pelo canal humano.

## Os 7 agentes (+ 1 pessoa)

| # | Agente (`agente`) | Papel em uma frase | Implementação | Autonomia |
| --- | --- | --- | --- | --- |
| 1 | Despachante (`despachante`) | Dono do laço `proximo_evento`: trata falhas, guarda a memória, entrega e fecha os casos. | Código, sem IA | Faz sozinho (infraestrutura) |
| 2 | Triador (`triador`) | Classifica: segurança, impacto P0–P4, dúvida/pedido, tipo do catálogo e campos. | IA + regras de segurança por código | Só propõe |
| 3 | Pesquisador (`pesquisador`) | Acha duplicados, a resposta no FAQ e o time certo. | Busca por código + IA julga | Só propõe |
| 4 | Revisor (`revisor`) | Classifica sozinho antes de ver a proposta e aplica o checklist. | IA independente + checklist por código | Aprova ou devolve |
| 5 | Executor (`executor`) | Único que registra, atualiza e responde, sempre com `agente`, `motivo` e `evento_id`. | Código + IA para redigir | Faz após o Revisor; espera OK humano |
| 6 | Operador de tela (`operador_tela`) | Lança férias no `/legado` pelo navegador (Playwright). | Navegador + IA lê o formulário | Só após Revisor e OK |
| 7 | Escalador (`escalador`) | Ponte com pessoas: escalações, aprovações, plantonista, painel de pendências. | Código + IA para resumir | Só escala |

**Quem propõe não executa.** Nenhuma proposta vira ação sem passar pelo Revisor; tipos que exigem aprovação só
executam depois da decisão registrada por uma pessoa no canal humano. Os agentes conversam por mensagens
estruturadas (envelope validado) e cada troca relevante aparece no painel do servidor com `registrar_conversa`.

### Matriz de permissões (aplicada no código: chamada fora dela falha antes de chegar ao servidor)

| Agente | consultar / listar_bases | registrar / atualizar | responder_evento / enviar_mensagem | Tela /legado | registrar_conversa |
| --- | --- | --- | --- | --- | --- |
| Despachante | Sim (+ proximo_evento, ler/listar_eventos) | Não | Não | Não | Sim |
| Triador | Sim | Não | Não | Não | Sim |
| Pesquisador | Sim | Não | Não | Não | Sim |
| Revisor | Sim | Não | Não | Não | Sim |
| Executor | Sim | Sim | Sim | Não | Sim |
| Operador de tela | Não | Não | Não | Sim | Sim |
| Escalador | Só times, mensagens, eventos | Não | Sim (escalações, recusas, cobranças) | Não | Sim |

## Fluxo (BPMN)

```
proximo_evento -> Despachante (abre o caso ou retoma um caso aguardando)
  -> Triador: segurança? --sim--> Escalador -> pessoa (nada é enviado ao solicitante)
  -> Triador: impacto real (ignora "URGENTE") -> Pesquisador: duplicado? --sim--> proposta de vínculo
  -> incidente P0/P1/P2 -> proposta abrir_incidente
  -> dúvida -> Pesquisador: FAQ (texto literal) ou encaminhar ao time
  -> pedido -> catálogo + campos; faltou campo -> Executor pede o que falta (aguardar_resposta)
  -> Revisor (classificação independente + checklist) --devolve (até 2x; na 3ª escala)--> Triador
  -> Executor: exige OK? -> Escalador -> pessoa no canal humano -> aprovado/recusado
  -> férias -> Operador de tela (/legado) ; demais -> Executor no MCP
  -> P0/P1 -> Escalador avisa o plantonista na hora
  -> Despachante atualiza a memória curta e a longa e fecha o caso
```

## Memória

- **Curta** (SQLite em `dados/triagem.db`): cada caso com estado, histórico, propostas, revisões, devoluções,
  aprovação e escalação. Sobrevive a uma queda do processo: ao reiniciar, o time retoma os casos.
- **Longa** (mesmo banco, tabela `licoes`): padrões gerais — urgências falsas, remetentes que repetem pedidos,
  sinais de P0/P1, correções do Revisor, mapeamentos frequentes e padrões de aprovação. Uma lição só vale depois de
  confirmada por mais de um caso (ou por uma correção do Revisor) e só as mais relevantes entram nos prompts. A tela
  **Memória longa** do canal humano mostra cada lição e quantas vezes foi usada. Nunca guarda resposta por evento.

## Resiliência

Um único cliente MCP resiliente (`src/mcp_client`): timeout de 20 s; 503 repete com backoff 2/4/8/16 s; 504 em
consulta repete; 504 em ação **confere no servidor antes de repetir** (rotina `ja_foi_feito()` por tipo de ação);
409 consulta e reavalia; 410 para tudo e emite o relatório; conexão perdida reconecta, recarrega as bases e, se o
servidor reiniciou (relógio voltou), abre uma rodada nova sem misturar casos antigos. Idempotência por
`evento_id` (um evento nunca vira dois casos) e por `evento_id + etapa` (uma ação nunca é feita duas vezes).
Um evento que se perdeu (lido mas sem caso) é recuperado pela varredura periódica de `listar_eventos`.

## Canal humano

- **Painel**: o que espera uma pessoa, por categoria, com destaque para P0/P1 sem atendimento.
- **Aprovações**: ação proposta e justificativa; Aprovar/Recusar com comentário; grava quem e quando. Lembretes
  sobem a urgência; silêncio nunca vira aprovação.
- **Escalações**: resumo de 3 linhas, o que o time já fez e a recomendação; Assumir / Resolvida.
- **Histórico**, **Casos** (com a triagem e as revisões de cada um) e **Memória longa**.
- **Novo chamado**: o pedido entra no servidor como evento e passa pelo mesmo time.
- **Perguntar ao time**: "por que o CH-1001 foi P2?" — o Escalador responde com o histórico do caso.
- **Demonstração T14**: botão que faz o Triador rebaixar o próximo P1 para P2, para mostrar o Revisor corrigindo.

## Testes

```bash
.venv/Scripts/python -m pytest -q tests/test_unidades.py      # unitários, sem servidor e sem chave
```

Ponta a ponta (Seção 15.2), contra um servidor de teste e com um **LLM simulado só para testes**
(`tests/llm_simulado.py`, heurísticas genéricas; o sistema real exige a chave):

```bash
# na pasta do servidor
python mundo.py --tema triagem --sem-cenario --porta 8799 --erros 0.15 --segundos-por-dia 1200 --sem-navegador
# nesta pasta
.venv/Scripts/python -m tests.e2e_servidor     # T01–T15 (servidor limpo a cada execução)
.venv/Scripts/python -m tests.e2e_reinicio     # derruba e sobe o servidor no meio da execução
```

Resultado aqui: 28/28 critérios do `e2e_servidor` com 15% de falhas ligadas (503/504/409 tratados, nenhum registro
duplicado), reinício do servidor OK, e o cenário de treino inteiro (60 e-mails, relógio acelerado) sem exceções.
Esses testes validam o encanamento; a qualidade das classificações depende do modelo configurado no `.env`.

## Estrutura

```
src/
  main.py            sobe o time e o canal humano (python rodar.py)
  config.py          variáveis de ambiente (.env)
  mcp_client/        cliente MCP resiliente + matriz de permissões
  llm/               cliente da IA (API compatível com OpenAI), JSON validado com uma correção
  contratos/         envelope e esquemas das mensagens (Pydantic), rotas permitidas entre agentes
  barramento/        fila em memória, trava por caso, isolamento de falhas, espelho no painel
  memoria/           SQLite: casos, eventos vistos, ações feitas, escalações, aprovações, lições
  agentes/           despachante, triador, pesquisador, revisor, executor, operador_tela, escalador, prompts
  canal_humano/      app web (Starlette) das pessoas
tests/               unitários, e2e com o servidor, reinício, LLM simulado
logs/                log JSONL por execução, relatórios finais e capturas da tela de férias (fora do Git)
dados/               banco SQLite (fora do Git)
```

## Limitações conhecidas e o que faríamos com mais tempo

- Duas mensagens iguais que chegam juntas enquanto a primeira ainda espera informação viram dois casos (só a
  partir do registro no servidor o segundo é vinculado). Com mais tempo: deduplicar também casos em aberto.
- Nenhum gestor responde pelo servidor: a pessoa no canal humano faz o papel de aprovador.
- O resumo das escalações e a redação das mensagens dependem do modelo; o código troca por um texto pronto quando
  a redação traz número que não está nos fatos ou fica longa demais.
- Docker para os agentes não foi incluído (o script cria o ambiente virtual); a tela usa Playwright headless
  (`OPERADOR_HEADLESS=0` mostra o navegador, bom para a apresentação).
