# Prompts dos agentes

Estes arquivos são a fonte versionada de instruções do time multiagente:

- `ORQUESTRADOR.md`: controla fluxo, estado, tentativas e delegação;
- `TRIADOR.md`: interpreta o evento e propõe uma decisão estruturada;
- `REVISOR.md`: valida criticidade, segurança, fontes e regras;
- `EXECUTOR.md`: transforma uma decisão aprovada em chamadas MCP;
- `ESCALACAO_HUMANA.md`: prepara decisões que somente uma pessoa pode tomar.

Os prompts não contêm chaves, respostas específicas do cenário de treino nem
dados pessoais. O código deve carregá-los em tempo de execução; não os copie para
strings espalhadas pelo projeto.

