"""2. TRIADOR (classificador). IA com saída JSON validada. Só PROPÕE, nunca age.

Ordem: segurança -> impacto real (P0 a P4) -> incidente? -> duplicado (Pesquisador) -> dúvida ou pedido ->
catálogo e campos obrigatórios -> proposta ao Revisor (ou PEDIR_INFO ao Executor).
"""

from __future__ import annotations

from typing import Any

from ..contratos import Caso, Envelope, PedidoEscalar, Proposta, Triagem, rebaixar_se_individual
from ..llm import ErroLLM
from ..util import formatar_data, parse_data, data_do_agora, tem_dado_sensivel
from . import prompts
from .base import Agente

INCIDENTE = ("P0", "P1", "P2")


class Triador(Agente):
    nome = "triador"

    async def receber(self, env: Envelope) -> None:
        caso = self.caso(env.caso_id)
        if env.tipo == "CASO_NOVO":
            await self._triar(caso, env.payload)
        elif env.tipo == "RESULTADO_DUPLICADO":
            await self._depois_do_duplicado(caso)

    # ---------- triagem ----------
    async def _triar(self, caso: Caso, info: dict) -> None:
        if not self.ctx.bases.carregado or not self.ctx.bases.catalogo:
            raise RuntimeError("catálogo não carregado: o Triador não classifica às cegas")
        caso.estado = "EM_TRIAGEM"
        hoje = data_do_agora(self.agora)
        licoes = self.ctx.longa.relevantes(("urgencia_falsa", "sinal_p0_p1", "correcao_revisor", "mapeamento_frequente"), caso.assunto + " " + caso.corpo)
        partes = [
            f"Hoje (data simulada): {formatar_data(hoje) if hoje else self.agora}",
            "",
            "CATÁLOGO (tipos de chamado):",
            self.ctx.bases.texto_catalogo(),
            "",
            "TIMES:",
            self.ctx.bases.texto_times(),
            "",
            "LIÇÕES DA MEMÓRIA LONGA (padrões gerais aprendidos):",
            self.ctx.longa.formatar(licoes),
        ]
        if caso.contexto_anterior:
            partes += ["", "CONTEXTO: esta mensagem continua uma conversa já tratada.", caso.contexto_anterior]
        if info.get("devolucao"):
            partes += ["", "ATENÇÃO: o Revisor DEVOLVEU a proposta anterior. Reclassifique do zero, começando pela segurança, considerando:",
                       *[f"- {p}" for p in info.get("problemas", [])]]
        if caso.pedidos_info:
            partes += ["", f"Já pedimos informação ao solicitante {caso.pedidos_info} vez(es); as respostas estão no e-mail abaixo."]
        partes += ["", "E-MAIL:", caso.texto_completo()]
        try:
            triagem = await self.ctx.llm.json(self.nome, prompts.TRIADOR, "\n".join(partes), Triagem, caso_id=caso.caso_id)
        except ErroLLM as e:
            self.anotar(caso, "triagem", f"modelo falhou: {e}", "erro")
            self.salvar(caso)
            await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(categoria="erro_repetido", motivo=f"Triador sem saída válida do modelo: {e}"[:300], urgencia="alta"))
            return
        triagem = self._normalizar(caso, triagem, info)
        caso.triagem = triagem.model_dump()
        usadas = ", ".join(f"#{l['id']}" for l in licoes)
        self.anotar(caso, "triagem", f"{triagem.impacto}/{triagem.tipo_caso}/{triagem.tipo_catalogo or '-'} seg={triagem.seguranca}: {triagem.motivo}" + (f" (lições usadas: {usadas})" if usadas else ""))
        self.salvar(caso)

        if triagem.seguranca:
            categoria = triagem.categoria_seguranca or "seguranca"
            await self.mcp.conversa("escalador", f"Caso {caso.caso_id} ({caso.evento_id}): sinal de {categoria.replace('_', ' ')}. Só escala, sem ação e sem resposta ao solicitante.")
            await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(categoria=categoria, motivo=triagem.motivo_seguranca or triagem.motivo, urgencia="alta"))
            return
        await self.mcp.conversa("pesquisador", f"Caso {caso.caso_id}: {triagem.impacto}/{triagem.tipo_caso}. Procure duplicados antes de seguir.")
        await self.enviar("pesquisador", "PESQUISAR_DUPLICADO", caso, {"modo": "incidente" if triagem.tipo_caso == "incidente" else "chamado"})

    def _normalizar(self, caso: Caso, t: Triagem, info: dict) -> Triagem:
        """Regras do tema aplicadas por código, sempre para o lado seguro."""
        texto = caso.texto_completo()
        sensiveis = tem_dado_sensivel(texto)
        if sensiveis and not t.seguranca:
            t.seguranca, t.categoria_seguranca = True, "dado_sensivel"
            t.motivo_seguranca = f"dado pessoal sensível detectado no texto ({', '.join(sensiveis)})"
        if info.get("exigir_escalacao"):
            t.seguranca = True
            t.categoria_seguranca = t.categoria_seguranca or "seguranca"
            t.motivo_seguranca = t.motivo_seguranca or "o Revisor apontou sinal de segurança"
        if t.seguranca and not t.categoria_seguranca:
            t.categoria_seguranca = "seguranca"
        t.impacto = rebaixar_se_individual(t.impacto, t.alcance, texto)
        # incidente só existe em P0-P2; P0-P2 é sempre incidente
        if t.impacto in INCIDENTE:
            t.tipo_caso = "incidente"
        elif t.tipo_caso == "incidente":
            t.tipo_caso = "pedido"
            t.tipo_catalogo = t.tipo_catalogo or self._tipo_suporte()
        # modo demonstração T14: força o Triador a rebaixar um P1 para P2 (o Revisor tem de pegar)
        if t.impacto == "P1" and self.ctx.banco.ajuste("sabotar_proximo_p1") == "1" and not info.get("devolucao"):
            self.ctx.banco.definir_ajuste("sabotar_proximo_p1", "0")
            t.impacto = "P2"
            t.motivo = "[demonstração T14: criticidade rebaixada de propósito] " + t.motivo
        # catálogo: tipo precisa existir; campos faltantes recalculados pelo código
        info_tipo = self.ctx.bases.tipo(t.tipo_catalogo) if t.tipo_catalogo else None
        if info_tipo:
            t.tipo_catalogo = info_tipo["tipo"]
            obrig = info_tipo.get("campos_obrigatorios") or []
            t.campos = {k: v for k, v in t.campos.items() if k in obrig}
            t.campos_faltantes = [c for c in obrig if not str(t.campos.get(c, "") or "").strip()]
        elif t.tipo_caso == "pedido":
            t.tipo_catalogo = None
            t.confianca = min(t.confianca, 0.5)
        if t.time_responsavel and not self.ctx.bases.time(t.time_responsavel):
            t.time_responsavel = None
        if not t.time_responsavel and info_tipo:
            t.time_responsavel = info_tipo.get("time")
        return t

    def _tipo_suporte(self) -> str | None:
        for c in self.ctx.bases.catalogo:
            if "suporte" in c["tipo"].lower():
                return c["tipo"]
        return None

    # ---------- depois da busca de duplicados ----------
    async def _depois_do_duplicado(self, caso: Caso) -> None:
        t = Triagem.model_validate(caso.triagem)
        if t.tipo_caso == "incidente":
            await self._propor(caso, "abrir_incidente", {
                "criticidade": t.impacto, "produto": t.produto, "resumo": t.resumo or caso.assunto,
                "sintomas": t.sintomas, "impacto": t.impacto_descricao, "contorno": t.contorno,
                "escalar_na_hora": t.impacto in ("P0", "P1"), "time": t.time_responsavel,
            }, criticidade=t.impacto, motivo=f"incidente {t.impacto}: {t.motivo}")
            return
        if t.tipo_caso == "duvida":
            await self.mcp.conversa("pesquisador", f"Caso {caso.caso_id}: é dúvida. Procure no FAQ: {t.pergunta or t.resumo}")
            await self.enviar("pesquisador", "PESQUISAR_FAQ", caso, {"pergunta": t.pergunta or t.resumo or caso.assunto})
            return
        # pedido
        info_tipo = self.ctx.bases.tipo(t.tipo_catalogo) if t.tipo_catalogo else None
        esgotado = caso.pedidos_info >= self.ctx.cfg.max_pedidos_info
        if not info_tipo or t.confianca < 0.6:
            if esgotado:
                await self._encaminhar(caso, t, "não deu para identificar o tipo do pedido mesmo após pedir esclarecimento")
            else:
                await self._pedir_info(caso, [], "esclarecer o que precisa ser feito (tipo do pedido incerto)")
            return
        if t.campos_faltantes:
            if esgotado:
                await self._encaminhar(caso, t, f"faltam {t.campos_faltantes} mesmo após {caso.pedidos_info} pedido(s) de informação")
            else:
                await self._pedir_info(caso, t.campos_faltantes, f"faltam campos obrigatórios do tipo {info_tipo['tipo']}")
            return
        exige = bool(info_tipo.get("aprovacao"))
        if info_tipo is self.ctx.bases.tipo_ferias():
            params = self._parametros_ferias(caso, t)
            await self._propor(caso, "lancar_ferias", params, exige=exige, motivo=f"pedido de férias completo ({params.get('inicio')} a {params.get('fim')})")
            return
        await self._propor(caso, "registrar_chamado", {
            "tipo": info_tipo["tipo"], "campos": t.campos, "resumo": t.resumo or caso.assunto, "time": info_tipo.get("time"),
            "prazo_dias_uteis": info_tipo.get("prazo_dias_uteis"), "aprovador": info_tipo.get("aprovacao"),
            "criticidade_avaliada": t.impacto,
        }, exige=exige, motivo=f"pedido completo do tipo {info_tipo['tipo']}: {t.motivo}")

    def _parametros_ferias(self, caso: Caso, t: Triagem) -> dict[str, Any]:
        hoje = data_do_agora(self.agora)
        campos = list(t.campos.values())
        inicio = parse_data(t.campos.get("data_de_inicio") or (campos[0] if campos else ""), hoje)
        fim = parse_data(t.campos.get("data_de_fim") or (campos[1] if len(campos) > 1 else ""), hoje)
        return {
            "email": caso.remetente.lower(),
            "inicio": formatar_data(inicio) if inicio else t.campos.get("data_de_inicio"),
            "fim": formatar_data(fim) if fim else t.campos.get("data_de_fim"),
            "evento": caso.evento_id, "tipo": t.tipo_catalogo,
        }

    async def _encaminhar(self, caso: Caso, t: Triagem, motivo: str) -> None:
        time = self.ctx.bases.time(t.time_responsavel) if t.time_responsavel else None
        time = time or self.ctx.bases.time_por_atende("nao se encaixam") or (self.ctx.bases.times[0] if self.ctx.bases.times else None)
        await self._propor(caso, "encaminhar_time", {"time": time["time"], "email": time["email"], "resumo": t.resumo or caso.assunto}, motivo=f"encaminhar sem inventar resposta: {motivo}")

    async def _pedir_info(self, caso: Caso, faltantes: list[str], motivo: str) -> None:
        self.anotar(caso, "pedir_info", motivo)
        self.salvar(caso)
        await self.enviar("executor", "PEDIR_INFO", caso, {"campos_faltantes": faltantes, "motivo": motivo, "tipo": (caso.triagem or {}).get("tipo_catalogo")})

    async def _propor(self, caso: Caso, acao: str, parametros: dict, criticidade: str | None = None, exige: bool = False, motivo: str = "") -> None:
        proposta = Proposta(
            proposta_id=f"p-{caso.caso_id[2:]}-{len(caso.propostas) + 1}", caso_id=caso.caso_id, autor="triador", acao=acao,
            parametros=parametros, criticidade=criticidade if criticidade in INCIDENTE else None, exige_aprovacao_humana=exige, motivo=motivo[:400],
        )
        caso.propostas.append(proposta.model_dump())
        caso.estado = "EM_REVISAO"
        self.anotar(caso, "propor", f"{acao}: {motivo}"[:300])
        self.salvar(caso)
        await self.enviar("revisor", "PROPOSTA", caso, proposta)
