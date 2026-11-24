"""Contexto compartilhado, cache das bases (descobertas em tempo de execução) e a classe base dos agentes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel

from ..barramento import Barramento
from ..config import Config
from ..contratos import Caso, Envelope
from ..llm import LLM
from ..log import Log
from ..mcp_client import ClienteMCP, FerramentasAgente
from ..memoria import Banco, MemoriaCurta, MemoriaLonga
from ..util import sem_acento


class Bases:
    """Descobre as bases com listar_bases pela ESTRUTURA (campos), sem presumir nomes, e mantém cache paginado."""

    def __init__(self) -> None:
        self.meta: dict[str, dict] = {}
        self.papeis: dict[str, str] = {}
        self.faq: list[dict] = []
        self.catalogo: list[dict] = []
        self.times: list[dict] = []
        self.chamados: list[dict] = []
        self.incidentes: list[dict] = []
        self.carregado = False
        self._trava = asyncio.Lock()

    def _identificar(self, bases: list[dict]) -> None:
        self.meta = {b["base"]: b for b in bases}
        papeis: dict[str, str] = {}
        for b in bases:
            campos = set(b.get("campos") or [])
            registrar = set((b.get("campos_para_registrar") or {}).keys())
            if {"acoes", "responde_a"} <= campos:
                papeis["eventos"] = b["base"]
            elif {"para", "mensagem"} <= campos and not b.get("pode_registrar"):
                papeis["mensagens"] = b["base"]
            elif {"pergunta", "resposta"} <= campos:
                papeis["faq"] = b["base"]
            elif "campos_obrigatorios" in campos:
                papeis["catalogo"] = b["base"]
            elif {"email", "atende"} <= campos:
                papeis["times"] = b["base"]
            elif b.get("pode_registrar") and "criticidade" in registrar:
                papeis["incidentes"] = b["base"]
            elif b.get("pode_registrar") and "tipo" in registrar:
                papeis["chamados"] = b["base"]
        faltam = {"eventos", "faq", "catalogo", "times", "chamados", "incidentes"} - set(papeis)
        if faltam:
            raise RuntimeError(f"não encontrei as bases {sorted(faltam)} em listar_bases")
        self.papeis = papeis

    def nome(self, papel: str) -> str:
        return self.papeis[papel]

    def chave(self, papel: str) -> str:
        return self.meta.get(self.papeis.get(papel, ""), {}).get("chave", "id")

    async def listar(self, ferr: FerramentasAgente, papel: str, filtro: dict | None = None, busca: str | None = None, maximo: int = 500, motivo: str = "") -> list[dict]:
        """Consulta paginada (limite/offset) até tem_mais=false ou até o máximo razoável."""
        saida: list[dict] = []
        offset = 0
        while len(saida) < maximo:
            r = await ferr.chamar("consultar", motivo or f"carregar a base {papel}", base=self.nome(papel), filtro=filtro or None, busca=busca or None, limite=100, offset=offset)
            regs = r.get("registros") or []
            saida += regs
            if not r.get("tem_mais") or not regs:
                break
            offset += len(regs)
        return saida

    async def descobrir_e_carregar(self, ferr: FerramentasAgente) -> None:
        async with self._trava:
            r = await ferr.chamar("listar_bases", "descobrir bases e campos do tema")
            self._identificar(r.get("bases") or [])
            self.faq = await self.listar(ferr, "faq")
            self.catalogo = await self.listar(ferr, "catalogo")
            self.times = await self.listar(ferr, "times")
            self.chamados = await self.listar(ferr, "chamados")
            self.incidentes = await self.listar(ferr, "incidentes")
            if not self.catalogo:
                raise RuntimeError("catálogo vazio: não dá para classificar às cegas")
            self.carregado = True

    async def recarregar_registros(self, ferr: FerramentasAgente) -> None:
        self.chamados = await self.listar(ferr, "chamados", motivo="recarregar chamados abertos")
        self.incidentes = await self.listar(ferr, "incidentes", motivo="recarregar incidentes")

    def tipo(self, nome: Any) -> Optional[dict]:
        alvo = sem_acento(nome).strip()
        for c in self.catalogo:
            if sem_acento(c.get("tipo")) == alvo:
                return c
        return None

    def tipo_ferias(self) -> Optional[dict]:
        for c in self.catalogo:
            if "ferias" in sem_acento(c.get("tipo")):
                return c
        return None

    def time(self, nome: Any) -> Optional[dict]:
        alvo = sem_acento(nome).strip()
        for t in self.times:
            if sem_acento(t.get("time")) == alvo:
                return t
        return None

    def time_por_atende(self, termo: str) -> Optional[dict]:
        for t in self.times:
            if sem_acento(termo) in sem_acento(t.get("atende")):
                return t
        return None

    def faq_item(self, faq_id: Any) -> Optional[dict]:
        for f in self.faq:
            if str(f.get("id")).strip().upper() == str(faq_id).strip().upper():
                return f
        return None

    def texto_catalogo(self) -> str:
        linhas = []
        for c in self.catalogo:
            linhas.append(
                f"- {c['tipo']}: time {c.get('time')}; campos obrigatórios {c.get('campos_obrigatorios')}; "
                f"aprovação: {c.get('aprovacao') or 'não exige'}; prazo {c.get('prazo_dias_uteis') or 'conforme criticidade'} dias úteis. {c.get('descricao', '')}"
            )
        return "\n".join(linhas)

    def texto_times(self) -> str:
        return "\n".join(f"- {t['time']}: {t.get('atende')}" for t in self.times)


@dataclass
class Contexto:
    cfg: Config
    log: Log
    banco: Banco
    curta: MemoriaCurta
    longa: MemoriaLonga
    mcp: ClienteMCP
    llm: LLM
    bus: Barramento
    bases: Bases = field(default_factory=Bases)
    rodada: int = 0
    encerrado: bool = False
    agentes: dict[str, Any] = field(default_factory=dict)

    def ferramentas(self, agente: str) -> FerramentasAgente:
        return FerramentasAgente(self.mcp, agente, lambda: self.rodada)


class Agente:
    nome = ""

    def __init__(self, ctx: Contexto) -> None:
        self.ctx = ctx
        self.mcp = ctx.ferramentas(self.nome)

    # ---------- apoio ----------
    @property
    def agora(self) -> str:
        return self.ctx.mcp.ultimo_agora

    def caso(self, caso_id: str) -> Caso:
        caso = self.ctx.curta.obter(caso_id)
        if caso is None:
            raise RuntimeError(f"caso {caso_id} não está na memória curta")
        return caso

    def salvar(self, caso: Caso) -> None:
        self.ctx.curta.salvar(caso)

    def anotar(self, caso: Caso, acao: str, motivo: str, resultado: str = "ok", **extra: Any) -> None:
        caso.anotar(self.nome, acao, motivo, self.agora)
        self.ctx.log.registrar(self.nome, acao, resultado, motivo=motivo, caso_id=caso.caso_id, evento_id=caso.evento_id, **extra)

    async def enviar(self, para: str, tipo: str, caso: Caso, payload: dict | BaseModel | None = None) -> None:
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        env = Envelope(de=self.nome, para=para, tipo=tipo, caso_id=caso.caso_id, ts=self.agora, payload=payload or {})
        await self.ctx.bus.enviar(env)

    # ---------- idempotência ----------
    async def _acao(self, caso: Caso, etapa: str, ferramenta: str, motivo: str, verificar: Optional[Callable[[], Awaitable[Optional[dict]]]] = None, **args) -> dict:
        chave = f"{caso.evento_id}:{etapa}"
        feito = self.ctx.curta.acao_feita(caso.rodada, chave)
        if feito is not None:
            self.anotar(caso, f"{ferramenta}/ja_feito", f"{etapa} já executado antes: não repito")
            return feito
        r = await self.mcp.chamar(ferramenta, motivo, verificar=verificar, rodada=caso.rodada, caso_id=caso.caso_id, **args)
        self.ctx.curta.registrar_acao(caso.rodada, chave, r)
        self.anotar(caso, ferramenta, motivo, "verificado" if r.get("verificado") else "ok")
        return r

    async def _contar_acoes(self, evento_id: str, ferramenta: str) -> int:
        regs = await self.ctx.bases.listar(self.mcp, "eventos", filtro={"id": evento_id}, motivo="contar ações do evento (idempotência)")
        ev = next((r for r in regs if r.get("id") == evento_id), {})
        return sum(1 for a in ev.get("acoes") or [] if a.get("ferramenta") == ferramenta)

    async def _responder(self, caso: Caso, etapa: str, mensagem: str, motivo: str, aguardar: bool = False, evento_id: str | None = None) -> dict:
        eid = evento_id or caso.evento_id
        if self.ctx.curta.acao_feita(caso.rodada, f"{eid}:{etapa}") is None:
            antes = await self._contar_acoes(eid, "responder_evento")
        else:
            antes = 0

        async def ja_foi_feito() -> Optional[dict]:
            return {} if await self._contar_acoes(eid, "responder_evento") > antes else None

        return await self._acao(caso, etapa, "responder_evento", motivo, verificar=ja_foi_feito, evento_id=eid, mensagem=mensagem, aguardar_resposta=aguardar)

    async def _mensagem_time(self, caso: Caso, etapa: str, email: str, assunto: str, mensagem: str, motivo: str) -> dict:
        eid = caso.evento_id

        async def ja_foi_feito() -> Optional[dict]:
            regs = await self.ctx.bases.listar(self.mcp, "mensagens", filtro={"evento_id": eid, "para": email}, motivo="504: conferir se a mensagem já foi enviada")
            meus = [m for m in regs if m.get("evento_id") == eid and m.get("agente") == self.nome and m.get("assunto") == assunto]
            return {"mensagem_id": meus[-1]["id"]} if meus else None

        return await self._acao(caso, etapa, "enviar_mensagem", motivo, verificar=ja_foi_feito, para=email, assunto=assunto, mensagem=mensagem, evento_id=eid)

    async def receber(self, env: Envelope) -> None:  # pragma: no cover - cada agente implementa
        raise NotImplementedError
