"""7. ESCALADOR (ponte com pessoas). Código para as filas e o canal humano; IA só para resumir em até 3 linhas,
com dados sensíveis mascarados. Nunca aprova, nunca decide, nunca trata silêncio como aprovação."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from ..contratos import Caso, DecisaoHumana, Envelope, Escalacao, PedidoAprovacao, PedidoEscalar, ResultadoFinal
from ..llm import ErroLLM
from ..mcp_client import CenarioEncerrado, ErroMCP, RodadaObsoleta
from ..memoria import agora_iso
from ..util import mascarar, mascarar_obj
from . import prompts
from .base import Agente

ASSINATURA = "Atendimento N1 - T4H"


class Resumo(BaseModel):
    resumo: str
    recomendacao_do_time: str = ""


class Escalador(Agente):
    nome = "escalador"

    async def receber(self, env: Envelope) -> None:
        caso = self.caso(env.caso_id)
        try:
            if env.tipo == "ESCALAR":
                await self._escalar(caso, PedidoEscalar.model_validate(env.payload), env.de)
            elif env.tipo == "PEDIR_APROVACAO":
                await self._pedir_aprovacao(caso, env.payload)
            elif env.tipo == "DECISAO_HUMANA":
                await self._decisao(caso, DecisaoHumana.model_validate(env.payload))
            elif env.tipo == "COBRANCA":
                await self._cobranca(caso, env.payload.get("evento_id"))
        except (CenarioEncerrado, RodadaObsoleta) as e:
            self.anotar(caso, "escalador", f"sem novas ações: {e}", "encerrado")
        except ErroMCP as e:
            # Canal com o mundo falhou: a escalação já está salva no canal humano (nunca é descartada).
            self.anotar(caso, "escalador", f"erro {e.codigo} ao avisar no mundo: {e.mensagem}; escalação mantida no canal humano", f"erro_{e.codigo}")
            self.salvar(caso)

    # ---------- escalação ----------
    def _time_destino(self, caso: Caso, pedido: PedidoEscalar) -> Optional[dict]:
        b = self.ctx.bases
        t = caso.triagem or {}
        if pedido.categoria == "seguranca":
            return b.time_por_atende("golpe") or b.time_por_atende("vazamento") or b.time("Segurança")
        if pedido.categoria in ("incidente_p0", "incidente_p1"):
            d = pedido.detalhes
            return b.time(d.get("time")) or ({"time": d.get("time"), "email": d.get("email")} if d.get("email") else None)
        if pedido.categoria == "dado_sensivel":
            return b.time(t.get("time_responsavel")) or b.time_por_atende("golpe")
        return b.time(t.get("time_responsavel")) or b.time_por_atende("nao se encaixam")

    async def _resumir(self, caso: Caso, pedido: PedidoEscalar) -> Resumo:
        base = f"{pedido.categoria.replace('_', ' ')}: {(caso.triagem or {}).get('resumo') or caso.assunto}. Motivo: {pedido.motivo}"
        try:
            r = await self.ctx.llm.json(
                self.nome, prompts.ESCALADOR_RESUMIR,
                f"Categoria: {pedido.categoria}\nMotivo da escalação: {pedido.motivo}\nDetalhes: {pedido.detalhes}\n"
                f"Classificação: {caso.triagem}\nEvento: {caso.evento_id}\n\nCASO:\n{mascarar(caso.texto_completo())}",
                Resumo, caso_id=caso.caso_id,
            )
            return Resumo(resumo=mascarar(r.resumo)[:400], recomendacao_do_time=mascarar(r.recomendacao_do_time)[:300])
        except ErroLLM:
            return Resumo(resumo=mascarar(base)[:400], recomendacao_do_time="Avaliar o caso e decidir o próximo passo.")

    async def _escalar(self, caso: Caso, pedido: PedidoEscalar, de: str) -> None:
        rodada = self.ctx.rodada
        existentes = self.ctx.banco.q("SELECT id FROM escalacoes WHERE rodada=? AND caso_id=? AND categoria=?", (rodada, caso.caso_id, pedido.categoria))
        urgencia = "imediata" if pedido.categoria in ("incidente_p0", "incidente_p1") else ("alta" if pedido.categoria in ("seguranca", "dado_sensivel") else pedido.urgencia)
        resumo = await self._resumir(caso, pedido)
        feito = [f"{h['agente']}: {h['acao']} - {h['motivo']}" for h in caso.historico[-8:]]
        esc = Escalacao(
            escalacao_id=existentes[0]["id"] if existentes else f"e-{caso.caso_id[2:]}-{len(self.ctx.banco.q('SELECT id FROM escalacoes WHERE caso_id=?', (caso.caso_id,))) + 1}",
            caso_id=caso.caso_id, evento_id=caso.evento_id, categoria=pedido.categoria, urgencia=urgencia,
            resumo=resumo.resumo, o_que_ja_foi_feito=[mascarar(f)[:200] for f in feito], recomendacao_do_time=resumo.recomendacao_do_time,
        )
        dados = mascarar_obj({**esc.model_dump(), "remetente": caso.remetente, "assunto": caso.assunto, "detalhes": pedido.detalhes, "pedido_por": de, "motivo": pedido.motivo})
        if existentes:
            self.ctx.banco.x("UPDATE escalacoes SET dados=?, urgencia=?, atualizado_em=? WHERE id=?", (json.dumps(dados, ensure_ascii=False, default=str), urgencia, agora_iso(), esc.escalacao_id))
        else:
            self.ctx.banco.x(
                "INSERT INTO escalacoes (id, rodada, caso_id, evento_id, categoria, urgencia, dados, status, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (esc.escalacao_id, rodada, caso.caso_id, caso.evento_id, esc.categoria, urgencia, json.dumps(dados, ensure_ascii=False, default=str), "pendente", agora_iso(), agora_iso()),
            )
        caso.escalacao = esc.model_dump()
        caso.estado = "ESCALADO"
        self.anotar(caso, "escalar", f"{esc.categoria} ({urgencia}) no canal humano: {esc.resumo}"[:300])
        self.salvar(caso)
        await self.mcp.conversa("canal_humano", f"[{urgencia.upper()}] Escalação {esc.escalacao_id} ({esc.categoria}) do caso {caso.caso_id}, evento {caso.evento_id}: {esc.resumo}")

        # Avisar a pessoa/time responsável no mundo, com o evento_id (é o que conta como atendimento do evento).
        # Segurança e dado sensível: NADA vai para o solicitante.
        time = self._time_destino(caso, pedido)
        if time and time.get("email"):
            prefixo = {"incidente_p0": "[PLANTÃO P0]", "incidente_p1": "[PLANTÃO P1]", "seguranca": "[SEGURANÇA]", "dado_sensivel": "[DADO SENSÍVEL]"}.get(esc.categoria, "[ESCALAÇÃO N1]")
            corpo = (
                f"{prefixo} Escalação {esc.escalacao_id} - urgência {urgencia}.\nEvento: {caso.evento_id} | Solicitante: {caso.remetente}\n"
                f"Resumo: {esc.resumo}\nMotivo: {mascarar(pedido.motivo)}\nO que o time já fez:\n" + "\n".join(f"- {f}" for f in esc.o_que_ja_foi_feito[-5:])
                + f"\nRecomendação (apenas sugestão): {esc.recomendacao_do_time}\nDados sensíveis mascarados; consulte o evento original."
            )
            if pedido.categoria in ("incidente_p0", "incidente_p1") and pedido.detalhes.get("incidente_id"):
                corpo = f"Incidente {pedido.detalhes['incidente_id']} ({pedido.detalhes.get('produto') or '-'}) aberto agora.\n" + corpo
            await self._mensagem_time(caso, f"escalar_{esc.categoria}_{len(caso.complementos)}",time["email"], f"{prefixo} {mascarar(caso.assunto)}"[:280], corpo[:1990], f"escalar {esc.categoria} a {time.get('time')} com o pacote de contexto")
        await self.enviar("despachante", "RESULTADO", caso, ResultadoFinal(
            estado="ESCALADO", acao=f"escalar_{esc.categoria}", detalhes={"escalacao_id": esc.escalacao_id, "time": (time or {}).get("time")}, motivo=pedido.motivo[:300],
        ))

    # ---------- aprovação ----------
    async def _pedir_aprovacao(self, caso: Caso, payload: dict) -> None:
        rodada = self.ctx.rodada
        if self.ctx.banco.q("SELECT 1 FROM aprovacoes WHERE rodada=? AND caso_id=? AND status='pendente'", (rodada, caso.caso_id)):
            return  # já pedida
        ap = PedidoAprovacao(
            aprovacao_id=f"a-{caso.caso_id[2:]}-{len(self.ctx.banco.q('SELECT id FROM aprovacoes WHERE caso_id=?', (caso.caso_id,))) + 1}",
            caso_id=caso.caso_id, acao=payload["acao"], justificativa=payload.get("justificativa", ""),
        )
        dados = mascarar_obj({**ap.model_dump(), "evento_id": caso.evento_id, "remetente": caso.remetente, "assunto": caso.assunto,
                              "aprovador_catalogo": payload.get("aprovador_catalogo"), "resumo": (caso.triagem or {}).get("resumo")})
        self.ctx.banco.x(
            "INSERT INTO aprovacoes (id, rodada, caso_id, dados, status, urgencia, criado_em) VALUES (?,?,?,?,?,?,?)",
            (ap.aprovacao_id, rodada, caso.caso_id, json.dumps(dados, ensure_ascii=False, default=str), "pendente", "normal", agora_iso()),
        )
        caso.aprovacao = {**(caso.aprovacao or {}), "aprovacao_id": ap.aprovacao_id, "status": "pendente"}
        caso.estado = "AGUARDANDO_APROVACAO"
        self.anotar(caso, "pedir_aprovacao", f"{ap.aprovacao_id}: {ap.acao.get('tipo')} aguarda OK de uma pessoa ({payload.get('aprovador_catalogo')})")
        self.salvar(caso)
        await self.mcp.conversa("canal_humano", f"Pedido de aprovação {ap.aprovacao_id} (caso {caso.caso_id}): {ap.acao.get('tipo')}. {mascarar(ap.justificativa)}"[:600])

    def decidir(self, aprovacao_id: str, decisao: str, pessoa: str, comentario: str = "") -> Optional[Envelope]:
        """Chamado pelo canal humano. Grava quem decidiu e quando; a decisão vira DECISAO_HUMANA no barramento."""
        linhas = self.ctx.banco.q("SELECT * FROM aprovacoes WHERE id=?", (aprovacao_id,))
        if not linhas or linhas[0]["status"] != "pendente":
            return None
        quando = datetime.now().isoformat(timespec="seconds")
        status = "aprovada" if decisao == "aprovar" else "recusada"
        self.ctx.banco.x("UPDATE aprovacoes SET status=?, decidido_por=?, decidido_em=?, comentario=? WHERE id=?", (status, pessoa, quando, comentario, aprovacao_id))
        return Envelope(de="canal_humano", para="escalador", tipo="DECISAO_HUMANA", caso_id=linhas[0]["caso_id"], ts=self.agora,
                        payload=DecisaoHumana(aprovacao_id=aprovacao_id, decisao=status, decidido_por=pessoa, decidido_em=quando, comentario=comentario or None).model_dump())

    async def _decisao(self, caso: Caso, d: DecisaoHumana) -> None:
        self.anotar(caso, "decisao_humana", f"{d.aprovacao_id} {d.decisao} por {d.decidido_por} em {d.decidido_em}. {d.comentario or ''}"[:300])
        await self.mcp.conversa("executor", f"Decisão humana: {d.aprovacao_id} {d.decisao.upper()} por {d.decidido_por}. {mascarar(d.comentario or '')}", de="canal_humano")
        if d.decisao == "recusada":
            modelo = (f"Olá! Seu pedido ({caso.assunto}) não foi aprovado"
                      + (f" pelo responsável. Comentário: {mascarar(d.comentario)}" if d.comentario else " pelo responsável.")
                      + f"\nSe precisar, responda este e-mail com mais detalhes.\n{ASSINATURA}")
            await self._responder(caso, "responder_recusa", modelo, f"informar a recusa decidida por {d.decidido_por}")
        self.salvar(caso)
        await self.enviar("executor", "DECISAO_HUMANA", caso, d)

    async def lembretes(self) -> None:
        """Sem resposta da pessoa: relembra e sobe a urgência. Nunca assume aprovação por silêncio."""
        while True:
            await asyncio.sleep(10)
            try:
                for a in self.ctx.banco.q("SELECT * FROM aprovacoes WHERE status='pendente' AND rodada=?", (self.ctx.rodada,)):
                    idade = (datetime.now() - datetime.fromisoformat(a["criado_em"])).total_seconds()
                    nivel = int(idade // max(self.ctx.cfg.lembrete_aprovacao_s, 10))
                    if nivel > (a["lembretes"] or 0):
                        urg = "alta" if nivel == 1 else "imediata"
                        self.ctx.banco.x("UPDATE aprovacoes SET lembretes=?, urgencia=? WHERE id=?", (nivel, urg, a["id"]))
                        self.ctx.log.registrar(self.nome, "lembrete_aprovacao", motivo=f"{a['id']} sem decisão há {idade:.0f}s: urgência {urg} (silêncio não é aprovação)", caso_id=a["caso_id"])
                        await self.mcp.conversa("canal_humano", f"Lembrete: aprovação {a['id']} (caso {a['caso_id']}) espera uma pessoa há {idade:.0f}s. Urgência agora: {urg}.")
            except Exception as e:
                self.ctx.log.registrar(self.nome, "lembrete_aprovacao", "erro", motivo=str(e))

    # ---------- cobranças e mensagens novas sobre casos em andamento ----------
    async def _cobranca(self, caso: Caso, evento_id: str) -> None:
        esc = caso.escalacao or {}
        if caso.estado == "ESCALADO" and esc.get("categoria") in ("seguranca", "dado_sensivel"):
            # informação nova num caso de segurança: vai para a pessoa, nunca resposta automática ao solicitante
            ultimo = caso.complementos[-1] if caso.complementos else {}
            await self._escalar(caso, PedidoEscalar(categoria=esc["categoria"], motivo=f"nova mensagem do solicitante ({evento_id}) no caso escalado: {mascarar(ultimo.get('corpo', ''))[:200]}", urgencia="imediata"), "despachante")
            return
        if caso.estado == "AGUARDANDO_APROVACAO":
            ap_id = (caso.aprovacao or {}).get("aprovacao_id")
            if ap_id:
                self.ctx.banco.x("UPDATE aprovacoes SET urgencia='imediata' WHERE id=? AND status='pendente'", (ap_id,))
            ref = (caso.aprovacao or {}).get("chamado_id")
            texto = (f"Olá! Seu pedido{f' ({ref})' if ref else ''} continua aguardando a aprovação de: "
                     f"{(caso.aprovacao or {}).get('aprovador_catalogo') or 'responsável'}. Já reforçamos o pedido de decisão.\n{ASSINATURA}")
        else:
            texto = f"Olá! Recebemos sua mensagem e seu pedido está em andamento com o atendimento N1. Retornaremos assim que houver novidade.\n{ASSINATURA}"
        n = sum(1 for h in caso.historico if h["acao"] == "responder_evento" and "cobrança" in h["motivo"])
        await self._responder(caso, f"cobranca_{evento_id}_{n}", texto, f"responder cobrança ({evento_id}) com o status do caso ({caso.estado})")
        self.salvar(caso)
