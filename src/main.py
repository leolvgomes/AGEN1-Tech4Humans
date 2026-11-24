"""Sobe o time de agentes da Triagem N1 e o canal humano. Uso: python -m src.main  (ou: python rodar.py)

Opções:
  --verificar      testa a conexão com o servidor MCP e com a IA e sai
  --sem-canal      não sobe o canal humano (não recomendado: as aprovações dependem dele)
  --sair-ao-fim    encerra o processo quando o cenário acabar (padrão: mantém o canal humano aberto)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .agentes import Contexto, Despachante, Escalador, Executor, OperadorTela, Pesquisador, Revisor, Triador
from .barramento import Barramento
from .config import Config
from .contratos import Envelope, PedidoEscalar
from .llm import LLM, ClienteLLM
from .log import Log
from .mcp_client import ClienteMCP
from .memoria import Banco, MemoriaCurta, MemoriaLonga
from .util import mascarar


def resumo_envelope(env: Envelope) -> str:
    p = env.payload
    if env.tipo == "PROPOSTA":
        return f"Proposta {p.get('proposta_id')}: {p.get('acao')} {p.get('criticidade') or ''} — {p.get('motivo')}"
    if env.tipo == "REVISAO":
        txt = f"Revisão {p.get('proposta_id')}: {str(p.get('decisao')).upper()}"
        return txt + (f" — problemas: {'; '.join(p.get('problemas') or [])}" if p.get("problemas") else f" — {p.get('motivo')}")
    if env.tipo == "EXECUTAR":
        return f"Executar {p.get('proposta', {}).get('acao')} aprovado pelo Revisor ({p.get('proposta', {}).get('proposta_id')})"
    if env.tipo == "ESCALAR":
        return f"Escalar ({p.get('categoria')}, {p.get('urgencia')}): {p.get('motivo')}"
    if env.tipo == "PEDIR_APROVACAO":
        return f"Pedir OK humano para {p.get('acao', {}).get('tipo')}: {p.get('justificativa')}"
    if env.tipo == "DECISAO_HUMANA":
        return f"Decisão humana {p.get('aprovacao_id')}: {p.get('decisao')} por {p.get('decidido_por')}"
    if env.tipo == "LANCAR_FERIAS":
        return f"Lançar férias de {p.get('inicio')} a {p.get('fim')} na tela /legado (aprovado)"
    if env.tipo == "PEDIR_INFO":
        return f"Pedir ao solicitante: {', '.join(p.get('campos_faltantes') or []) or 'esclarecimento'}"
    return env.tipo


def montar(cfg: Config, llm: LLM | None = None, console: bool = True) -> Contexto:
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    log = Log(cfg.logs_dir, console=console)
    banco = Banco(cfg.dados_dir / "triagem.db")
    mcp = ClienteMCP(cfg.mcp_url, cfg.mcp_timeout_s, log)
    ctx_ref: dict[str, Contexto] = {}
    bus = Barramento(banco, log, lambda: ctx_ref["ctx"].rodada)
    ctx = Contexto(cfg=cfg, log=log, banco=banco, curta=MemoriaCurta(banco), longa=MemoriaLonga(banco), mcp=mcp, llm=llm or ClienteLLM(cfg, log), bus=bus)
    ctx_ref["ctx"] = ctx
    for cls in (Despachante, Triador, Pesquisador, Revisor, Executor, OperadorTela, Escalador):
        agente = cls(ctx)
        ctx.agentes[agente.nome] = agente
        bus.registrar(agente.nome, agente.receber)

    async def espelho(env: Envelope) -> None:
        autor = env.de if env.de != "canal_humano" else "escalador"
        await ctx.ferramentas(autor).conversa(env.para, f"[{env.caso_id}] {resumo_envelope(env)}"[:1500], de=env.de)

    async def ao_falhar(env: Envelope, erro: Exception) -> None:
        """Falha de um agente não derruba o time: o caso vai para ERRO e para o Escalador."""
        caso = ctx.curta.obter(env.caso_id)
        if not caso or caso.estado in ("ESCALADO", "CONCLUIDO"):
            return
        caso.estado = "ERRO"
        caso.anotar(env.para, "excecao", f"{type(erro).__name__}: {erro}"[:300])
        ctx.curta.salvar(caso)
        if env.para != "escalador" and not ctx.encerrado:
            await bus.enviar(Envelope(de="despachante", para="escalador", tipo="ESCALAR", caso_id=caso.caso_id, ts=mcp.ultimo_agora,
                                      payload=PedidoEscalar(categoria="erro_repetido", motivo=mascarar(f"falha do {env.para} em {env.tipo}: {erro}")[:300], urgencia="alta").model_dump()))

    bus.espelho = espelho
    bus.ao_falhar = ao_falhar
    return ctx


async def rodar(ctx: Contexto, sem_canal: bool = False, sair_ao_fim: bool = False) -> dict[str, Any]:
    cfg = ctx.cfg
    servidor_canal = None
    tarefas: list[asyncio.Task] = []
    if not sem_canal:
        import uvicorn

        from .canal_humano import criar_app

        servidor_canal = uvicorn.Server(uvicorn.Config(criar_app(ctx), host=cfg.canal_humano_host, port=cfg.canal_humano_port, log_level="warning"))
        tarefas.append(asyncio.create_task(servidor_canal.serve()))
        print(f"\n  Canal humano: http://{cfg.canal_humano_host}:{cfg.canal_humano_port}\n  Painel do servidor: {cfg.servidor_url}\n", file=sys.stderr)

    despachante: Despachante = ctx.agentes["despachante"]
    await despachante.iniciar()
    ctx.bus.iniciar(cfg.max_casos_paralelos)
    tarefas.append(asyncio.create_task(ctx.agentes["escalador"].lembretes()))
    await despachante.laco()
    await ctx.bus.esperar_ocioso(90)
    rel = despachante.relatorio()
    print("\n===== RELATÓRIO FINAL =====\n" + json.dumps(rel, ensure_ascii=False, indent=2), file=sys.stderr)
    if servidor_canal and not sair_ao_fim:
        print("\n  Cenário encerrado. O canal humano continua aberto para consulta (Ctrl+C para sair).", file=sys.stderr)
        await tarefas[0]
    if servidor_canal:
        servidor_canal.should_exit = True
        await asyncio.wait([tarefas[0]], timeout=5)
    for t in tarefas[1:]:
        t.cancel()
    await ctx.bus.parar()
    await ctx.mcp.fechar()
    return rel


async def verificar(ctx: Contexto) -> int:
    ok = True
    try:
        await ctx.mcp.conectar()
        print(f"MCP ok: {len(ctx.mcp.ferramentas)} ferramentas em {ctx.cfg.mcp_url}: {sorted(ctx.mcp.ferramentas)}")
    except Exception as e:
        print(f"MCP falhou: {e}")
        ok = False
    try:
        print(f"IA ok ({ctx.cfg.llm_model}): {(await ctx.llm.testar())[:60]!r}")  # type: ignore[attr-defined]
    except Exception as e:
        print(f"IA falhou: {e}")
        ok = False
    try:
        import playwright  # noqa: F401

        print("Playwright instalado (Operador de tela usa o navegador).")
    except ImportError:
        print("Playwright não instalado: o Operador de tela vai usar o modo http. Rode: pip install playwright && playwright install chromium")
    await ctx.mcp.fechar()
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Time de agentes da Triagem N1 (Hackathon UNIFEI 2026)")
    parser.add_argument("--verificar", action="store_true")
    parser.add_argument("--sem-canal", action="store_true")
    parser.add_argument("--sair-ao-fim", action="store_true")
    args = parser.parse_args()
    cfg = Config.carregar()
    faltam = cfg.problemas_llm()
    if faltam:
        print(f"\n  Configure a IA antes de rodar: preencha {', '.join(faltam)} no arquivo .env (copie de .env.example).\n", file=sys.stderr)
        raise SystemExit(2)
    if sys.platform == "win32":
        try:
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    ctx = montar(cfg)
    try:
        if args.verificar:
            raise SystemExit(asyncio.run(verificar(ctx)))
        asyncio.run(rodar(ctx, sem_canal=args.sem_canal, sair_ao_fim=args.sair_ao_fim))
    except KeyboardInterrupt:
        print("\n  Encerrado pelo usuário. A memória curta está salva: rodar de novo retoma os casos.", file=sys.stderr)


if __name__ == "__main__":
    main()
