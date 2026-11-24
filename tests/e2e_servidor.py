"""Teste ponta a ponta (Seção 15.2) contra um servidor MCP de verdade, com o LLM SIMULADO.

Suba o servidor de teste antes (na pasta do servidor):
    python mundo.py --tema triagem --sem-cenario --porta 8799 --erros 0.15 --sem-navegador
Depois:
    python -m tests.e2e_servidor            (usa E2E_URL=http://127.0.0.1:8799)

Cria os eventos sintéticos T01..T14 pelo "+ Novo evento" (API do painel), aprova pelo canal humano o que pedir OK
e confere no servidor: todo evento com ação, P0/P1 escalados, segurança sem resposta, férias pela tela, revisão.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import sys
import tempfile

import httpx

from src.config import Config
from src.main import montar
from tests.llm_simulado import LLMSimulado

URL = os.environ.get("E2E_URL", "http://127.0.0.1:8799")

EVENTOS = {
    "T01": ("ana.silva@t4h.exemplo", "Ana Silva", "vpn", "Oi! Como me conecto à VPN para trabalhar de fora do escritório?"),
    "T02": ("bia.reis@t4h.exemplo", "Bia Reis", "patrocínio", "Qual o procedimento para patrocinar um evento externo de tecnologia?"),
    "T03": ("caio.melo@t4h.exemplo", "Caio Melo", "acesso", "Preciso de acesso de leitura para acompanhar as vendas do meu time."),
    "T05a": ("davi.luz@t4h.exemplo", "Davi Luz", "mouse com defeito", "Preciso trocar meu mouse com defeito, patrimônio 7781, o clique esquerdo falha."),
    "T06": ("eva.sol@t4h.exemplo", "Eva Sol", "URGENTE!!! app", "URGENTE!!! O App Agenda não abre no meu celular desde hoje de manhã. Só comigo."),
    "T07": ("fabio.rio@t4h.exemplo", "Fabio Rio", "Portal do Cliente fora do ar", "O Portal do Cliente está fora do ar para todos os clientes desde as 10h. Ninguém consegue entrar."),
    "T08": ("gil.mar@t4h.exemplo", "Gil Mar", "App Agenda com erro", "No App Agenda muitos clientes não conseguem confirmar agendamento, dá erro ao salvar."),
    "T09": ("hugo.paz@t4h.exemplo", "Hugo Paz", "Painel de Vendas lento", "O relatório mensal do Painel de Vendas está lento para vários usuários; dá para usar o contorno de exportar por semana."),
    "T10": ("suporte@t4h-exemplo.com", "Suporte", "[AÇÃO NECESSÁRIA] senha expira", "Sua senha expira hoje. Clique no link http://t4h-exemplo.com/senha e informe sua senha atual."),
    "T11": ("iris.lua@t4h.exemplo", "Iris Lua", "atestado", "Segue meu atestado médico, CPF 123.456.789-09, CID J11. Podem lançar no ponto?"),
    "T12": ("joao.sal@t4h.exemplo", "João Sal", "férias", "Quero tirar férias de 11/01/2027 a 22/01/2027. Obrigado!"),
    "T13": ("kia.mel@t4h.exemplo", "Kia Mel", "acesso CRM", "Preciso de acesso de leitura ao CRM para acompanhar a carteira de clientes."),
}


async def criar(http: httpx.AsyncClient, chave: str) -> str:
    de, nome, assunto, corpo = EVENTOS[chave]
    r = await http.post(f"{URL}/api/evento", json={"de": de, "nome": nome, "assunto": assunto, "corpo": corpo})
    r.raise_for_status()
    return r.json()["id"]


async def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="triagem-e2e-"))
    cfg = Config(llm_api_key="simulado", llm_model="simulado", mcp_url=f"{URL}/mcp", legado_url=f"{URL}/legado", dados_dir=tmp / "dados",
                 logs_dir=tmp / "logs", max_casos_paralelos=4, espera_evento_s=3, operador_modo=os.environ.get("E2E_OPERADOR", "playwright"),
                 canal_humano_port=8098, lembrete_aprovacao_s=30)
    ctx = montar(cfg, LLMSimulado(), console=os.environ.get("E2E_VERBOSO") == "1")
    desp = ctx.agentes["despachante"]
    await desp.iniciar()
    ctx.bus.iniciar(cfg.max_casos_paralelos)
    laco = asyncio.create_task(desp.laco())
    ids: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=10) as http:
        ctx.banco.definir_ajuste("sabotar_proximo_p1", "1")  # T14: o próximo P1 sai rebaixado do Triador
        for chave in EVENTOS:
            ids[chave] = await criar(http, chave)
        ids["T05b"] = await criar(http, "T05a")  # T05: o mesmo pedido de novo
        print("eventos criados:", ids)

        respondeu_t03 = False
        decididas: set[str] = set()
        for _ in range(120):
            await asyncio.sleep(2)
            for a in ctx.banco.q("SELECT id FROM aprovacoes WHERE status='pendente'"):
                if a["id"] not in decididas:
                    env = ctx.agentes["escalador"].decidir(a["id"], "aprovar", "Pessoa de Teste", "ok no teste e2e")
                    decididas.add(a["id"])
                    if env:
                        await ctx.bus.enviar(env)
            c3 = ctx.curta.por_evento(ctx.rodada, ids["T03"])
            if c3 and c3.estado == "AGUARDANDO_SOLICITANTE" and not respondeu_t03:  # T04: o solicitante responde com o sistema
                respondeu_t03 = True
                r = await http.post(f"{URL}/api/evento", json={"de": EVENTOS["T03"][0], "nome": EVENTOS["T03"][1], "assunto": "RE: acesso",
                                                              "corpo": "É o CRM, acesso de leitura, para acompanhar as vendas do meu time."})
                ids["T04"] = r.json()["id"]
            pendentes = [c for c in ctx.curta.em_andamento(ctx.rodada) if c.estado != "AGUARDANDO_SOLICITANTE"]
            if respondeu_t03 and not pendentes and ctx.bus.ocioso() and len(decididas) >= 2:
                break
        estado = (await http.get(f"{URL}/api/estado")).json()
    laco.cancel()
    await ctx.bus.parar()

    caixa = {e["id"]: e for e in estado["caixa"]}
    falhas: list[str] = []

    def caso_de(chave: str):
        return ctx.curta.por_evento(ctx.rodada, ids[chave])

    def checar(cond: bool, texto: str) -> None:
        print(("  OK   " if cond else "  FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    print("\nCasos:")
    for chave, eid in ids.items():
        c = caso_de(chave)
        t = (c.triagem or {}) if c else {}
        print(f"  {chave:5} {eid:8} ações={caixa.get(eid, {}).get('acoes')} estado={c.estado if c else '-'} {t.get('impacto')}/{t.get('tipo_caso')}/{t.get('tipo_catalogo')} -> {(c.execucao or {}).get('acao') if c else ''} dev={c.devolucoes if c else ''}")
    print("\nCritérios:")
    hist = estado["historico"]
    chamadas = [h for h in hist if h.get("tipo") == "chamada"]
    for chave, eid in ids.items():
        if chave != "T04":
            checar(caixa[eid]["acoes"] > 0, f"{chave}: evento {eid} recebeu ação")
    checar((caso_de("T01").execucao or {}).get("acao") == "responder_faq", "T01 respondido com o FAQ")
    checar((caso_de("T02").execucao or {}).get("acao") == "encaminhar_time", "T02 encaminhado ao time, sem resposta inventada")
    checar((caso_de("T03").execucao or {}).get("acao") == "registrar_chamado" and caso_de("T03").pedidos_info >= 1, "T03/T04 pediu o que faltava e retomou o mesmo caso")
    checar((caso_de("T05b").execucao or {}).get("acao") == "vincular_duplicado", "T05 segundo pedido vinculado ao primeiro")
    checar((caso_de("T06").triagem or {}).get("impacto") in ("P3", "P4") and (caso_de("T06").execucao or {}).get("acao") != "abrir_incidente", "T06 URGENTE de uma pessoa não virou incidente")
    checar((caso_de("T07").escalacao or {}).get("categoria") == "incidente_p0", "T07 incidente P0 aberto e escalado na hora")
    checar((caso_de("T08").escalacao or {}).get("categoria") == "incidente_p1" and caso_de("T08").devolucoes >= 1, "T08/T14 Revisor devolveu o P2 e o caso virou P1 escalado")
    checar((caso_de("T09").execucao or {}).get("acao") == "abrir_incidente" and not caso_de("T09").escalacao, "T09 incidente P2 sem escalação imediata")
    resp_t10 = [h for h in chamadas if h.get("ferramenta") == "responder_evento" and h.get("argumentos", {}).get("evento_id") == ids["T10"]]
    checar(caso_de("T10").estado == "ESCALADO" and not resp_t10, "T10 golpe só escalado, nenhuma resposta ao solicitante")
    resp_t11 = [h for h in chamadas if h.get("ferramenta") == "responder_evento" and h.get("argumentos", {}).get("evento_id") == ids["T11"]]
    painel_t11 = [h for h in hist if "123.456.789-09" in str(h.get("mensagem", "")) + str(h.get("argumentos", ""))]  # o que o time escreveu
    checar(caso_de("T11").estado == "ESCALADO" and not resp_t11 and not painel_t11, "T11 dado sensível escalado, CPF mascarado no painel")
    tela = [h for h in chamadas if h.get("ferramenta") == "tela/ferias" and h.get("agente") == "operador_tela" and h.get("resultado") == "ok"]
    checar(bool(tela) and (caso_de("T12").execucao or {}).get("acao") == "lancar_ferias", "T12 férias lançadas pela tela com o nome operador_tela, após OK humano")
    checar((caso_de("T13").aprovacao or {}).get("status") == "aprovada" and (caso_de("T13").execucao or {}).get("acao") == "registrar_chamado", "T13 só executou depois do OK humano")
    conversas = [h for h in hist if h.get("tipo") == "conversa" and "DEVOLVER" in str(h.get("mensagem", "")).upper()]
    checar(bool(conversas), "Revisor corrigindo outro agente aparece no painel (registrar_conversa)")
    acoes = ctx.banco.q("SELECT chave FROM acoes WHERE rodada=?", (ctx.rodada,))
    checar(len(acoes) == len({a["chave"] for a in acoes}), "nenhuma ação duplicada (chave evento+etapa)")
    regs = [h for h in chamadas if h.get("ferramenta") == "registrar" and h.get("resultado") == "ok"]
    por_evento: dict[str, int] = {}
    for h in regs:
        por_evento[h["argumentos"].get("evento_id")] = por_evento.get(h["argumentos"].get("evento_id"), 0) + 1
    checar(all(n == 1 for n in por_evento.values()), f"T15 nenhum registro criado duas vezes no servidor ({por_evento})")
    print(f"\nErros tratados pelo cliente MCP: {ctx.mcp.estatisticas}")
    print(f"Log local: {ctx.log.arquivo}")
    shutil.rmtree(tmp / "dados", ignore_errors=True)
    print("\nRESULTADO:", "TUDO OK" if not falhas else f"{len(falhas)} falha(s)")
    return 0 if not falhas else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(asyncio.run(main()))
