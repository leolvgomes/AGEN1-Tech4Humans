"""4. REVISOR (segundo par de olhos). IA independente (prompt e, se configurado, modelo próprios).

1) Classifica o caso sozinho, ANTES de ver a proposta. 2) Compara e aplica o checklist do tipo de ação
(conferências objetivas por código + UMA pergunta semântica por ação à IA). 3) Aprova ou devolve com os problemas.
Nunca corrige nem executa. Uma objeção da IA só vale com prova conferível (trecho literal do e-mail, alternativa
que existe nas bases, campo com valor sem apoio): modelos pequenos repetem problemas de exemplo.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..contratos import Caso, ClassificacaoIndependente, Envelope, Proposta, Revisao, rebaixar_se_individual
from ..llm import ErroLLM
from ..util import PRIORIDADE, data_do_agora, mascarar, parse_data, sem_acento, trecho_no_texto, valor_no_texto
from . import prompts
from .base import Agente


class Conferencia(BaseModel):
    ok: bool  # obrigatório: sem ele a saída é inválida (e a revisão, inconclusiva)
    trecho: Optional[str] = ""
    alternativa: Optional[str] = ""
    campo: Optional[str] = ""
    explicacao: Optional[str] = ""


# A única pergunta semântica de cada ação; todo o resto do checklist é conferido por código.
PERGUNTAS = {
    "registrar_chamado": "O tipo do catálogo serve para o pedido e cada valor de campo veio do e-mail? Se outro tipo do catálogo servir claramente "
    "melhor, ok=false com a alternativa (nome exato do tipo) e o trecho do e-mail que mostra isso. Se um valor foi inventado, ok=false com o campo.",
    "responder_faq": "A resposta do FAQ responde ao que a pessoa perguntou? Se ficar sem resposta uma pergunta feita no e-mail, ok=false com o trecho "
    "do e-mail que contém essa pergunta.",
    "vincular_duplicado": "O e-mail trata do mesmo problema ou pedido do registro indicado? Cobrança, reenvio e outra pessoa relatando a mesma falha "
    "contam como o mesmo. Se for outro assunto, ok=false com o trecho do e-mail que mostra a diferença.",
    "encaminhar_time": "O time indicado é o que cuida do assunto? Se outro time cuidar, ok=false com a alternativa (nome exato do time).",
    "lancar_ferias": "As datas da proposta são as que a pessoa pediu? Se não forem, ok=false com o trecho do e-mail que traz as datas certas.",
    "abrir_incidente": "O e-mail relata uma falha de produto que atinge clientes? Se não relatar, ok=false com o trecho que mostra isso.",
}


class Revisor(Agente):
    nome = "revisor"

    async def receber(self, env: Envelope) -> None:
        if env.tipo == "PROPOSTA":
            await self._revisar(self.caso(env.caso_id), Proposta.model_validate(env.payload))

    async def _revisar(self, caso: Caso, p: Proposta) -> None:
        anterior = next((r for r in caso.revisoes if r.get("proposta_id") == p.proposta_id), None)
        if anterior:  # idempotência: reenvia a decisão anterior
            await self._encaminhar(caso, p, Revisao.model_validate(anterior), repetida=True)
            return

        texto = caso.texto_completo()
        # 1) classificação independente, só com o caso original
        try:
            minha = await self.ctx.llm.json(
                self.nome, prompts.REVISOR_CLASSIFICAR,
                "LIÇÕES (correções anteriores e sinais de P0/P1):\n"
                + self.ctx.longa.formatar(self.ctx.longa.relevantes(("correcao_revisor", "sinal_p0_p1"), caso.assunto + " " + caso.corpo, 4))
                + "\n\nCASO ORIGINAL:\n" + caso.texto_completo(),
                ClassificacaoIndependente, revisor=True, caso_id=caso.caso_id,
            )
        except ErroLLM as e:
            rev = Revisao(proposta_id=p.proposta_id, decisao="devolver", problemas=[f"revisão inconclusiva: {e}"[:200]], motivo="o modelo do Revisor não respondeu no esquema")
            await self._encaminhar(caso, p, rev)
            return

        minha.impacto = rebaixar_se_individual(minha.impacto, minha.alcance, texto)
        if minha.impacto not in ("P0", "P1", "P2") and minha.tipo_caso == "incidente":
            minha.tipo_caso = "pedido"

        # 2) checklist objetivo
        problemas = self._checklist(caso, p, minha)
        categorias = ["regra"] if problemas else []
        ignoradas: list[str] = []
        exigir_escalacao = minha.seguranca

        # 3) julgamento semântico (P0/P1 aprovados de forma curta: sem bloquear a escalação por redação)
        curto = p.acao == "abrir_incidente" and p.criticidade in ("P0", "P1")
        if not problemas and not curto:
            try:
                conf = await self.ctx.llm.json(self.nome, prompts.REVISOR_CONFERIR, self._texto_conferencia(caso, p, minha), Conferencia, revisor=True, caso_id=caso.caso_id)
                problema, categoria = self._objecao(p, conf, texto)
                if problema:
                    problemas.append(problema)
                    categorias.append(categoria)
                elif not conf.ok:
                    ignoradas.append(mascarar(conf.explicacao or "sem explicação")[:200])
            except ErroLLM as e:
                problemas.append(f"revisão inconclusiva: {e}"[:200])

        decisao = "devolver" if problemas else "aprovar"
        rev = Revisao(
            proposta_id=p.proposta_id, classificacao_independente=minha, decisao=decisao, problemas=problemas,
            motivo=(f"proposta {p.acao} confere com a classificação independente ({minha.impacto}/{minha.tipo_caso})" if decisao == "aprovar"
                    else f"{len(problemas)} problema(s) na proposta {p.acao}"),
            categorias=categorias, objecoes_ignoradas=ignoradas,
            exigir_escalacao=exigir_escalacao and decisao == "devolver",
        )
        await self._encaminhar(caso, p, rev)

    def _objecao(self, p: Proposta, c: Conferencia, texto: str) -> tuple[str, str]:
        """Transforma a resposta da IA em problema só se a prova confere; senão ('', '')."""
        if c.ok:
            return "", ""
        b, par = self.ctx.bases, p.parametros
        trecho = (c.trecho or "").strip()
        tem_trecho = trecho_no_texto(trecho, texto)
        citacao = f'"{mascarar(trecho)[:120]}"'
        if p.acao == "registrar_chamado":
            alt, atual = b.tipo(c.alternativa), b.tipo(par.get("tipo"))
            if alt and alt is not atual and tem_trecho:
                return f"o tipo do catálogo deveria ser {alt['tipo']} e não {par.get('tipo')}: o e-mail diz {citacao}", "tipo_catalogo"
            campos = par.get("campos") or {}
            if c.campo in campos and not valor_no_texto(campos[c.campo], texto):
                return f"o valor do campo {c.campo} não está no e-mail", "valor_sem_apoio"
            return "", ""
        if p.acao == "encaminhar_time":
            alt = b.time(c.alternativa)
            if alt and sem_acento(alt["time"]) != sem_acento(par.get("time")):
                return f"o time responsável deveria ser {alt['time']} e não {par.get('time')}", "time_errado"
            return "", ""
        if not tem_trecho:
            return "", ""
        return {
            "responder_faq": (f"o item do FAQ não responde a esta parte do e-mail: {citacao}", "faq_parcial"),
            "vincular_duplicado": (f"não é o mesmo assunto de {par.get('registro_id')}: o e-mail diz {citacao}", "duplicado_errado"),
            "lancar_ferias": (f"as datas não conferem com o e-mail: {citacao}", "datas"),
            "abrir_incidente": (f"o e-mail não descreve falha que atinja clientes: {citacao}", "nao_incidente"),
        }[p.acao]

    def _checklist(self, caso: Caso, p: Proposta, minha: ClassificacaoIndependente) -> list[str]:
        b = self.ctx.bases
        prob: list[str] = []
        par = p.parametros
        if minha.seguranca:
            prob.append("sinal de segurança ou dado pessoal sensível ignorado: o caso deve ser só escalado")
        crit_prop = p.criticidade if p.acao in ("abrir_incidente", "vincular_duplicado") else None
        if minha.impacto in ("P0", "P1", "P2"):
            if p.acao == "vincular_duplicado" and crit_prop is None and minha.impacto == "P2":
                pass  # P2 já em andamento num chamado aberto: vincular basta (P0/P1 nunca)
            elif crit_prop is None:
                prob.append(f"o Revisor classificou incidente {minha.impacto}, mas a proposta é {p.acao} sem criticidade")
            elif PRIORIDADE[crit_prop] > PRIORIDADE[minha.impacto]:
                prob.append(f"criticidade proposta ({crit_prop}) menor que a do revisor ({minha.impacto})")
        if p.acao == "abrir_incidente":
            if p.criticidade in ("P0", "P1") and not par.get("escalar_na_hora"):
                prob.append("P0/P1 precisa estar marcado para escalar na hora")
            if not (par.get("resumo") or "").strip():
                prob.append("incidente sem resumo do que está acontecendo")
            if not par.get("produto"):
                prob.append("incidente sem produto afetado")
        elif p.acao == "responder_faq":
            item = b.faq_item(par.get("faq_id"))
            if not item:
                prob.append(f"faq_id {par.get('faq_id')} não existe no FAQ")
            elif (par.get("texto_resposta") or "").strip() != (item.get("resposta") or "").strip():
                prob.append("o texto não é literalmente o do item do FAQ")
        elif p.acao == "encaminhar_time":
            if not b.time(par.get("time")):
                prob.append(f"o time '{par.get('time')}' não existe na base de times")
        elif p.acao == "vincular_duplicado":
            regs = b.incidentes if par.get("base") == "incidentes" else b.chamados
            alvo = next((r for r in regs if str(r.get("id")) == str(par.get("registro_id"))), None)
            if not alvo:
                prob.append(f"o registro {par.get('registro_id')} não existe")
            elif sem_acento(alvo.get("status", "")) in ("resolvido", "cancelado"):
                prob.append(f"o registro {alvo['id']} está fechado: é pedido novo, não duplicado")
            if not par.get("avisar_solicitante"):
                prob.append("o solicitante precisa ser avisado do vínculo")
        elif p.acao == "registrar_chamado":
            info = b.tipo(par.get("tipo"))
            if not info:
                prob.append(f"tipo '{par.get('tipo')}' não existe no catálogo")
            else:
                if info is b.tipo_ferias():
                    prob.append("férias não se registram como chamado: só pelo sistema de férias (tela)")
                faltam = [c for c in info.get("campos_obrigatorios") or [] if not str((par.get("campos") or {}).get(c, "") or "").strip()]
                if faltam:
                    prob.append(f"campos obrigatórios ausentes: {faltam}")
                if bool(info.get("aprovacao")) != p.exige_aprovacao_humana:
                    prob.append(f"exige_aprovacao_humana deveria ser {bool(info.get('aprovacao'))} conforme o catálogo")
                if par.get("time") and sem_acento(par["time"]) != sem_acento(info.get("time")):
                    prob.append(f"time do chamado deveria ser {info.get('time')}")
        elif p.acao == "lancar_ferias":
            info = b.tipo_ferias()
            hoje = data_do_agora(self.agora)
            ini, fim = parse_data(par.get("inicio")), parse_data(par.get("fim"))
            if not ini or not fim:
                prob.append("datas de férias ausentes ou fora do formato DD/MM/AAAA")
            elif fim < ini:
                prob.append("o último dia de férias é antes do primeiro")
            elif hoje and ini < hoje:
                prob.append("as férias começam no passado")
            if not par.get("email"):
                prob.append("colaborador não identificado")
            if info and bool(info.get("aprovacao")) != p.exige_aprovacao_humana:
                prob.append("o fluxo de aprovação de férias não foi respeitado")
        return prob

    def _texto_conferencia(self, caso: Caso, p: Proposta, minha: ClassificacaoIndependente) -> str:
        b = self.ctx.bases
        extra = ""
        if p.acao == "registrar_chamado":
            info = b.tipo(p.parametros.get("tipo")) or {}
            extra = f"Tipo do catálogo: {info}\nOutros tipos:\n{b.texto_catalogo()}"
        elif p.acao == "responder_faq":
            extra = f"Item do FAQ: {b.faq_item(p.parametros.get('faq_id'))}"
        elif p.acao == "encaminhar_time":
            extra = f"Times:\n{b.texto_times()}"
        elif p.acao == "vincular_duplicado":
            extra = f"Registro indicado: {p.parametros.get('registro')}"
        return (
            f"CASO ORIGINAL:\n{caso.texto_completo()}\n\nPROPOSTA: {p.acao}\n{p.parametros}\n\nFATOS DAS BASES:\n{extra}\n\n"
            f"PERGUNTA: {PERGUNTAS[p.acao]}"
        )

    async def _encaminhar(self, caso: Caso, p: Proposta, rev: Revisao, repetida: bool = False) -> None:
        if not repetida:
            caso.revisoes.append(rev.model_dump())
        self.anotar(caso, f"revisao/{rev.decisao}", f"{p.proposta_id} ({p.acao}): {rev.motivo}. {'; '.join(rev.problemas)}"[:400])
        if rev.objecoes_ignoradas:
            self.anotar(caso, "objecao_sem_prova", f"{p.proposta_id}: {'; '.join(rev.objecoes_ignoradas)}"[:300], "ignorada")
        if rev.decisao == "aprovar":
            if not repetida:
                self._aprender_correcao(caso, p)
            caso.estado = "EXECUTANDO"
            self.salvar(caso)
            if p.criticidade in ("P0", "P1"):
                await self.mcp.conversa(p.autor, f"Aprovado com prioridade: {p.acao} {p.criticidade} no caso {caso.caso_id} ({caso.evento_id}).")
            await self.enviar("executor", "EXECUTAR", caso, {"proposta": p.model_dump(), "revisao": rev.model_dump()})
            return
        self.salvar(caso)
        await self.mcp.conversa(p.autor, f"Devolvo {p.proposta_id} ({p.acao}) do caso {caso.caso_id}: " + "; ".join(rev.problemas))
        await self.enviar("despachante", "REVISAO", caso, rev)

    def _aprender_correcao(self, caso: Caso, p: Proposta) -> None:
        """Só vira lição a correção que deu certo (devolvida e depois aprovada diferente), por categoria fixa:
        nunca o texto do modelo, que pode trazer nome de pessoa ou um problema inventado."""
        for prop in caso.propostas[:-1]:
            rev = next((r for r in caso.revisoes if r.get("proposta_id") == prop["proposta_id"] and r.get("decisao") == "devolver"), None)
            antes = prop.get("criticidade") or prop["parametros"].get("tipo") or prop["acao"]
            depois = p.criticidade or p.parametros.get("tipo") or p.acao
            if not rev or antes == depois:
                continue
            for cat in (rev.get("categorias") or [])[:2]:
                self.ctx.longa.observar("correcao_revisor", f"{cat}: {antes}->{depois}", f"o Revisor já corrigiu {antes} para {depois} ({cat.replace('_', ' ')})", caso.caso_id)
