"""Canal humano (Seção 12): a ÚNICA forma de uma pessoa falar com o time enquanto os agentes rodam (Regra R5).

Telas: Painel (o que espera uma pessoa), Aprovações (Aprovar/Recusar com comentário), Escalações
(Assumir/Resolvida), Histórico, Casos, Memória longa, Novo chamado (entra no mesmo time como evento)
e Perguntar ao time ("por que o chamado X foi P2?"). Lê e grava a mesma persistência dos agentes.
"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from ..agentes.base import Contexto
from ..util import mascarar

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--tx:#1d2330;--mut:#5d6678;--bd:#dfe3ea;--pri:#2f6fd1;--red:#c0392b;--amb:#b8860b;--grn:#2e7d32}
@media (prefers-color-scheme: dark){:root{--bg:#14171d;--card:#1d222b;--tx:#e8ebf1;--mut:#9aa3b5;--bd:#2d3440;--pri:#5b93e6}}
main a{color:var(--pri)}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx)}
header{background:#0f2a57;color:#fff;padding:10px 18px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header b{font-size:16px}header a{color:#cfe0ff;text-decoration:none}header a:hover{color:#fff}
main{max-width:1150px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px;margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.num{font-size:28px;font-weight:700}.mut{color:var(--mut)}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--bd);margin-right:4px}
.imediata,.P0,.P1{background:#fde2e1;color:#8b1c13;border-color:#f3b1ab}.alta{background:#fff3cd;color:#6b4e00}
.normal{background:#e3e8ff;color:#22306f}.ok{color:var(--grn)}.erro{color:var(--red)}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid var(--bd);padding:6px;text-align:left;vertical-align:top}
input,textarea,select{font:inherit;padding:6px 8px;border:1px solid var(--bd);border-radius:6px;background:var(--card);color:var(--tx);width:100%}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--pri);background:var(--pri);color:#fff;cursor:pointer}
button.sec{background:transparent;color:var(--pri)}button.red{background:var(--red);border-color:var(--red)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row>*{flex:1}
pre{white-space:pre-wrap;background:var(--bg);padding:8px;border-radius:6px;margin:6px 0}
"""

RECARREGAR = """<script>setInterval(()=>{const a=document.activeElement;if(!a||!['INPUT','TEXTAREA','SELECT'].includes(a.tagName))location.reload()},6000)</script>"""


def pagina(titulo: str, corpo: str, recarregar: bool = False) -> HTMLResponse:
    nav = "".join(f"<a href='{u}'>{n}</a>" for u, n in [
        ("/", "Painel"), ("/aprovacoes", "Aprovações"), ("/escalacoes", "Escalações"), ("/casos", "Casos"),
        ("/historico", "Histórico"), ("/memoria", "Memória longa"), ("/novo", "Novo chamado"), ("/perguntar", "Perguntar ao time"),
    ])
    return HTMLResponse(
        f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(titulo)} · Canal humano N1</title><style>{CSS}</style></head><body><header><b>Canal humano · Triagem N1</b>{nav}</header>"
        f"<main>{corpo}</main>{RECARREGAR if recarregar else ''}</body></html>"
    )


def e(v: Any) -> str:
    return escape(mascarar("" if v is None else str(v)))


def criar_app(ctx: Contexto) -> Starlette:
    banco = ctx.banco

    def pessoa(request: Request) -> str:
        return request.cookies.get("pessoa", "")

    def campo_pessoa(request: Request) -> str:
        return f"<input name='pessoa' placeholder='Seu nome (quem decide)' value='{escape(pessoa(request))}' required>"

    def json_dados(linha) -> dict:
        try:
            return json.loads(linha["dados"])
        except Exception:
            return {}

    # ---------- painel ----------
    async def painel(request: Request):
        r = ctx.rodada
        esc = banco.q("SELECT * FROM escalacoes WHERE rodada=? AND status!='resolvida' ORDER BY CASE urgencia WHEN 'imediata' THEN 0 WHEN 'alta' THEN 1 ELSE 2 END, criado_em", (r,))
        apr = banco.q("SELECT * FROM aprovacoes WHERE rodada=? AND status='pendente' ORDER BY criado_em", (r,))
        por_cat: dict[str, int] = {}
        for x in esc:
            por_cat[x["categoria"]] = por_cat.get(x["categoria"], 0) + 1
        casos = ctx.curta.todos(r, limite=2000)
        estados: dict[str, int] = {}
        for c in casos:
            estados[c.estado] = estados.get(c.estado, 0) + 1
        criticos = [x for x in esc if x["categoria"] in ("incidente_p0", "incidente_p1") and x["status"] == "pendente"]
        cards = "".join(f"<div class='card'><div class='num'>{n}</div><div class='mut'>{escape(k.replace('_', ' '))}</div></div>" for k, n in sorted(por_cat.items()))
        alerta = ""
        if criticos:
            alerta = "<div class='card' style='border-color:var(--red)'><b class='erro'>P0/P1 sem atendimento humano:</b> " + ", ".join(
                f"<a href='/escalacoes#{escape(x['id'])}'>{escape(x['id'])} ({escape(x['categoria'])})</a>" for x in criticos) + "</div>"
        sabotar = banco.ajuste("sabotar_proximo_p1") == "1"
        corpo = (
            f"<h2>O que está esperando uma pessoa</h2>{alerta}"
            f"<div class='grid'><div class='card'><div class='num'>{len(apr)}</div><div class='mut'>aprovações pendentes</div></div>"
            f"<div class='card'><div class='num'>{len(esc)}</div><div class='mut'>escalações abertas</div></div>{cards}</div>"
            f"<div class='card'><b>Time de agentes</b> · rodada {r} · agora (simulado): {escape(ctx.mcp.ultimo_agora or '-')} · "
            f"{'<span class=erro>cenário encerrado</span>' if ctx.encerrado else '<span class=ok>rodando</span>'}<br>"
            f"<span class='mut'>Casos por estado:</span> " + " ".join(f"<span class='tag'>{escape(k)}: {v}</span>" for k, v in sorted(estados.items())) + "</div>"
            f"<div class='card'><b>Demonstração T14</b> — força o Triador a rebaixar o próximo P1 para P2, para mostrar o Revisor corrigindo. "
            f"<form method='post' action='/demo/sabotar' class='row' style='margin-top:6px'><span>Estado: <b>{'armado' if sabotar else 'desligado'}</b></span>"
            f"<button class='sec'>{'Desarmar' if sabotar else 'Armar'}</button></form></div>"
        )
        return pagina("Painel", corpo, recarregar=True)

    # ---------- aprovações ----------
    async def aprovacoes(request: Request):
        linhas = banco.q("SELECT * FROM aprovacoes WHERE rodada=? AND status='pendente' ORDER BY criado_em", (ctx.rodada,))
        itens = []
        for a in linhas:
            d = json_dados(a)
            acao = d.get("acao") or {}
            itens.append(
                f"<div class='card' id='{escape(a['id'])}'><div class='row'><b>{escape(a['id'])}</b><span><span class='tag {escape(a['urgencia'] or 'normal')}'>{escape(a['urgencia'] or 'normal')}</span>"
                f"caso <a href='/casos/{escape(a['caso_id'])}'>{escape(a['caso_id'])}</a> · evento {e(d.get('evento_id'))}</span></div>"
                f"<p><b>Ação proposta:</b> {e(acao.get('tipo'))} · <b>Solicitante:</b> {e(d.get('remetente'))} · <b>Assunto:</b> {e(d.get('assunto'))}</p>"
                f"<pre>{e(json.dumps(acao.get('parametros'), ensure_ascii=False, indent=1))}</pre>"
                f"<p><b>Justificativa do time:</b> {e(d.get('justificativa'))}<br><b>Aprovação exigida pelo catálogo:</b> {e(d.get('aprovador_catalogo'))}</p>"
                f"<form method='post' action='/aprovacoes/{escape(a['id'])}'><div class='row'>{campo_pessoa(request)}<input name='comentario' placeholder='Comentário (opcional)'></div>"
                f"<div class='row' style='margin-top:8px'><button name='decisao' value='aprovar'>Aprovar</button><button class='red' name='decisao' value='recusar'>Recusar</button></div></form></div>"
            )
        corpo = "<h2>Aprovações pendentes</h2><p class='mut'>O agente nunca aprova: só a decisão registrada aqui libera a ação.</p>" + ("".join(itens) or "<div class='card mut'>Nada esperando aprovação.</div>")
        return pagina("Aprovações", corpo, recarregar=True)

    async def decidir(request: Request):
        form = await request.form()
        nome = str(form.get("pessoa", "")).strip()[:80]
        if not nome:
            return pagina("Aprovações", "<div class='card erro'>Informe seu nome para decidir.</div><a href='/aprovacoes'>Voltar</a>")
        env = ctx.agentes["escalador"].decidir(request.path_params["id"], str(form.get("decisao")), nome, str(form.get("comentario", "")).strip()[:500])
        if env:
            await ctx.bus.enviar(env)
            ctx.log.registrar("canal_humano", "decisao", motivo=f"{request.path_params['id']}: {form.get('decisao')} por {nome}", caso_id=env.caso_id)
        resp = RedirectResponse("/aprovacoes", status_code=303)
        resp.set_cookie("pessoa", nome, max_age=86400 * 7)
        return resp

    # ---------- escalações ----------
    async def escalacoes(request: Request):
        linhas = banco.q("SELECT * FROM escalacoes WHERE rodada=? AND status!='resolvida' ORDER BY CASE urgencia WHEN 'imediata' THEN 0 WHEN 'alta' THEN 1 ELSE 2 END, criado_em", (ctx.rodada,))
        itens = []
        for x in linhas:
            d = json_dados(x)
            feitos = "".join(f"<li>{e(f)}</li>" for f in d.get("o_que_ja_foi_feito", [])[-6:])
            itens.append(
                f"<div class='card' id='{escape(x['id'])}'><div class='row'><b>{escape(x['id'])} · {escape(x['categoria'].replace('_', ' '))}</b>"
                f"<span><span class='tag {escape(x['urgencia'])}'>{escape(x['urgencia'])}</span><span class='tag'>{escape(x['status'])}</span>"
                f"{('assumida por ' + e(x['assumido_por'])) if x['assumido_por'] else ''}</span></div>"
                f"<p><b>Resumo:</b> {e(d.get('resumo'))}</p><p class='mut'>Caso <a href='/casos/{escape(x['caso_id'])}'>{escape(x['caso_id'])}</a> · evento {e(x['evento_id'])} · solicitante {e(d.get('remetente'))}</p>"
                f"<p><b>Recomendação do time (só sugestão):</b> {e(d.get('recomendacao_do_time'))}</p><details><summary>O que o time já fez</summary><ul>{feitos}</ul></details>"
                f"<form method='post' action='/escalacoes/{escape(x['id'])}' class='row' style='margin-top:8px'>{campo_pessoa(request)}"
                f"<button name='acao' value='assumir' class='sec'>Assumir</button><button name='acao' value='resolver'>Resolvida</button></form></div>"
            )
        corpo = "<h2>Escalações</h2><p class='mut'>Dados pessoais sensíveis aparecem mascarados; consulte o evento original se precisar.</p>" + ("".join(itens) or "<div class='card mut'>Nenhuma escalação aberta.</div>")
        return pagina("Escalações", corpo, recarregar=True)

    async def tratar_escalacao(request: Request):
        form = await request.form()
        nome = str(form.get("pessoa", "")).strip()[:80]
        if not nome:
            return pagina("Escalações", "<div class='card erro'>Informe seu nome.</div><a href='/escalacoes'>Voltar</a>")
        status = "em_atendimento" if form.get("acao") == "assumir" else "resolvida"
        banco.x("UPDATE escalacoes SET status=?, assumido_por=?, atualizado_em=datetime('now','localtime') WHERE id=?", (status, nome, request.path_params["id"]))
        ctx.log.registrar("canal_humano", "escalacao", motivo=f"{request.path_params['id']}: {status} por {nome}")
        resp = RedirectResponse("/escalacoes", status_code=303)
        resp.set_cookie("pessoa", nome, max_age=86400 * 7)
        return resp

    # ---------- histórico ----------
    async def historico(request: Request):
        aps = banco.q("SELECT * FROM aprovacoes WHERE status!='pendente' ORDER BY decidido_em DESC LIMIT 200")
        escs = banco.q("SELECT * FROM escalacoes WHERE status!='pendente' ORDER BY atualizado_em DESC LIMIT 200")
        t1 = "".join(f"<tr><td>{escape(a['id'])}</td><td>{escape(a['caso_id'])}</td><td class='{'ok' if a['status'] == 'aprovada' else 'erro'}'>{escape(a['status'])}</td><td>{e(a['decidido_por'])}</td><td>{e(a['decidido_em'])}</td><td>{e(a['comentario'])}</td></tr>" for a in aps)
        t2 = "".join(f"<tr><td>{escape(x['id'])}</td><td>{escape(x['caso_id'])}</td><td>{escape(x['categoria'])}</td><td>{escape(x['status'])}</td><td>{e(x['assumido_por'])}</td><td>{e(x['atualizado_em'])}</td></tr>" for x in escs)
        corpo = (f"<h2>Histórico</h2><div class='card'><b>Decisões de aprovação</b><table><tr><th>Id</th><th>Caso</th><th>Decisão</th><th>Por</th><th>Quando</th><th>Comentário</th></tr>{t1 or '<tr><td colspan=6 class=mut>nenhuma</td></tr>'}</table></div>"
                 f"<div class='card'><b>Escalações tratadas</b><table><tr><th>Id</th><th>Caso</th><th>Categoria</th><th>Status</th><th>Por</th><th>Quando</th></tr>{t2 or '<tr><td colspan=6 class=mut>nenhuma</td></tr>'}</table></div>")
        return pagina("Histórico", corpo)

    # ---------- casos ----------
    async def casos(request: Request):
        linhas = []
        for c in ctx.curta.todos(ctx.rodada, limite=500):
            t = c.triagem or {}
            linhas.append(f"<tr><td><a href='/casos/{escape(c.caso_id)}'>{escape(c.caso_id)}</a></td><td>{escape(c.evento_id)}</td><td>{e(c.assunto)}</td>"
                          f"<td><span class='tag {escape(str(t.get('impacto')))}'>{escape(str(t.get('impacto') or '-'))}</span>{escape(str(t.get('tipo_caso') or ''))}</td>"
                          f"<td>{escape(c.estado)}</td><td>{escape(str((c.execucao or {}).get('acao') or ''))}</td><td>{c.devolucoes}</td></tr>")
        corpo = f"<h2>Casos da rodada {ctx.rodada}</h2><div class='card'><table><tr><th>Caso</th><th>Evento</th><th>Assunto</th><th>Triagem</th><th>Estado</th><th>Ação</th><th>Devoluções</th></tr>{''.join(linhas)}</table></div>"
        return pagina("Casos", corpo, recarregar=True)

    async def caso(request: Request):
        c = ctx.curta.obter(request.path_params["id"])
        if not c:
            return pagina("Caso", "<div class='card'>Caso não encontrado.</div>")
        hist = "".join(f"<tr><td>{e(h['ts'])}</td><td>{e(h['agente'])}</td><td>{e(h['acao'])}</td><td>{e(h['motivo'])}</td></tr>" for h in c.historico)
        corpo = (f"<h2>Caso {escape(c.caso_id)} · {escape(c.estado)}</h2><div class='card'><b>{e(c.assunto)}</b> <span class='mut'>de {e(c.remetente)} · eventos {e(', '.join(c.eventos))}</span><pre>{e(c.texto_completo())}</pre></div>"
                 f"<div class='card'><b>Triagem</b><pre>{e(json.dumps(c.triagem, ensure_ascii=False, indent=1))}</pre><b>Revisões</b><pre>{e(json.dumps(c.revisoes, ensure_ascii=False, indent=1))}</pre>"
                 f"<b>Registro</b><pre>{e(json.dumps(c.registro_criado, ensure_ascii=False))}</pre></div><div class='card'><b>Histórico</b><table>{hist}</table></div>")
        return pagina(f"Caso {c.caso_id}", corpo)

    # ---------- memória longa ----------
    async def memoria(request: Request):
        linhas = "".join(f"<tr><td>{escape(l['tipo'])}</td><td>{e(l['licao'])}</td><td>{l['vezes_confirmada']}</td><td>{l['usos']}</td><td>{'ativa' if l['vezes_confirmada'] >= 2 or l['tipo'] == 'correcao_revisor' else 'aguardando confirmação'}</td><td>{e(l['atualizado_em'])}</td></tr>" for l in ctx.longa.todas())
        corpo = f"<h2>Memória longa</h2><p class='mut'>Padrões gerais (nunca resposta por evento). Uma lição vale depois de confirmada por mais de um caso ou por correção do Revisor.</p><div class='card'><table><tr><th>Tipo</th><th>Lição</th><th>Confirmações</th><th>Usos</th><th>Estado</th><th>Atualizada</th></tr>{linhas}</table></div>"
        return pagina("Memória longa", corpo)

    # ---------- formulário interno de chamados ----------
    async def novo(request: Request):
        msg = ""
        if request.method == "POST":
            form = await request.form()
            dados = {k: str(form.get(k, "")).strip() for k in ("de", "nome", "assunto", "corpo")}
            if not dados["de"].endswith("@t4h.exemplo"):
                msg = "<div class='card erro'>Use um e-mail da empresa (@t4h.exemplo).</div>"
            elif not dados["assunto"] or not dados["corpo"]:
                msg = "<div class='card erro'>Preencha assunto e mensagem.</div>"
            else:
                try:
                    async with httpx.AsyncClient(timeout=10) as http:
                        r = await http.post(f"{ctx.cfg.servidor_url}/api/evento", json=dados)
                    if r.status_code == 200:
                        msg = f"<div class='card ok'>Pedido enviado ao time como evento <b>{escape(r.json().get('id', '?'))}</b>. O Despachante vai pegá-lo no próximo ciclo.</div>"
                        ctx.log.registrar("canal_humano", "novo_chamado", motivo=f"evento {r.json().get('id')} criado pelo formulário interno")
                    else:
                        msg = f"<div class='card erro'>O servidor recusou: {escape(r.text[:200])}</div>"
                except httpx.HTTPError as ex:
                    msg = f"<div class='card erro'>Servidor indisponível: {escape(str(ex))}</div>"
        corpo = (f"<h2>Abrir chamado</h2>{msg}<div class='card'><p class='mut'>O pedido entra no Despachante como um evento e passa pelo mesmo time de agentes.</p>"
                 "<form method='post'><div class='row'><input name='de' placeholder='seu.email@t4h.exemplo' required><input name='nome' placeholder='Seu nome'></div>"
                 "<p><input name='assunto' placeholder='Assunto' required></p><p><textarea name='corpo' rows='6' placeholder='Descreva o pedido' required></textarea></p>"
                 "<button>Enviar ao time</button></form></div>")
        return pagina("Novo chamado", corpo)

    # ---------- conversa direta ----------
    def explicar(pergunta: str) -> str:
        ids = re.findall(r"\b(c-\d{4}|CH-\d+|INC-\d+|PED-\d+(?:-R\d+)?|MAN-\d+|MSG-\d+)\b", pergunta, re.I)
        if not ids:
            return "Informe o identificador (por exemplo CH-1001, INC-01, PED-014 ou c-0007) para eu buscar o histórico do caso."
        alvo = ids[0]
        achado = None
        for c in ctx.curta.todos(None, limite=5000):
            reg = c.registro_criado or {}
            if alvo.lower() in [c.caso_id.lower(), *[x.lower() for x in c.eventos], str(reg.get("id", "")).lower()]:
                achado = c
                break
        if not achado:
            return f"Não encontrei {alvo} na memória do time."
        t = achado.triagem or {}
        revs = "; ".join(f"{r.get('decisao')} ({', '.join(r.get('problemas') or []) or r.get('motivo')})" for r in achado.revisoes) or "nenhuma"
        passos = "\n".join(f"- {h['agente']}: {h['acao']} — {h['motivo']}" for h in achado.historico[-10:])
        return mascarar(
            f"{alvo} pertence ao caso {achado.caso_id} ({achado.estado}).\n"
            f"Triador: impacto {t.get('impacto')}, tipo {t.get('tipo_caso')}, catálogo {t.get('tipo_catalogo')}. Motivo: {t.get('motivo')}\n"
            f"Segurança: {t.get('seguranca')} {t.get('motivo_seguranca') or ''}\nRevisões: {revs}\nÚltimos passos:\n{passos}"
        )

    async def perguntar(request: Request):
        resposta = ""
        if request.method == "POST":
            form = await request.form()
            q = str(form.get("pergunta", "")).strip()[:500]
            resp = explicar(q)
            banco.x("INSERT INTO perguntas (pessoa, pergunta, resposta, ts) VALUES (?,?,?,datetime('now','localtime'))", (pessoa(request), q, resp))
            resposta = f"<div class='card'><b>Escalador responde:</b><pre>{escape(resp)}</pre></div>"
        corpo = (f"<h2>Perguntar ao time</h2>{resposta}<div class='card'><form method='post'><p><input name='pergunta' placeholder='Por que o chamado CH-1001 foi classificado assim?' required></p>"
                 "<button>Perguntar</button></form></div>")
        return pagina("Perguntar", corpo)

    async def sabotar(request: Request):
        banco.definir_ajuste("sabotar_proximo_p1", "0" if banco.ajuste("sabotar_proximo_p1") == "1" else "1")
        return RedirectResponse("/", status_code=303)

    async def api_pendencias(request: Request):
        return JSONResponse({
            "rodada": ctx.rodada,
            "aprovacoes": [dict(a) for a in banco.q("SELECT id, caso_id, status, urgencia, criado_em FROM aprovacoes WHERE rodada=? AND status='pendente'", (ctx.rodada,))],
            "escalacoes": [dict(x) for x in banco.q("SELECT id, caso_id, evento_id, categoria, urgencia, status FROM escalacoes WHERE rodada=? AND status!='resolvida'", (ctx.rodada,))],
        })

    return Starlette(routes=[
        Route("/", painel),
        Route("/aprovacoes", aprovacoes),
        Route("/aprovacoes/{id}", decidir, methods=["POST"]),
        Route("/escalacoes", escalacoes),
        Route("/escalacoes/{id}", tratar_escalacao, methods=["POST"]),
        Route("/historico", historico),
        Route("/casos", casos),
        Route("/casos/{id}", caso),
        Route("/memoria", memoria),
        Route("/novo", novo, methods=["GET", "POST"]),
        Route("/perguntar", perguntar, methods=["GET", "POST"]),
        Route("/demo/sabotar", sabotar, methods=["POST"]),
        Route("/api/pendencias", api_pendencias),
    ])
