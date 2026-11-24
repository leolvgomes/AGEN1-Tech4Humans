"""3. PESQUISADOR (conhecimento, só leitura). A recuperação é feita por código (consultar); a IA só julga
similaridade e cobertura. Acha duplicados, responde só com o FAQ (texto literal) e descobre o time certo."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from ..contratos import Caso, Envelope, Proposta
from ..llm import ErroLLM
from ..util import sem_acento, similaridade, tokens
from . import prompts
from .base import Agente

FECHADOS = ("resolvido", "cancelado")


class JulgamentoDuplicado(BaseModel):
    duplicado: bool = False
    registro_id: Optional[str] = None
    similaridade: float = 0.0
    motivo: str = ""

    @field_validator("similaridade", mode="before")
    @classmethod
    def _s(cls, v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0


class JulgamentoFaq(BaseModel):
    encontrou: bool = False
    faq_id: Optional[str] = None
    confianca: float = 0.0
    time_responsavel: Optional[str] = None
    motivo: str = ""

    @field_validator("confianca", mode="before")
    @classmethod
    def _c(cls, v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0


class Pesquisador(Agente):
    nome = "pesquisador"

    async def receber(self, env: Envelope) -> None:
        caso = self.caso(env.caso_id)
        if env.tipo == "PESQUISAR_DUPLICADO":
            await self._duplicado(caso, env.payload.get("modo", "chamado"))
        elif env.tipo == "PESQUISAR_FAQ":
            await self._faq(caso, env.payload.get("pergunta", ""))

    @staticmethod
    def _recusados(caso: Caso, acao: str, parametro: str) -> set[str]:
        """O que o Revisor já devolveu neste caso: não repropor a mesma coisa."""
        devolvidas = {r.get("proposta_id") for r in caso.revisoes if r.get("decisao") == "devolver" and not any("inconclusiva" in x for x in r.get("problemas") or [])}
        return {str(p["parametros"].get(parametro)) for p in caso.propostas if p["acao"] == acao and p["proposta_id"] in devolvidas}

    # ---------- duplicados ----------
    async def _esperar_casos_parecidos(self, caso: Caso) -> None:
        """Dois e-mails sobre a mesma coisa em paralelo: espera o outro terminar de agir antes de procurar,
        para não abrir dois registros iguais."""
        for _ in range(30):
            parecidos = [
                c for c in self.ctx.curta.em_andamento(self.ctx.rodada)
                if c.caso_id != caso.caso_id and c.estado in ("EM_TRIAGEM", "EM_REVISAO", "EXECUTANDO") and c.caso_id < caso.caso_id
                and (c.remetente == caso.remetente or similaridade(c.assunto + " " + c.corpo, caso.assunto + " " + caso.corpo) >= 0.5)
            ]
            if not parecidos:
                return
            await asyncio.sleep(2)

    async def _candidatos(self, caso: Caso, modo: str) -> list[dict]:
        bases = self.ctx.bases
        await self._esperar_casos_parecidos(caso)
        await bases.recarregar_registros(self.mcp)
        meus = set(caso.eventos)
        recusados = self._recusados(caso, "vincular_duplicado", "registro_id")
        texto = f"{caso.assunto} {caso.corpo} {' '.join(c.get('corpo', '') for c in caso.complementos)}"
        produto = sem_acento((caso.triagem or {}).get("produto") or "")
        candidatos: list[tuple[float, dict]] = []
        fontes = [("incidentes", bases.incidentes), ("chamados", bases.chamados)] if modo == "incidente" else [("chamados", bases.chamados), ("incidentes", bases.incidentes)]
        for papel, registros in fontes:
            for r in registros:
                if sem_acento(r.get("status", "")) in FECHADOS:
                    continue  # duplicado de chamado fechado não é duplicado: é pedido novo
                if meus & set(r.get("pedidos") or []) or str(r.get("id")) in recusados:
                    continue
                nota = similaridade(texto, f"{r.get('resumo', '')} {r.get('tipo', '')} {r.get('produto', '')} {r.get('campos', '')}")
                if sem_acento(r.get("solicitante", "")) == sem_acento(caso.remetente):
                    nota += 0.6
                if produto and produto in sem_acento(f"{r.get('produto', '')} {r.get('resumo', '')}"):
                    nota += 0.4
                if nota >= 0.25:
                    candidatos.append((nota, {"base": papel, **{k: r.get(k) for k in ("id", "tipo", "criticidade", "produto", "solicitante", "resumo", "status", "aberto_em")} }))
        candidatos.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in candidatos[:8]]

    async def _duplicado(self, caso: Caso, modo: str) -> None:
        candidatos = await self._candidatos(caso, modo)
        dica = self.ctx.longa.remetente_repete(caso.remetente)
        julg = JulgamentoDuplicado(duplicado=False, motivo="nenhum registro aberto parecido")
        if candidatos:
            usuario = "\n".join([
                "CASO NOVO:", caso.texto_completo(), "",
                f"Classificação do Triador: {(caso.triagem or {}).get('impacto')} / {(caso.triagem or {}).get('tipo_caso')} / {(caso.triagem or {}).get('tipo_catalogo')}",
                f"Memória longa: {dica['licao']}" if dica else "",
                "", "CANDIDATOS ABERTOS:", *[str(c) for c in candidatos],
            ])
            try:
                julg = await self.ctx.llm.json(self.nome, prompts.PESQUISADOR_DUPLICADO, usuario, JulgamentoDuplicado, caso_id=caso.caso_id)
            except ErroLLM as e:
                julg = JulgamentoDuplicado(duplicado=False, motivo=f"julgamento indisponível ({e}); candidatos: {[c['id'] for c in candidatos]}")
        alvo = next((c for c in candidatos if str(c["id"]) == str(julg.registro_id)), None)
        if julg.duplicado and alvo and julg.similaridade >= 0.6:
            self.anotar(caso, "duplicado", f"duplicado de {alvo['id']} ({julg.similaridade:.2f}): {julg.motivo}")
            proposta = Proposta(
                proposta_id=f"p-{caso.caso_id[2:]}-{len(caso.propostas) + 1}", caso_id=caso.caso_id, autor="pesquisador", acao="vincular_duplicado",
                parametros={"base": alvo["base"], "registro_id": alvo["id"], "registro": alvo, "avisar_solicitante": True, "similaridade": julg.similaridade},
                criticidade=alvo.get("criticidade") if alvo.get("criticidade") in ("P0", "P1", "P2") else None,
                motivo=f"mesmo problema/pedido de {alvo['id']} ainda aberto: {julg.motivo}"[:400],
            )
            caso.propostas.append(proposta.model_dump())
            caso.estado = "EM_REVISAO"
            self.salvar(caso)
            await self.enviar("revisor", "PROPOSTA", caso, proposta)
            return
        motivo = julg.motivo if candidatos else "nenhum candidato aberto parecido"
        self.anotar(caso, "duplicado", f"não é duplicado: {motivo}"[:300])
        self.salvar(caso)
        await self.mcp.conversa("triador", f"Caso {caso.caso_id}: não é duplicado ({motivo})"[:400])
        await self.enviar("triador", "RESULTADO_DUPLICADO", caso, {"duplicado": False, "motivo": motivo, "candidatos": [c["id"] for c in candidatos]})

    # ---------- FAQ ----------
    async def _faq(self, caso: Caso, pergunta: str) -> None:
        bases = self.ctx.bases
        itens = "\n".join(f"[{f['id']}] P: {f['pergunta']}\n    R: {f['resposta']}" for f in bases.faq)
        usuario = f"PERGUNTA: {pergunta}\n\nE-MAIL COMPLETO:\n{caso.texto_completo()}\n\nITENS DO FAQ:\n{itens}\n\nTIMES:\n{bases.texto_times()}"
        try:
            julg = await self.ctx.llm.json(self.nome, prompts.PESQUISADOR_FAQ, usuario, JulgamentoFaq, caso_id=caso.caso_id)
        except ErroLLM as e:
            julg = JulgamentoFaq(encontrou=False, motivo=f"FAQ indisponível ({e}): não responder, encaminhar")
        item = bases.faq_item(julg.faq_id) if julg.encontrou and julg.faq_id else None
        if item and str(item["id"]) in self._recusados(caso, "responder_faq", "faq_id"):
            item = None  # o Revisor mostrou que esse item cobre só parte: encaminhar
        n = len(caso.propostas) + 1
        if item and julg.confianca >= 0.7:
            proposta = Proposta(
                proposta_id=f"p-{caso.caso_id[2:]}-{n}", caso_id=caso.caso_id, autor="pesquisador", acao="responder_faq",
                parametros={"faq_id": item["id"], "texto_resposta": item["resposta"], "pergunta_faq": item["pergunta"]},
                motivo=f"resposta do FAQ item {item['id']}, pergunta coberta integralmente: {julg.motivo}"[:400],
            )
        else:
            time = bases.time(julg.time_responsavel) or bases.time((caso.triagem or {}).get("time_responsavel")) or bases.time_por_atende("nao se encaixam")
            if time is None:
                time = bases.times[0]
            proposta = Proposta(
                proposta_id=f"p-{caso.caso_id[2:]}-{n}", caso_id=caso.caso_id, autor="pesquisador", acao="encaminhar_time",
                parametros={"time": time["time"], "email": time["email"], "resumo": (caso.triagem or {}).get("resumo") or caso.assunto, "pergunta": pergunta},
                motivo=f"FAQ não cobre a pergunta inteira; encaminhar a {time['time']} sem inventar resposta: {julg.motivo}"[:400],
            )
        caso.propostas.append(proposta.model_dump())
        caso.estado = "EM_REVISAO"
        self.anotar(caso, "faq", proposta.motivo)
        self.salvar(caso)
        await self.enviar("revisor", "PROPOSTA", caso, proposta)
