"""6. OPERADOR DE TELA. Lança férias no sistema legado (/legado), que não tem API, operando a tela com
Playwright (navegador real). A IA lê os rótulos do formulário e diz qual campo recebe cada dado; o código
preenche, relê cada campo, confere com o aprovado, tira capturas de tela, envia e lê a confirmação.

Só lança depois do Revisor e do OK da pessoa. Nunca navega fora do /legado, nunca digita credenciais.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

from ..contratos import Caso, Envelope, PedidoEscalar, ResultadoFinal, ResultadoTela
from ..llm import ErroLLM
from ..util import data_do_agora, formatar_data, parse_data, sem_acento
from . import prompts
from .base import Agente

PALAVRAS = {  # reserva, se a IA não conseguir mapear os campos
    "agente": ("quem esta lancando", "agente", "lancando"),
    "email": ("e-mail", "email"),
    "inicio": ("primeiro dia", "inicio"),
    "fim": ("ultimo dia", "fim", "termino"),
    "evento": ("evento",),
}


class Mapa(BaseModel):
    mapa: dict[str, str] = Field(default_factory=dict)
    motivo: str = ""


class OperadorTela(Agente):
    nome = "operador_tela"

    async def receber(self, env: Envelope) -> None:
        if env.tipo == "LANCAR_FERIAS":
            await self._lancar(self.caso(env.caso_id), env.payload)

    # ---------- validação ----------
    def _validar(self, d: dict) -> tuple[Optional[dict], str]:
        hoje = data_do_agora(self.agora)
        ini, fim = parse_data(d.get("inicio"), hoje), parse_data(d.get("fim"), hoje)
        email = (d.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return None, "colaborador (e-mail) não informado"
        if not ini or not fim:
            return None, "datas ausentes ou inválidas"
        if fim < ini:
            return None, "último dia antes do primeiro"
        if hoje and ini < hoje:
            return None, "férias começando no passado"
        if (d.get("aprovacao") or {}).get("status") not in ("aprovada", None):
            return None, "sem OK humano"
        return {"agente": self.nome, "email": email, "inicio": formatar_data(ini), "fim": formatar_data(fim), "evento": d.get("evento") or ""}, ""

    def _dentro_do_legado(self, url: str) -> bool:
        base = urlparse(self.ctx.cfg.legado_url)
        u = urlparse(url)
        return (u.scheme, u.netloc) == (base.scheme, base.netloc) and u.path.startswith(base.path or "/legado")

    # ---------- fluxo ----------
    async def _lancar(self, caso: Caso, pedido: dict) -> None:
        if (caso.aprovacao or {}).get("status") != "aprovada" and (self.ctx.bases.tipo_ferias() or {}).get("aprovacao"):
            await self._falhou(caso, "lançamento sem OK humano registrado: não lanço", None)
            return
        dados, erro = self._validar(pedido)
        if not dados:
            await self._falhou(caso, f"dados de férias inválidos: {erro}", None)
            return
        self.anotar(caso, "tela/ferias", f"lançar férias {dados['inicio']} a {dados['fim']} para {dados['email']}")
        res: ResultadoTela | None = None
        captura = None
        for tentativa in range(1, 3):  # no máximo duas tentativas
            try:
                if self.ctx.cfg.operador_modo == "http":
                    res, captura = await self._via_http(dados)
                else:
                    res, captura = await self._via_navegador(dados, caso)
            except Exception as e:
                res = ResultadoTela(sucesso=False, motivo=f"tela se comportou de forma inesperada: {type(e).__name__}: {e}"[:300])
            self.anotar(caso, "tela/ferias", f"tentativa {tentativa}: {res.motivo}", "ok" if res.sucesso else "erro")
            if res.sucesso or "já existem" in sem_acento(res.motivo) or "passado" in sem_acento(res.motivo):
                break
        if res and res.sucesso:
            painel = await self._conferir_painel()
            await self.mcp.conversa("despachante", f"Férias lançadas pela tela para o caso {caso.caso_id}: {res.comprovante}. {painel}")
            self.salvar(caso)
            await self.enviar("despachante", "RESULTADO", caso, ResultadoFinal(
                estado="CONCLUIDO", acao="lancar_ferias", sucesso=True,
                detalhes={"comprovante": res.comprovante, "inicio": dados["inicio"], "fim": dados["fim"], "captura": captura}, motivo=res.motivo,
            ))
            return
        await self._falhou(caso, res.motivo if res else "falha desconhecida na tela", captura)

    async def _falhou(self, caso: Caso, motivo: str, captura: Optional[str]) -> None:
        self.anotar(caso, "tela/ferias", motivo, "falha")
        self.salvar(caso)
        await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(categoria="erro_repetido", motivo=f"Operador de tela: {motivo}"[:300], urgencia="alta", detalhes={"captura": captura}))

    async def _mapear(self, campos: list[dict], dados: dict, caso: Caso) -> dict[str, str]:
        mapa: dict[str, str] = {}
        try:
            m = await self.ctx.llm.json(self.nome, prompts.OPERADOR_MAPEAR, f"CAMPOS DO FORMULÁRIO: {campos}\nDADOS APROVADOS (chaves): {list(dados)}", Mapa, caso_id=caso.caso_id)
            ids = {c["id"] for c in campos}
            mapa = {k: v for k, v in m.mapa.items() if k in ids and v in dados}
        except ErroLLM:
            pass
        if set(mapa.values()) >= {"agente", "email", "inicio", "fim"}:
            return mapa
        mapa = {}
        for c in campos:  # reserva determinística pelos rótulos
            rot = sem_acento(c["rotulo"])
            for chave, palavras in PALAVRAS.items():
                if chave not in mapa.values() and any(p in rot for p in palavras):
                    mapa[c["id"]] = chave
                    break
        return mapa

    async def _via_navegador(self, dados: dict, caso: Caso) -> tuple[ResultadoTela, Optional[str]]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.ctx.log.registrar(self.nome, "tela", "aviso", motivo="Playwright não instalado: usando o modo http (pip install playwright && playwright install chromium)")
            return await self._via_http(dados)
        pasta = self.ctx.cfg.logs_dir / "telas"
        pasta.mkdir(parents=True, exist_ok=True)
        carimbo = f"{caso.caso_id}-{datetime.now():%H%M%S}"
        async with async_playwright() as pw:
            nav = await pw.chromium.launch(headless=self.ctx.cfg.operador_headless)
            try:
                pagina = await nav.new_page()
                pagina.set_default_timeout(15000)
                await pagina.goto(self.ctx.cfg.legado_url)
                link = pagina.get_by_role("link", name=re.compile("f[ée]rias", re.I)).first
                destino = urljoin(pagina.url, await link.get_attribute("href") or "")
                if not self._dentro_do_legado(destino):
                    return ResultadoTela(sucesso=False, motivo=f"link fora do /legado ({destino}): parei"), None
                await link.click()
                await pagina.wait_for_load_state()
                if not self._dentro_do_legado(pagina.url):
                    return ResultadoTela(sucesso=False, motivo="a tela saiu do /legado: parei"), None
                # idempotência: o lançamento já está na tabela?
                for linha in await pagina.locator("table tr").all_inner_texts():
                    if dados["email"] in linha.lower() and dados["inicio"] in linha and dados["fim"] in linha:
                        prot = re.search(r"FER-\d+", linha)
                        return ResultadoTela(sucesso=True, comprovante=prot.group(0) if prot else "já lançado", motivo="já estava lançado na tela: não lancei de novo"), None
                campos = await pagina.eval_on_selector_all("form label", "ls => ls.map(l => ({id: l.htmlFor, rotulo: l.innerText}))")
                mapa = await self._mapear(campos, dados, caso)
                for campo_id, chave in mapa.items():
                    await pagina.fill(f"#{campo_id}", dados[chave])
                for campo_id, chave in mapa.items():  # relê cada campo e confere com o aprovado
                    lido = await pagina.input_value(f"#{campo_id}")
                    if lido != dados[chave]:
                        return ResultadoTela(sucesso=False, motivo=f"campo {campo_id} ficou '{lido}', diferente do aprovado: parei"), None
                antes = str(pasta / f"{carimbo}-antes.png")
                await pagina.screenshot(path=antes, full_page=True)
                await pagina.locator("form button[type=submit]").click()
                await pagina.wait_for_load_state()
                depois = str(pasta / f"{carimbo}-depois.png")
                await pagina.screenshot(path=depois, full_page=True)
                ok = await pagina.locator(".ok").all_inner_texts()
                erro = await pagina.locator(".erro").all_inner_texts()
            finally:
                await nav.close()
        return self._interpretar(ok, erro), depois

    async def _via_http(self, dados: dict) -> tuple[ResultadoTela, Optional[str]]:
        """Reserva sem navegador: lê o HTML do formulário e envia como um navegador enviaria."""
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            indice = await http.get(self.ctx.cfg.legado_url)
            m = re.search(r"href='([^']*f[ée]rias[^']*)'", indice.text, re.I)
            url = urljoin(self.ctx.cfg.legado_url + "/", m.group(1)) if m else self.ctx.cfg.legado_url + "/ferias"
            if not self._dentro_do_legado(url):
                return ResultadoTela(sucesso=False, motivo="link fora do /legado: parei"), None
            pagina = (await http.get(url)).text
            for linha in re.findall(r"<tr>(.*?)</tr>", pagina, re.S):
                txt = html.unescape(re.sub(r"<[^>]+>", " ", linha))
                if dados["email"] in txt.lower() and dados["inicio"] in txt and dados["fim"] in txt:
                    prot = re.search(r"FER-\d+", txt)
                    return ResultadoTela(sucesso=True, comprovante=prot.group(0) if prot else "já lançado", motivo="já estava lançado: não lancei de novo"), None
            campos = [{"id": i, "rotulo": html.unescape(r)} for i, r in re.findall(r"<label for='([^']+)'>(.*?)</label>", pagina)]
            mapa = {}
            for c in campos:
                rot = sem_acento(c["rotulo"])
                for chave, palavras in PALAVRAS.items():
                    if chave not in mapa.values() and any(p in rot for p in palavras):
                        mapa[c["id"]] = chave
                        break
            acao = re.search(r"<form[^>]*action='([^']+)'", pagina)
            alvo = urljoin(url, acao.group(1)) if acao else url
            if not self._dentro_do_legado(alvo):
                return ResultadoTela(sucesso=False, motivo="formulário fora do /legado: parei"), None
            resp = await http.post(alvo, data={cid: dados[ch] for cid, ch in mapa.items()})
            ok = [html.unescape(x) for x in re.findall(r"<div class='ok'>(.*?)</div>", resp.text, re.S)]
            erro = [html.unescape(x) for x in re.findall(r"<div class='erro'>(.*?)</div>", resp.text, re.S)]
        return self._interpretar(ok, erro), None

    @staticmethod
    def _interpretar(ok: list[str], erro: list[str]) -> ResultadoTela:
        if ok:
            prot = re.search(r"FER-\d+", " ".join(ok))
            return ResultadoTela(sucesso=bool(prot), comprovante=prot.group(0) if prot else None, motivo=ok[0].strip()[:200])
        return ResultadoTela(sucesso=False, motivo=(erro[0].strip() if erro else "a tela não mostrou confirmação")[:200])

    async def _conferir_painel(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                estado = (await http.get(f"{self.ctx.cfg.servidor_url}/api/estado")).json()
            vistos = [h for h in estado.get("historico", []) if h.get("ferramenta") == "tela/ferias" and h.get("agente") == self.nome]
            return "Conferido no painel: aparece com operador_tela." if vistos else "Ainda não apareceu no painel."
        except Exception:
            return ""
