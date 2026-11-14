# 📁 Estrutura do Projeto - Triagem N1

## Visão Geral da Estrutura

```
hackathon-tech4hum/
├── .env                          # Variáveis de ambiente (GITIGNORED)
├── .env.example                  # Template de variáveis (exemplo)
├── .gitignore                    # Arquivos ignorados pelo git
├── README.md                     # Documentação principal
├── QUICKSTART.md                 # Guia rápido de início
├── ESTRUTURA.md                  # Este arquivo
├── requirements.txt              # Dependências Python
│
├── main.py                       # Ponto de entrada principal
├── run.py                        # Script com CLI (--test-connection, --limit)
├── test_connection.py            # Script para testar conexão com MCP
│
├── src/                          # Código-fonte principal
│   ├── __init__.py
│   ├── config/                   # Configurações
│   │   ├── __init__.py
│   │   └── settings.py           # Carregamento de .env e validação
│   │
│   ├── models/                   # Modelos de dados (Pydantic)
│   │   ├── __init__.py
│   │   ├── email.py              # Evento, EventoClassification, FAQ, CatalogItem, Time
│   │   └── ticket.py             # Ticket, Incident, TicketType, IncidentSeverity
│   │
│   ├── services/                 # Serviços (integração com MCP)
│   │   ├── __init__.py
│   │   └── mcp_client.py         # Cliente HTTP para servidor MCP
│   │
│   ├── agents/                   # Agentes de IA
│   │   ├── __init__.py
│   │   └── classifier_agent.py   # Agente de classificação de eventos
│   │
│   └── utils/                    # Utilitários
│       ├── __init__.py
│       └── logger.py             # Configuração de logging
│
├── tests/                        # Testes unitários
│   ├── __init__.py
│   └── test_models.py            # Testes dos modelos
│
├── data/                         # Dados (e-mails, processados)
│   └── (vazio - será preenchido em runtime)
│
└── logs/                         # Logs da aplicação
    └── app.log                   # Arquivo de log (criado em runtime)
```

## 📄 Arquivos Principais

### Configuração e Segurança

| Arquivo | Descrição |
|---------|-----------|
| `.env` | Variáveis de ambiente com chaves reais (GITIGNORED) |
| `.env.example` | Template de variáveis (exemplo para documentação) |
| `.gitignore` | Protege `.env`, `__pycache__`, logs, dados sensíveis |
| `requirements.txt` | Dependências Python (pip install -r requirements.txt) |

### Scripts Executáveis

| Arquivo | Descrição | Uso |
|---------|-----------|-----|
| `main.py` | Ponto de entrada principal | `python main.py` |
| `run.py` | CLI com opções | `python run.py --test-connection` ou `python run.py --limit 20` |
| `test_connection.py` | Testa conexão com MCP | `python test_connection.py` |

### Documentação

| Arquivo | Descrição |
|---------|-----------|
| `README.md` | Documentação completa do projeto |
| `QUICKSTART.md` | Guia rápido de início (recomendado para começar) |
| `ESTRUTURA.md` | Este arquivo - explicação da estrutura |

## 🏗️ Módulos Principais

### `src/config/settings.py`
- Carrega variáveis do `.env` usando Pydantic
- Valida tipos e valores
- Fornece função `get_settings()` para acessar configurações
- Configura logging

**Variáveis principais:**
```python
OPENAI_API_KEY          # Chave de API OpenAI
OPENAI_MODEL            # Modelo (gpt-4-turbo)
MCP_SERVER_URL          # URL do servidor MCP (http://localhost:8765/mcp)
LOG_LEVEL               # Nível de log (INFO, DEBUG, etc)
AGENT_TEMPERATURE       # Temperatura do LLM (0.3)
```

### `src/models/email.py`
Define modelos de dados para eventos:

- **`Evento`**: Representa um e-mail/evento do servidor MCP
  - `id`, `tipo`, `de`, `para`, `assunto`, `corpo`, `timestamp`, `status`, `observacao`

- **`EventoClassification`**: Resultado da classificação
  - `evento_id`, `criticality`, `category`, `action`, `action_reason`, `requires_human_review`, `security_concerns`, `confidence_score`

- **`FAQ`**: Resposta pronta
  - `id`, `pergunta`, `resposta`

- **`CatalogItem`**: Tipo de chamado
  - `tipo`, `time`, `campos_obrigatorios`, `requer_aprovacao`, `prazo_horas`

- **`Time`**: Time da empresa
  - `time`, `email`, `atende`

### `src/models/ticket.py`
Define modelos para chamados e incidentes:

- **`Ticket`**: Chamado aberto
  - `id`, `ticket_type`, `status`, `title`, `description`, `requester_email`, `assigned_team`, etc

- **`Incident`**: Incidente crítico
  - `id`, `severity`, `status`, `title`, `description`, `affected_systems`, `business_impact`, etc

### `src/services/mcp_client.py`
Cliente HTTP para comunicação com servidor MCP:

**Métodos principais:**
```python
# Eventos
fetch_eventos(limit, offset)        # Busca eventos
get_evento(evento_id)               # Busca um evento
update_evento(evento_id, status)    # Atualiza evento
responder_evento(evento_id, resposta)  # Responde evento

# Chamados
registrar_chamado(tipo, campos)     # Cria chamado
list_chamados()                     # Lista chamados
atualizar_chamado(chamado_id, ...)  # Atualiza chamado

# Incidentes
registrar_incidente(criticidade, resumo)  # Cria incidente
list_incidentes()                   # Lista incidentes
atualizar_incidente(incidente_id, ...)    # Atualiza incidente

# Dados
get_faq()                           # Busca FAQ
get_catalogo()                      # Busca catálogo
get_times()                         # Busca times
```

### `src/agents/classifier_agent.py`
Agente de classificação usando LangChain + OpenAI:

**Métodos principais:**
```python
classify_evento(evento)             # Classifica um evento
batch_classify(eventos)             # Classifica lote de eventos
```

**Retorna:**
- `EventoClassification` com criticidade (P0-P4), categoria, ação recomendada, confiança

### `src/utils/logger.py`
Configuração de logging:
- Logs em arquivo (`logs/app.log`) e console
- Rotação automática de logs (10MB)
- Níveis configuráveis via `.env`

## 🔄 Fluxo de Execução

```
1. Carregar configurações (.env)
   ↓
2. Configurar logging
   ↓
3. Conectar ao servidor MCP
   ↓
4. Carregar FAQ, Catálogo, Times
   ↓
5. Inicializar agente classificador
   ↓
6. Buscar eventos do servidor
   ↓
7. Classificar cada evento
   ↓
8. Exibir resultados
   ↓
9. (Próximo: Abrir chamados/incidentes, responder com FAQ, etc)
```

## 📊 Níveis de Criticidade

| Nível | Quando | Ação |
|-------|--------|------|
| **P0** | Produto fora do ar para TODOS | Abrir incidente + escalar |
| **P1** | Função importante fora para MUITOS | Abrir incidente + escalar |
| **P2** | Falha parcial com contorno | Abrir incidente |
| **P3** | Falha para uma pessoa | Chamado de Suporte |
| **P4** | Dúvida ou melhoria | Resposta ou FAQ |

## 🧪 Testes

```bash
# Todos os testes
pytest

# Com cobertura
pytest --cov=src

# Apenas modelos
pytest tests/test_models.py -v
```

**Status atual:** ✅ 7 testes passando

## 🔐 Segurança

✅ `.env` não é commitado (veja `.gitignore`)
✅ Chaves de API em variáveis de ambiente
✅ Detecção de dados pessoais sensíveis
✅ Escalação automática de casos de segurança
✅ Logs sem informações sensíveis

## 📈 Próximos Passos

1. **Agente de Revisão**: Segundo agente que revisa classificações
2. **Agente de Ação**: Abre chamados e incidentes no servidor
3. **Agente de Resposta**: Responde com FAQ
4. **Dashboard**: Interface web para visualizar eventos
5. **Integração com Sistema de Férias**: Operação de tela

## 📞 Como Usar

### Teste de Conexão
```bash
python run.py --test-connection
```

### Executar Classificador
```bash
python run.py                    # Processa 10 eventos (padrão)
python run.py --limit 20         # Processa 20 eventos
```

### Ver Logs
```bash
tail -f logs/app.log             # Linux/Mac
Get-Content logs/app.log -Tail 20 -Wait  # Windows PowerShell
```

## 🎯 Checklist de Implementação

- [x] Estrutura de pastas
- [x] Configurações (.env, settings.py)
- [x] Modelos de dados (Pydantic)
- [x] Cliente MCP (HTTP)
- [x] Agente classificador (LangChain + OpenAI)
- [x] Logging
- [x] Testes básicos
- [x] Scripts executáveis
- [x] Documentação
- [ ] Agente de revisão
- [ ] Agente de ação
- [ ] Agente de resposta
- [ ] Dashboard web
- [ ] Integração com sistema de férias
