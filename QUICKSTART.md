# Quick Start - Triagem N1

## 🚀 Começando Rapidamente

### 1. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 2. Configurar Variáveis de Ambiente

Edite o arquivo `.env` e adicione sua chave de API OpenAI:

```env
OPENAI_API_KEY=sk-seu-api-key-aqui
OPENAI_MODEL=gpt-4-turbo
MCP_SERVER_URL=http://localhost:8765/mcp
```

### 3. Iniciar o Servidor MCP

Em outro terminal, na pasta do servidor MCP:

```bash
TEMA=triagem docker compose up --build mundo
```

Ou sem Docker:

```bash
python mundo.py --tema triagem
```

### 4. Testar a Conexão

```bash
python run.py --test-connection
```

Você deve ver algo como:

```
================================================================================
Testando conexão com servidor MCP
================================================================================
URL do servidor: http://localhost:8765/mcp

Testando endpoints...
--------------------------------------------------------------------------------
1. Buscando FAQ...
   ✓ FAQ carregado com sucesso (15 respostas)
2. Buscando Catálogo...
   ✓ Catálogo carregado com sucesso (8 tipos)
3. Buscando Times...
   ✓ Times carregados com sucesso (5 times)
4. Buscando Eventos...
   ✓ Eventos carregados com sucesso (10 eventos)
   Primeiros eventos:
   - evt_001: Sistema fora do ar
   - evt_002: Acesso negado
   - evt_003: Dúvida sobre produto
5. Buscando Chamados...
   ✓ Chamados carregados com sucesso (3 chamados)
6. Buscando Incidentes...
   ✓ Incidentes carregados com sucesso (1 incidentes)
--------------------------------------------------------------------------------
✓ Teste de conexão concluído com sucesso!
================================================================================
```

### 5. Executar o Classificador

```bash
python run.py
```

Ou com limite customizado:

```bash
python run.py --limit 20
```

Você deve ver algo como:

```
================================================================================
Iniciando aplicação de Triagem N1 de Chamados e Incidentes
================================================================================
Conectando ao servidor MCP...
Carregando FAQ, Catálogo e Times...
✓ FAQ: 15 respostas
✓ Catálogo: 8 tipos de chamado
✓ Times: 5 times
Inicializando agente classificador...
Buscando eventos do servidor MCP (limite: 10)...
✓ Encontrados 10 eventos

Iniciando classificação de eventos...
--------------------------------------------------------------------------------
Classificados 10/10 eventos
--------------------------------------------------------------------------------
✓ Classificação concluída: 10/10 eventos processados

RESULTADOS DA CLASSIFICAÇÃO:
================================================================================

[1] Evento: evt_001
    Criticidade: P0
    Categoria: Incidente
    Ação: abrir_incidente
    Motivo: Produto fora do ar para todos os clientes
    Confiança: 95.0%
    ⚠️  REQUER REVISÃO HUMANA

[2] Evento: evt_002
    Criticidade: P3
    Categoria: Acesso a Sistema
    Ação: abrir_chamado
    Motivo: Problema de acesso para um usuário
    Confiança: 87.0%

...

================================================================================
✓ Aplicação finalizada com sucesso
================================================================================
```

## 📊 Estrutura de Saída

Cada evento classificado mostra:

- **Evento ID**: Identificador único do evento
- **Criticidade**: P0, P1, P2, P3 ou P4
- **Categoria**: Tipo de pedido (Incidente, Suporte, Acesso, etc)
- **Ação**: O que fazer (abrir_incidente, abrir_chamado, responder_faq, etc)
- **Motivo**: Explicação da classificação
- **Confiança**: Percentual de confiança da classificação
- **Flags**: ⚠️ REQUER REVISÃO HUMANA, 🔒 Preocupações de segurança

## 🧪 Executar Testes

```bash
# Todos os testes
pytest

# Com cobertura
pytest --cov=src

# Apenas testes de modelos
pytest tests/test_models.py -v
```

## 📝 Logs

Os logs são salvos em `logs/app.log` e também exibidos no console.

Para mudar o nível de log, edite `.env`:

```env
LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## 🔧 Troubleshooting

### Erro: "Connection refused" ao conectar ao MCP

- Verifique se o servidor MCP está rodando
- Verifique a URL em `.env`: `MCP_SERVER_URL=http://localhost:8765/mcp`
- Tente: `python run.py --test-connection`

### Erro: "OPENAI_API_KEY not found"

- Verifique se o arquivo `.env` existe
- Verifique se `OPENAI_API_KEY` está preenchido com uma chave válida
- Não use aspas: `OPENAI_API_KEY=sk-...` (não `OPENAI_API_KEY="sk-..."`)

### Erro: "No module named 'langchain'"

- Reinstale as dependências: `pip install -r requirements.txt`

## 📚 Próximos Passos

1. **Implementar Agente de Revisão**: Segundo agente que revisa as classificações
2. **Implementar Agente de Ação**: Agente que abre chamados e incidentes
3. **Implementar Agente de Resposta**: Agente que responde com FAQ
4. **Criar Dashboard**: Interface web para visualizar eventos e ações
5. **Integrar com Sistema de Férias**: Operação de tela para lançamento de férias

## 📞 Suporte

Para dúvidas ou problemas, verifique:

- [README.md](README.md) - Documentação completa
- [logs/app.log](logs/app.log) - Arquivo de logs
- Código-fonte em `src/`
