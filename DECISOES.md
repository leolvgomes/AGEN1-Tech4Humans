# Decisões tomadas diante de ambiguidade

Regra geral: na dúvida, o lado seguro (escalar, classificar para cima, não repetir uma ação).

## Escolhas do Anexo A.1

| Decisão | Escolha | Por quê |
| --- | --- | --- |
| Linguagem | Python 3.11+ | Mesma do servidor; asyncio para casos em paralelo |
| Framework de agentes | Orquestração própria | Controle total da matriz de permissões, idempotência e falhas |
| Modelo de IA | Qualquer API compatível com OpenAI, configurada no `.env` | O modelo do evento é entregue no dia |
| Barramento | Fila asyncio em memória, mensagens persistidas no SQLite | Simples, auditável, uma trava por caso |
| Persistência | SQLite (`dados/triagem.db`) | Sobrevive à queda do processo; o canal humano lê o mesmo banco |
| Canal humano | Web app (Starlette) no mesmo processo | Decisão vira mensagem no barramento sem integração extra |
| Automação de tela | Playwright (modo `http` como reserva, sem navegador) | Seletores estáveis + capturas de tela para conferência |

## O que foi descoberto no servidor (A.2) e como o código usa

- Ferramentas e parâmetros vêm do `tools/list`; o cliente valida cada chamada contra o esquema antes de enviar.
- As bases são identificadas pela **estrutura** retornada por `listar_bases` (ex.: a base com `pergunta`/`resposta` é
  o FAQ; a que aceita registro com `criticidade` é a de incidentes), não por nomes fixos.
- Chamados e incidentes ficam em bases separadas; incidente aceita só P0/P1/P2.
- Férias não podem ser registradas como chamado (o servidor recusa): só pela tela `/legado/ferias`.
- Não há plantonista na base `times`: o "plantonista" é o time responsável pelo produto (pela coluna `atende`).

## Diferenças em relação ao BPMN / especificação

1. **Duplicado antes de abrir incidente.** O BPMN vai direto de "Incidente?" para "propor abrir incidente". Aqui o
   Pesquisador também procura um incidente aberto para o mesmo produto/sintoma antes: o segundo relato da mesma
   queda é vinculado ao incidente existente, em vez de abrir outro (e escalar duas vezes).
2. **Tipo que exige aprovação.** "Registrar a proposta e esperar o OK": o chamado é registrado no servidor com status
   `aguardando aprovação` (como os chamados já existentes no kit) e o solicitante é avisado; após o OK humano o
   Executor muda para `aberto` e grava quem aprovou; na recusa, `cancelado`. Assim o evento tem atendimento
   imediato (sem cobrança) e nada é executado sem a pessoa. Férias: nada é lançado antes do OK.
3. **Escalação de segurança/dado sensível também avisa o time no mundo.** Além do pacote no canal humano, o
   Escalador manda o pacote (mascarado) ao time de Segurança (ou ao responsável) com `enviar_mensagem` e
   `evento_id`. Nunca há resposta ao solicitante. Isso torna a escalação visível no painel e conta como atendimento.
4. **Mensagens extras no barramento:** `COBRANCA` (Despachante → Escalador: nova mensagem num caso em andamento) e
   `CONFIRMAR_FERIAS` (Despachante → Executor, depois do resultado da tela), que a especificação descreve em texto
   mas não lista na tabela de tipos.
5. **Respostas FAQ sem IA na redação.** O Executor monta saudação + texto literal do item + assinatura, por código,
   para garantir "zero respostas com informação fora do FAQ". As demais mensagens são redigidas pela IA com os fatos;
   se surgir número que não está nos fatos, usa-se o texto pronto.
6. **Detecção de dado sensível também por código** (CPF, cartão, dados bancários com contexto, CID, RG): se o modelo
   não marcar, o código marca e escala. "Conta 31877" de um cliente sem contexto bancário não conta.
7. **Pedido de informação tem limite** (`MAX_PEDIDOS_INFO=2`): depois disso o caso é encaminhado ao time do tipo,
   em vez de perguntar indefinidamente.
8. **Servidor reiniciado = rodada nova.** Ids de evento se repetem (PED-001 de novo), então toda a idempotência é
   por rodada; casos da rodada anterior viram `ERRO` e não podem mais agir (`RodadaObsoleta`).
9. **Resposta a caso já fechado** abre um caso novo com o contexto do anterior (o Pesquisador tende a vinculá-lo ao
   registro já criado). Correspondência ambígua sempre vira caso novo.
10. **Mensagem nova juntada a um caso** (por exemplo um "Fwd:" do mesmo pedido enquanto ele espera informação)
    recebe um retorno próprio, para que nenhum e-mail fique sem ação.

11. **Objeção do Revisor só vale com prova.** Na execução de 14/11 com `gpt-4o-mini` (60 casos) o Revisor fez 155
    devoluções e 4 aprovações, e 51 casos foram escalados por revisão esgotada: o modelo repetia os problemas de
    exemplo do prompt. Agora o checklist objetivo é só código, a IA responde a uma pergunta por ação e uma objeção só
    devolve a proposta se a prova confere (trecho literal do e-mail, tipo/time que existe nas bases, campo com valor
    sem apoio no e-mail). Objeção sem prova fica no histórico do caso como `objecao_sem_prova`. Troca assumida: uma
    objeção correta, mas sem prova, é ignorada. Segurança e criticidade não dependem dessa prova.
12. **Falha de uma pessoa não vira P1/P2.** Só rebaixa quando o próprio modelo diz que afeta uma pessoa (ou ninguém) e
    o texto não tem sinal coletivo ("clientes", "todos", "fora do ar"...). P0 nunca é rebaixado.
13. **P2 já em andamento num chamado aberto** pode ser vinculado a ele; P0/P1 nunca.
14. **Lição de correção só quando deu certo** (devolvida e depois aprovada diferente), por categoria fixa. Antes, o
    texto do modelo virava lição na hora, realimentava o erro e chegou a guardar o nome de uma pessoa.
15. **O Pesquisador não repropõe** o item de FAQ ou o registro que o Revisor já recusou no mesmo caso.

Os itens 11 a 15 foram validados com testes de regressão (`tests/test_revisor.py`) e com a IA simulada; ainda não
rodaram com um modelo real.

## Regras do hackathon

- R2: nenhum prompt, regra ou memória contém resposta por evento. As heurísticas por palavra-chave existem apenas em
  `tests/llm_simulado.py`, usado só pelos testes automatizados (o sistema real exige a chave da IA).
- R4: a chave fica no `.env` (no `.gitignore`); `.env.example` vai sem valores.
