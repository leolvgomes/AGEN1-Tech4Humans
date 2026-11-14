# Hackathon Tech4Hum - Triagem N1 de Chamados e Incidentes

Sistema de agentes de IA para automatizar o primeiro atendimento de pedidos internos, classificando e-mails por urgência/importância, respondendo com FAQ, abrindo chamados apropriados e escalando incidentes críticos.

## 📋 Visão Geral

Este projeto implementa um sistema multi-agente que:

1. **Recebe e-mails** da caixa de entrada via servidor MCP
2. **Classifica** por criticidade (P0-P4) baseado em impacto
3. **Responde** com FAQ quando apropriado
4. **Abre chamados** com tipos e campos obrigatórios corretos
5. **Escala incidentes** críticos (P0/P1) imediatamente
6. **Detecta** casos de segurança e dados pessoais
7. **Revisa** ações antes de executar (quando necessário)

## 🏗️ Arquitetura

```
hackathon-tech4hum/
├── src/
│   ├── agents/              # Agentes de IA
│   │   └── classifier_agent.py
│   ├── models/              # Modelos de dados
│   │   ├── email.py
│   │   └── ticket.py
│   ├── services/            # Serviços (MCP Client, etc)
│   │   └── mcp_client.py
│   ├── config/              # Configurações
│   │   └── settings.py
│   └── utils/               # Utilitários
│       └── logger.py
├── tests/                   # Testes
├── data/                    # Dados (e-mails, processados)
├── logs/                    # Logs da aplicação
├── main.py                  # Ponto de entrada
├── requirements.txt         # Dependências Python
├── .env.example             # Exemplo de variáveis de ambiente
└── .gitignore              # Arquivos ignorados pelo git
```

## 🚀 Começando

### Pré-requisitos

- Python 3.9+
- pip ou conda
- Chave de API OpenAI

### Instalação

1. **Clone o repositório**
   ```bash
   git clone <repo-url>
   cd hackathon-tech4hum
   ```

2. **Crie um ambiente virtual**
   ```bash
   python -m venv venv
   source venv/bin/activate  # No Windows: venv\Scripts\activate
   ```

3. **Instale as dependências**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure as variáveis de ambiente**
   ```bash
   cp .env.example .env
   # Edite .env e adicione sua chave de API OpenAI
   ```

5. **Execute a aplicação**
   ```bash
   python main.py
   ```

## 📊 Níveis de Criticidade

| Nível | Quando | Ação |
|-------|--------|------|
| **P0** | Produto fora do ar para TODOS os clientes | Abrir incidente e escalar na hora |
| **P1** | Função importante fora para MUITOS clientes | Abrir incidente e escalar na hora |
| **P2** | Falha parcial com contorno | Abrir incidente |
| **P3** | Falha para uma pessoa, dúvida ou melhoria | Chamado de Suporte ou resposta |
| **P4** | Dúvida ou melhoria | Resposta ou FAQ |

## ⚠️ Erros Graves a Evitar

- ❌ Deixar passar um incidente P0 ou P1, ou classificá-lo abaixo
- ❌ Agir sozinho num caso de segurança ou de dado pessoal
- ❌ Responder com informação que não está no FAQ

## 📈 Níveis de Entrega

### Mínimo ✓
- [x] Pelo menos dois agentes com papéis diferentes
- [x] Processam todos os e-mails
- [x] Decidem uma ação para cada um com motivo

### Bom
- [ ] Respondem com FAQ
- [ ] Juntam duplicados
- [ ] Pedem informações faltantes
- [ ] Acertam a criticidade
- [ ] Um agente revisa o trabalho dos outros

### Excelente
- [ ] Tela de abertura de chamado integrada
- [ ] Painel do que está esperando uma pessoa

## 🔧 Configuração

### Variáveis de Ambiente

Veja `.env.example` para todas as variáveis disponíveis:

```env
# LLM
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo

# MCP Server
MCP_SERVER_URL=http://localhost:8000
MCP_SERVER_TIMEOUT=30

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
```

## 🧪 Testes

```bash
# Executar todos os testes
pytest

# Com cobertura
pytest --cov=src

# Teste específico
pytest tests/test_classifier.py
```

## 📝 Estrutura de Dados

### Email
```python
{
    "id": "email_001",
    "sender": "user@company.com",
    "subject": "Sistema fora do ar",
    "body": "O sistema de vendas está fora do ar...",
    "criticality": "P0",
    "category": "Incidente",
    "has_security_concern": False,
    "has_pii": False
}
```

### Classificação
```python
{
    "email_id": "email_001",
    "criticality": "P0",
    "category": "Incidente",
    "action": "open_incident",
    "action_reason": "Produto fora do ar para todos os clientes",
    "requires_human_review": True,
    "confidence_score": 0.95
}
```

## 🔐 Segurança

- ✅ `.env` não é commitado (veja `.gitignore`)
- ✅ Chaves de API em variáveis de ambiente
- ✅ Detecção de dados pessoais sensíveis
- ✅ Escalação automática de casos de segurança
- ✅ Logs sem informações sensíveis

## 📚 Documentação

- [Modelos de Dados](src/models/README.md)
- [Agentes](src/agents/README.md)
- [Serviços](src/services/README.md)

## 🤝 Contribuindo

1. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
2. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
3. Push para a branch (`git push origin feature/AmazingFeature`)
4. Abra um Pull Request

## 📄 Licença

Este projeto é parte do Hackathon UNIFEI 2026.

## 👥 Autores

- Tech4Hum Team

## 📞 Suporte

Para dúvidas ou problemas, abra uma issue no repositório.