"""1. DESPACHANTE (orquestrador). Código determinístico, sem IA.

Dono do laço proximo_evento: trata falhas, guarda a memória curta (casos) e a longa (padrões), entrega cada caso
ao agente certo, controla as devoluções do Revisor e fecha o atendimento. Não toma decisão de negócio.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime
from typing import Any

from ..contratos import ESTADOS_FINAIS, Caso, Envelope, PedidoEscalar, ResultadoFinal, Revisao
from ..mcp_client import CenarioEncerrado, ErroMCP
from ..util import PRIORIDADE, eh_resposta, momento_do_agora, normalizar_assunto, sem_acento, tokens
from .base import Agente

URGENCIA = ("urgente", "urgentissimo", "critico", "asap", "imediato", "emergencia", "socorro")


class Despachante(Agente):
    nome = "despachante"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.inicio = datetime.now()
        self._ultima_varredura = 0.0

    # ---------- inicialização ----------
    async def iniciar(self) -> None:
        await self.ctx.mcp.conectar()
        await self.ctx.bases.descobrir_e_carregar(self.mcp)
        await self._definir_rodada()
        self.ctx.mcp.on_reconectar.append(self._ao_reconectar)
        self.ctx.log.registrar(
            self.nome, "iniciar", motivo=f"rodada {self.ctx.rodada}; bases {self.ctx.bases.papeis}; "
            f"{len(self.ctx.bases.faq)} FAQ, {len(self.ctx.bases.catalogo)} tipos, {len(self.ctx.bases.times)} times, "
            f"{len(self.ctx.bases.chamados)} chamados; {len(self.ctx.longa.ativas())} lições ativas na memória longa",
        )
        await self._retomar_casos()

    async def _definir_rodada(self) -> None:
        """Mesmo servidor de antes (processo do time reiniciou) ou servidor novo (relógio zerado)?"""
        agora = self.ctx.mcp.ultimo_agora
        ultima = self.ctx.banco.rodada_atual()
        mesma = False
        if ultima and ultima["ultimo_agora"] and not ultima["encerrada"]:
            antes, depois = momento_do_agora(ultima["ultimo_agora"]), momento_do_agora(agora)
            if antes and depois and depois >= antes:
                vistos = self.ctx.banco.q("SELECT evento_id FROM eventos_vistos WHERE rodada=? ORDER BY visto_em DESC LIMIT 1", (ultima["id"],))
                if vistos:
                    try:
                        await self.mcp.chamar("ler_evento", "conferir se o servidor é o mesmo da última execução", evento_id=vistos[0]["evento_id"])
                        mesma = True
                    except ErroMCP:
                        mesma = False
                else:
                    mesma = True
        if mesma:
            self.ctx.rodada = ultima["id"]
        else:
            if ultima:
                for caso in self.ctx.curta.em_andamento(ultima["id"]):
                    caso.estado = "ERRO"
                    caso.anotar(self.nome, "rodada_encerrada", "servidor reiniciado: caso de uma rodada anterior")
                    self.ctx.curta.salvar(caso)
                self.ctx.banco.x("UPDATE rodadas SET encerrada=1 WHERE id=?", (ultima["id"],))
            self.ctx.rodada = self.ctx.banco.nova_rodada(agora)
        self.ctx.banco.marcar_agora(self.ctx.rodada, agora)

    async def _ao_reconectar(self) -> None:
        """Conexão caiu ou o servidor reiniciou: recarregar caches e reconciliar a memória curta."""
        anterior = self.ctx.rodada
        await self.ctx.bases.descobrir_e_carregar(self.mcp)
        await self._definir_rodada()
        if self.ctx.rodada != anterior:
            self.ctx.encerrado = False
            self.ctx.mcp.encerrado = False
            self.ctx.log.registrar(self.nome, "reconectar", motivo=f"servidor reiniciado: nova rodada {self.ctx.rodada}; casos antigos marcados como ERRO")
        else:
            self.ctx.log.registrar(self.nome, "reconectar", motivo="mesmo servidor: casos em aberto mantidos")

    async def _retomar_casos(self) -> None:
        """Queda do processo: retoma os casos pelo último estado (ações já feitas não se repetem)."""
        for caso in self.ctx.curta.em_andamento(self.ctx.rodada):
            if caso.estado in ("NOVO", "EM_TRIAGEM", "EM_REVISAO", "EXECUTANDO"):
                caso.anotar(self.nome, "retomar", "processo reiniciado: triagem de novo a partir do estado salvo")
                self.salvar(caso)
                await self.enviar("triador", "CASO_NOVO", caso, {"retomado": True})

    # ---------- laço ----------
    async def laco(self) -> None:
        while not self.ctx.encerrado:
            try:
                r = await self.mcp.chamar("proximo_evento", "pegar o próximo evento da caixa de entrada", esperar_segundos=self.ctx.cfg.espera_evento_s)
            except CenarioEncerrado:
                break
            except ErroMCP as e:
                self.ctx.log.registrar(self.nome, "proximo_evento", "erro", motivo=e.mensagem)
                await asyncio.sleep(2)
                continue
            self.ctx.banco.marcar_agora(self.ctx.rodada, self.ctx.mcp.ultimo_agora)
            if r.get("encerrado"):
                self.ctx.encerrado = True
                break
            ev = r.get("evento")
            if ev:
                await self._processar_evento(ev["id"])
            await self._varrer_perdidos()
        self.ctx.encerrado = True
        self.ctx.log.registrar(self.nome, "fim", motivo="o cenário terminou (encerrado=true)")

    async def _varrer_perdidos(self) -> None:
        """Resiliência: evento marcado 'lido' cuja resposta se perdeu (timeout do cliente) volta para a fila."""
        agora = asyncio.get_running_loop().time()
        if agora - self._ultima_varredura < 20:
            return
        self._ultima_varredura = agora
        offset = 0
        try:
            while True:
                r = await self.mcp.chamar("listar_eventos", "varrer eventos lidos que não viraram caso", status="lido", limite=200, offset=offset)
                for e in r.get("eventos") or []:
                    if not self.ctx.curta.evento_visto(self.ctx.rodada, e["id"]):
                        self.ctx.log.registrar(self.nome, "varredura", motivo="evento lido sem caso: recuperado", evento_id=e["id"])
                        await self._processar_evento(e["id"])
                if not r.get("tem_mais"):
                    break
                offset += 200
        except ErroMCP as e:
            self.ctx.log.registrar(self.nome, "varredura", "erro", motivo=e.mensagem)

    async def _processar_evento(self, evento_id: str) -> None:
        rodada = self.ctx.rodada
        if not self.ctx.curta.marcar_visto(rodada, evento_id, None):
            return  # idempotência: um evento nunca é processado duas vezes
        ev = None
        for tentativa in range(3):
            try:
                ev = (await self.mcp.chamar("ler_evento", "ler o evento para triagem", evento_id=evento_id)).get("evento")
                break
            except ErroMCP as e:
                self.ctx.log.registrar(self.nome, "ler_evento", "erro", motivo=e.mensagem, evento_id=evento_id, tentativas=tentativa + 1)
                await asyncio.sleep(2)
        if not ev:
            caso = self._novo_caso({"id": evento_id, "de": "", "assunto": "(evento ilegível)", "corpo": ""})
            self.ctx.curta.ligar_evento(rodada, evento_id, caso.caso_id)
            await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(categoria="erro_repetido", motivo="falha repetida ao ler o evento", urgencia="alta"))
            return
        existente, como = self._caso_existente(ev)
        if existente and como == "retomar":
            existente.complementos.append({"evento_id": ev["id"], "assunto": ev.get("assunto", ""), "corpo": ev.get("corpo", ""), "origem": ev.get("origem", "")})
            existente.eventos.append(ev["id"])
            existente.estado = "EM_TRIAGEM"
            self.anotar(existente, "retomar_caso", f"resposta do solicitante ({ev['id']}) anexada ao caso aguardando")
            self.salvar(existente)
            self.ctx.curta.ligar_evento(rodada, ev["id"], existente.caso_id)
            await self.enviar("triador", "CASO_NOVO", existente, {"retomado": True, "evento_novo": ev["id"]})
            return
        if existente and como == "cobranca":
            existente.eventos.append(ev["id"])
            existente.complementos.append({"evento_id": ev["id"], "assunto": ev.get("assunto", ""), "corpo": ev.get("corpo", ""), "origem": ev.get("origem", "")})
            self.anotar(existente, "cobranca", f"nova mensagem ({ev['id']}) sobre caso em andamento ({existente.estado})")
            self.salvar(existente)
            self.ctx.curta.ligar_evento(rodada, ev["id"], existente.caso_id)
            await self.enviar("escalador", "COBRANCA", existente, {"evento_id": ev["id"]})
            return
        caso = self._novo_caso(ev)
        if existente:  # conversa sobre um caso já fechado: caso novo, com o contexto do anterior
            caso.caso_anterior = existente.caso_id
            caso.contexto_anterior = self._resumo_caso(existente)
        self.salvar(caso)
        self.ctx.curta.ligar_evento(rodada, ev["id"], caso.caso_id)
        await self.enviar("triador", "CASO_NOVO", caso, {"retomado": False})

    def _novo_caso(self, ev: dict) -> Caso:
        caso = Caso(
            caso_id=self.ctx.curta.proximo_caso_id(), rodada=self.ctx.rodada, evento_id=ev["id"], eventos=[ev["id"]],
            origem={"painel": "painel", "mundo": "servidor", "cenario": "servidor"}.get(ev.get("origem", ""), "servidor"),
            remetente=ev.get("de", ""), nome=ev.get("nome", ""), assunto=ev.get("assunto", ""), corpo=ev.get("corpo", ""),
            recebido_em=ev.get("chegou_em", self.agora), estado="NOVO",
        )
        self.anotar(caso, "abrir_caso", f"caso aberto a partir de {ev['id']} ({ev.get('origem', '?')})")
        self.salvar(caso)
        return caso

    def _caso_existente(self, ev: dict) -> tuple[Caso | None, str]:
        rodada = self.ctx.rodada
        ref = ev.get("responde_a")
        if ref:
            caso = self.ctx.curta.por_evento(rodada, ref)
            if caso:
                if caso.estado == "AGUARDANDO_SOLICITANTE":
                    return caso, "retomar"
                if caso.estado not in ESTADOS_FINAIS:
                    return caso, "cobranca"
                if caso.estado == "ESCALADO" and (caso.escalacao or {}).get("categoria") in ("seguranca", "dado_sensivel"):
                    return caso, "cobranca"  # segurança: informação nova vai para a pessoa, nunca resposta automática
                return caso, "anterior"
        # Sem referência explícita: mesmo remetente + "Re:" + mesmo assunto de um caso aguardando.
        if eh_resposta(ev.get("assunto", "")):
            alvo = normalizar_assunto(ev.get("assunto", ""))
            candidatos = [c for c in self.ctx.curta.abertos_do_remetente(rodada, ev.get("de", "")) if normalizar_assunto(c.assunto) == alvo]
            if len(candidatos) == 1:
                c = candidatos[0]
                return c, "retomar" if c.estado == "AGUARDANDO_SOLICITANTE" else "cobranca"
            # ambíguo (0 ou vários): caso novo; abrir duplicado é menos grave do que misturar pedidos
        return None, ""

    @staticmethod
    def _resumo_caso(caso: Caso) -> str:
        t = caso.triagem or {}
        reg = caso.registro_criado or {}
        return (
            f"Caso anterior {caso.caso_id} ({caso.estado}): {t.get('resumo') or caso.assunto}. "
            f"Classificação {t.get('impacto')}/{t.get('tipo_caso')}/{t.get('tipo_catalogo')}. Registro: {reg.get('id', 'nenhum')}."
        )

    # ---------- mensagens recebidas ----------
    async def receber(self, env: Envelope) -> None:
        caso = self.caso(env.caso_id)
        if env.tipo == "REVISAO":
            await self._devolucao(caso, Revisao.model_validate(env.payload), env.de)
        elif env.tipo == "RESULTADO":
            await self._resultado(caso, ResultadoFinal.model_validate(env.payload), env.de)

    async def _devolucao(self, caso: Caso, rev: Revisao, de: str) -> None:
        caso.devolucoes += 1
        caso.problemas_revisor = rev.problemas
        self.anotar(caso, "devolucao", f"devolução {caso.devolucoes} ({de}): {'; '.join(rev.problemas)[:300]}")
        if caso.devolucoes > 2:
            caso.estado = "EM_REVISAO"
            self.salvar(caso)
            await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(categoria="revisao_esgotada", motivo="o Revisor devolveu a proposta 3 vezes", urgencia="alta", detalhes={"problemas": rev.problemas}))
            return
        caso.estado = "EM_TRIAGEM"
        self.salvar(caso)
        await self.enviar("triador", "CASO_NOVO", caso, {"retomado": True, "devolucao": True, "problemas": rev.problemas, "exigir_escalacao": rev.exigir_escalacao})

    async def _resultado(self, caso: Caso, res: ResultadoFinal, de: str) -> None:
        if de == "operador_tela" and res.acao == "lancar_ferias" and res.sucesso:
            caso.estado = "EXECUTANDO"
            self.salvar(caso)
            await self.enviar("executor", "CONFIRMAR_FERIAS", caso, res.detalhes)
            return
        caso.estado = res.estado
        if res.estado in ("CONCLUIDO", "ESCALADO"):
            caso.execucao = {"acao": res.acao, "sucesso": res.sucesso, **res.detalhes}
        self.anotar(caso, "fechar_caso" if res.estado in ESTADOS_FINAIS else "atualizar_caso", f"{res.acao} por {de}: {res.estado}. {res.motivo}"[:300])
        self.salvar(caso)
        if res.estado in ("CONCLUIDO", "ESCALADO"):
            self._aprender(caso)

    # ---------- memória longa ----------
    def _aprender(self, caso: Caso) -> None:
        """Grava padrões gerais (nunca resposta por evento, nunca dado sensível)."""
        t = caso.triagem or {}
        longa = self.ctx.longa
        if t.get("seguranca"):
            return
        assunto = sem_acento(caso.assunto)
        imp = t.get("impacto")
        gritos = [p for p in URGENCIA if p in assunto] or (["caixa alta e '!!!'"] if (caso.assunto.isupper() or "!!" in caso.assunto) else [])
        if gritos and PRIORIDADE.get(imp, 5) >= 3:
            longa.observar("urgencia_falsa", gritos[0], f"'{gritos[0]}' no assunto costuma vir sem impacto real: classificar pelo impacto descrito", caso.caso_id)
        if imp in ("P0", "P1"):
            for termo in self._termos(caso)[:3]:
                longa.observar("sinal_p0_p1", termo, f"o termo '{termo}' acompanhou incidentes {imp} reais: avaliar impacto com atenção", caso.caso_id)
        acao = (caso.execucao or {}).get("acao")
        if acao == "vincular_duplicado":
            longa.observar("remetente_repete", sem_acento(caso.remetente), f"{caso.remetente} costuma reenviar o mesmo pedido: procurar duplicado com atenção", caso.caso_id)
        tipo = t.get("tipo_catalogo")
        if tipo and acao in ("registrar_chamado", "lancar_ferias"):
            for termo in self._termos(caso)[:2]:
                longa.observar("mapeamento_frequente", f"{termo}->{tipo}", f"pedidos com '{termo}' costumam ser do tipo '{tipo}'", caso.caso_id)
        if caso.aprovacao and caso.aprovacao.get("status") in ("aprovada", "recusada") and tipo:
            longa.observar("padrao_aprovacao", f"{tipo}:{caso.aprovacao['status']}", f"pedidos do tipo '{tipo}' costumam ser {caso.aprovacao['status']}s", caso.caso_id)

    @staticmethod
    def _termos(caso: Caso) -> list[str]:
        return [t for t in tokens(caso.assunto, 4) if not t.isdigit()]

    # ---------- relatório final ----------
    def relatorio(self) -> dict[str, Any]:
        rodada = self.ctx.rodada
        casos = self.ctx.curta.todos(rodada, limite=5000)
        por_estado = Counter(c.estado for c in casos)
        por_acao = Counter((c.execucao or {}).get("acao", "-") for c in casos)
        acoes_agente = Counter()
        for (agente, acao), n in self.ctx.log.contagem.items():
            if acao.startswith("mcp/") or acao in ("registrar", "atualizar", "responder_evento", "enviar_mensagem", "tela/ferias"):
                acoes_agente[agente] += n
        q = self.ctx.banco.q
        rel = {
            "rodada": rodada,
            "duracao_real": str(datetime.now() - self.inicio).split(".")[0],
            "eventos_vistos": q("SELECT COUNT(*) n FROM eventos_vistos WHERE rodada=?", (rodada,))[0]["n"],
            "casos": len(casos),
            "casos_por_estado": dict(por_estado),
            "casos_por_acao": dict(por_acao),
            "acoes_executadas": q("SELECT COUNT(*) n FROM acoes WHERE rodada=?", (rodada,))[0]["n"],
            "escalacoes": q("SELECT COUNT(*) n FROM escalacoes WHERE rodada=?", (rodada,))[0]["n"],
            "aprovacoes": {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM aprovacoes WHERE rodada=? GROUP BY status", (rodada,))},
            "devolucoes_do_revisor": sum(c.devolucoes for c in casos),
            "mensagens_no_barramento": self.ctx.bus.total,
            "erros_tratados_mcp": self.ctx.mcp.estatisticas,
            "chamadas_ao_modelo": getattr(self.ctx.llm, "chamadas", None),
            "licoes_ativas": len(self.ctx.longa.ativas()),
        }
        arquivo = self.ctx.cfg.logs_dir / f"relatorio-rodada{rodada}-{datetime.now():%Y%m%d-%H%M%S}.json"
        arquivo.write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
        rel["arquivo"] = str(arquivo)
        return rel
