# 🚀 Como Iniciar o Servidor MCP

## Pré-requisito

O servidor MCP deve estar rodando para que a aplicação funcione.

## Opção 1: Com Docker (Recomendado)

Abra um terminal **na pasta do servidor MCP** (não nesta pasta) e execute:

```bash
TEMA=triagem docker compose up --build mundo
```

Você deve ver algo como:

```
Creating mundo ... done
Attaching to mundo
mundo | 2026-11-14 12:30:00 - INFO - Servidor MCP iniciado em http://localhost:8765/mcp
mundo | 2026-11-14 12:30:00 - INFO - Cenário: triagem
mundo | 2026-11-14 12:30:00 - INFO - Aguardando conexões...
```

## Opção 2: Sem Docker (Python direto)

Abra um terminal **na pasta do servidor MCP** e execute:

```bash
python mundo.py --tema triagem
```

## Verificar se está rodando

Abra outro terminal **nesta pasta** e execute:

```bash
python demo.py
```

Se o servidor estiver rodando, você verá:

```
================================================================================
  DEMO - Triagem N1 de Chamados e Incidentes
================================================================================

[1] BUSCANDO FAQ (Respostas Prontas)
--------------------------------------------------------------------------------

OK - Encontradas 15 respostas prontas:

   [1] faq_001
       Pergunta: Como resetar senha?
       Resposta: Clique em 'Esqueci minha senha' na tela de login...

   [2] faq_002
       ...
```

## Troubleshooting

### Erro: "Connection refused"

```
2026-11-14 12:36:16,965 - ERROR - Erro de conexao: Connection refused
   Verifique se o servidor MCP esta rodando em http://localhost:8765/mcp
```

**Solução:**
1. Verifique se o servidor MCP está rodando em outro terminal
2. Verifique se a URL está correta: `http://localhost:8765/mcp`
3. Tente reiniciar o servidor

### Erro: "404 Not Found"

```
2026-11-14 12:36:16,965 - ERROR - Erro: 404 Client Error: Not Found for url: http://localhost:8765/mcp/faq
```

**Solução:**
1. O servidor está rodando, mas os endpoints não estão disponíveis
2. Verifique se o servidor foi iniciado com `TEMA=triagem`
3. Tente reiniciar o servidor

### Porta 8765 já está em uso

```
ERROR: Port 8765 is already in use
```

**Solução:**
1. Verifique se há outro servidor rodando: `netstat -ano | findstr :8765` (Windows)
2. Mate o processo: `taskkill /PID <PID> /F`
3. Ou use outra porta: `docker compose up -p 8766:8765`

## Próximos Passos

Quando o servidor estiver rodando:

1. **Testar a conexão:**
   ```bash
   python demo.py
   ```

2. **Executar o classificador (quando implementado):**
   ```bash
   python run.py
   ```

3. **Ver logs:**
   ```bash
   tail -f logs/app.log
   ```

## Informações do Servidor

- **URL:** http://localhost:8765/mcp
- **Tema:** triagem
- **Cenário:** ~60 eventos ao longo de 5 dias
- **Duração:** 20 minutos (1 dia de expediente = 4 minutos)

## Endpoints Disponíveis

- `GET /faq` - Respostas prontas
- `GET /catalogo` - Tipos de chamado
- `GET /times` - Equipes da empresa
- `GET /eventos` - E-mails/pedidos
- `GET /chamados` - Tickets abertos
- `GET /incidentes` - Incidentes críticos
- `POST /chamados` - Criar chamado
- `POST /incidentes` - Criar incidente
- `PUT /eventos/{id}` - Atualizar evento
- `POST /eventos/{id}/responder` - Responder evento

## Documentação

Para mais informações sobre o servidor MCP, veja a documentação oficial no repositório do servidor.
