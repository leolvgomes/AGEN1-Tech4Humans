"""5. EXECUTOR (único que escreve nas bases e responde a solicitantes).

Código determinístico para as chamadas e a idempotência (chave evento_id + etapa, e rotina ja_foi_feito() que
consulta o servidor depois de um 504). IA só para redigir mensagens, com os fatos dados pelo código.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional

from ..contratos import Caso, DecisaoHumana, Envelope, PedidoEscalar, Proposta, ResultadoFinal, Revisao
from ..llm import ErroLLM
from ..mcp_client import CenarioEncerrado, ErroMCP, RodadaObsoleta
from ..util import mascarar, rotulo_campo, sem_acento
from . import prompts
from .base import Agente

ASSINATURA = "Atendimento N1 - T4H"


class Executor(Agente):
    nome = "executor"

    async def receber(self, env: Envelope) -> None:
        caso = self.caso(env.caso_id)
        try:
            if env.tipo == "EXECUTAR":
                p = Proposta.model_validate(env.payload["proposta"])
                rev = Revisao.model_validate(env.payload["revisao"])
                await self._executar(caso, p, rev)
            elif env.tipo == "PEDIR_INFO":
                await self._pedir_info(caso, env.payload)
            elif env.tipo == "DECISAO_HUMANA":
                await self._decisao(caso, DecisaoHumana.model_validate(env.payload))
            elif env.tipo == "CONFIRMAR_FERIAS":
                await self._confirmar_ferias(caso, env.payload)
        except RodadaObsoleta as e:
            self.anotar(caso, "acao_cancelada", f"rodada antiga: {e}", "obsoleto")
        except CenarioEncerrado:
            caso.estado = "ERRO"
            self.anotar(caso, "acao_cancelada", "o cenário acabou (410): nenhuma ação nova", "encerrado")
            self.salvar(caso)
        except ErroMCP as e:
            await self._tratar_erro(caso, e, env)

    def _verificar_registro(self, papel: str, evento_id: str):
        async def ja_foi_feito() -> Optional[dict]:
            regs = await self.ctx.bases.listar(self.mcp, papel, filtro={"pedidos": evento_id}, motivo="504/409: conferir se o registro já foi criado antes de repetir")
            achado = next((r for r in regs if evento_id in (r.get("pedidos") or []) and r.get("aberto_por") == self.nome), None)
            return {"registro": achado} if achado else None
        return ja_foi_feito

    async def _atualizar(self, caso: Caso, etapa: str, papel: str, registro_id: str, dados: dict, motivo: str) -> dict:
        base = self.ctx.bases.nome(papel)

        async def ja_foi_feito() -> Optional[dict]:
            regs = await self.ctx.bases.listar(self.mcp, papel, filtro={"id": registro_id}, motivo="conferir o registro antes de repetir a atualização")
            r = next((x for x in regs if str(x.get("id")) == str(registro_id)), None)
            if not r:
                return None
            for k, v in dados.items():
                if k == "pedidos":
                    if not set(v if isinstance(v, list) else [v]) <= set(r.get("pedidos") or []):
                        return None
                elif sem_acento(r.get(k)) != sem_acento(v):
                    return None
            return {"registro": r}

        return await self._acao(caso, etapa, "atualizar", motivo, verificar=ja_foi_feito, base=base, id=registro_id, dados=dados, evento_id=caso.evento_id)

    # ---------- redação ----------
    @staticmethod
    def _saudacao(caso: Caso) -> str:
        nome = (caso.nome or caso.remetente.split("@")[0].split(".")[0]).split()[0].capitalize() if (caso.nome or caso.remetente) else ""
        return f"Olá, {nome}!" if nome else "Olá!"

    async def _redigir(self, caso: Caso, objetivo: str, fatos: dict, modelo: str) -> str:
        """IA redige com os fatos; se a resposta trouxer número que não está nos fatos ou ficar longa, usa o modelo pronto."""
        try:
            texto = await self.ctx.llm.texto(self.nome, prompts.EXECUTOR_REDIGIR,
                                             f"Destinatário: {caso.nome or caso.remetente}\nObjetivo: {objetivo}\nFatos: {fatos}", caso_id=caso.caso_id)
            numeros_fatos = set(re.findall(r"\d+", str(fatos) + ASSINATURA))
            intrusos = [n for n in re.findall(r"\d+", texto) if n not in numeros_fatos]
            linhas = [l for l in texto.splitlines() if l.strip()]
            if texto and not intrusos and len(linhas) <= 10 and len(texto) < 1500:
                return texto
        except ErroLLM:
            pass
        return modelo

    # ---------- execução das propostas aprovadas ----------
    async def _executar(self, caso: Caso, p: Proposta, rev: Revisao) -> None:
        if rev.decisao != "aprovar" or rev.proposta_id != p.proposta_id:
            self.anotar(caso, "executar", "proposta sem aprovação do Revisor: não executo", "recusado")
            return
        if caso.estado in ("ESCALADO", "CONCLUIDO"):
            self.anotar(caso, "executar", f"caso já está {caso.estado}: não executo de novo", "ignorado")
            return
        caso.estado = "EXECUTANDO"
        self.salvar(caso)
        acao = p.acao
        if p.exige_aprovacao_humana and not (caso.aprovacao and caso.aprovacao.get("status") == "aprovada"):
            await self._pedir_aprovacao(caso, p)
            return
        await getattr(self, f"_x_{acao}")(caso, p)

    async def _x_abrir_incidente(self, caso: Caso, p: Proposta) -> None:
        par = p.parametros
        r = await self._acao(
            caso, "registrar_incidente", "registrar", f"abrir incidente {p.criticidade}: {p.motivo}"[:300],
            verificar=self._verificar_registro("incidentes", caso.evento_id),
            base=self.ctx.bases.nome("incidentes"), evento_id=caso.evento_id,
            dados={"criticidade": p.criticidade, "produto": par.get("produto"), "resumo": self._resumo_incidente(par)},
        )
        inc = r.get("registro") or {}
        caso.registro_criado = {"base": "incidentes", "id": inc.get("id"), "criticidade": p.criticidade}
        self.ctx.bases.incidentes.append(inc)
        await self._ligar_extras(caso, "incidentes", inc.get("id"))
        time = self._time_incidente(par)
        fatos = {"incidente": inc.get("id"), "criticidade": p.criticidade, "produto": par.get("produto"), "time_responsavel": time.get("time")}
        modelo = (f"{self._saudacao(caso)}\nRegistramos o incidente {inc.get('id')} sobre {par.get('produto') or 'o problema relatado'} "
                  f"e o time {time.get('time')} já foi acionado.\nVamos avisar quando houver novidades.\n{ASSINATURA}")
        texto = await self._redigir(caso, "confirmar a abertura do incidente e o time responsável", fatos, modelo)
        await self._responder(caso, "responder_incidente", texto, f"confirmar abertura do incidente {inc.get('id')} ao solicitante")
        self.salvar(caso)
        if p.criticidade in ("P0", "P1"):
            await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(
                categoria="incidente_p0" if p.criticidade == "P0" else "incidente_p1", urgencia="imediata",
                motivo=f"incidente {p.criticidade} aberto ({inc.get('id')}): escalar na hora ao plantonista",
                detalhes={"incidente_id": inc.get("id"), "time": time.get("time"), "email": time.get("email"), "produto": par.get("produto"), "resumo": par.get("resumo")},
            ))
            return
        await self._resultado(caso, "CONCLUIDO", "abrir_incidente", {"incidente_id": inc.get("id"), "criticidade": p.criticidade}, "incidente P2 aberto, sem escalação imediata")

    async def _ligar_extras(self, caso: Caso, papel: str, reg_id: Optional[str]) -> None:
        """Respostas do solicitante que fazem parte do mesmo caso também ficam ligadas ao registro."""
        extras = [e for e in caso.eventos if e != caso.evento_id]
        if reg_id and extras:
            await self._atualizar(caso, f"ligar_extras_{len(extras)}", papel, reg_id, {"pedidos": extras}, f"ligar as respostas {extras} ao {reg_id}")

    @staticmethod
    def _resumo_incidente(par: dict) -> str:
        partes = [par.get("resumo") or ""]
        for k, rot in (("sintomas", "Sintomas"), ("impacto", "Impacto"), ("contorno", "Contorno")):
            if par.get(k):
                partes.append(f"{rot}: {par[k]}")
        return mascarar(" | ".join(p for p in partes if p))[:1900]

    def _time_incidente(self, par: dict) -> dict:
        b = self.ctx.bases
        t = b.time(par.get("time")) if par.get("time") else None
        if not t and par.get("produto"):
            t = b.time_por_atende(par["produto"])
        if not t:
            sup = next((c for c in b.catalogo if "suporte" in sem_acento(c["tipo"])), None)
            t = b.time(sup["time"]) if sup else None
        return t or (b.times[0] if b.times else {"time": "?", "email": ""})

    async def _x_vincular_duplicado(self, caso: Caso, p: Proposta) -> None:
        par = p.parametros
        papel = "incidentes" if par.get("base") == "incidentes" else "chamados"
        reg_id = str(par["registro_id"])
        await self._atualizar(caso, "vincular", papel, reg_id, {"pedidos": [caso.evento_id]}, f"vincular {caso.evento_id} ao {reg_id} (mesmo problema/pedido ainda aberto)")
        caso.registro_criado = {"base": papel, "id": reg_id, "vinculado": True}
        reg = par.get("registro") or {}
        fatos = {"registro": reg_id, "resumo": reg.get("resumo"), "status": reg.get("status")}
        modelo = (f"{self._saudacao(caso)}\nSeu pedido já está em andamento no {reg_id} ({mascarar(reg.get('resumo') or 'mesmo assunto')}), "
                  f"com status \"{reg.get('status') or 'aberto'}\".\nVinculamos sua mensagem a ele, sem abrir um registro novo.\n{ASSINATURA}")
        texto = await self._redigir(caso, "avisar que o pedido já está em andamento e informar o registro existente", fatos, modelo)
        await self._responder(caso, "responder_vinculo", texto, f"avisar o solicitante do vínculo com {reg_id}")
        await self._resultado(caso, "CONCLUIDO", "vincular_duplicado", {"registro_id": reg_id}, f"vinculado ao {reg_id}")

    async def _x_responder_faq(self, caso: Caso, p: Proposta) -> None:
        item = self.ctx.bases.faq_item(p.parametros["faq_id"])
        if not item or item["resposta"].strip() != p.parametros["texto_resposta"].strip():
            raise ErroMCP(422, "texto do FAQ não confere com a base: não respondo")
        # Só saudação e fechamento em volta do texto literal do FAQ: nenhuma informação a mais.
        texto = f"{self._saudacao(caso)}\n{item['resposta']}\n{ASSINATURA}"
        await self._responder(caso, "responder_faq", texto, f"resposta do FAQ item {item['id']}, pergunta coberta integralmente")
        await self._resultado(caso, "CONCLUIDO", "responder_faq", {"faq_id": item["id"]}, f"respondido com o FAQ {item['id']}")

    async def _x_encaminhar_time(self, caso: Caso, p: Proposta) -> None:
        par = p.parametros
        time = self.ctx.bases.time(par["time"]) or {"time": par["time"], "email": par.get("email")}
        corpo = (f"Encaminhamento do Atendimento N1 (evento {caso.evento_id}).\nSolicitante: {caso.nome} <{caso.remetente}>\n"
                 f"Assunto: {caso.assunto}\nResumo: {par.get('resumo')}\n\nMensagem original:\n{mascarar(caso.texto_completo())[:1400]}")
        await self._mensagem_time(caso, "encaminhar_time", time["email"], f"[N1] {caso.assunto}"[:280], corpo, f"encaminhar ao time {time['time']} (fora do FAQ/ sem resposta pronta)")
        fatos = {"time_responsavel": time["time"]}
        modelo = f"{self._saudacao(caso)}\nEncaminhamos seu pedido ao time {time['time']}, que é o responsável pelo assunto e vai retornar diretamente.\n{ASSINATURA}"
        texto = await self._redigir(caso, "avisar que o pedido foi encaminhado ao time responsável, sem responder a pergunta", fatos, modelo)
        await self._responder(caso, "responder_encaminhado", texto, f"avisar que foi encaminhado ao time {time['time']}")
        await self._resultado(caso, "CONCLUIDO", "encaminhar_time", {"time": time["time"]}, f"encaminhado ao time {time['time']}")

    async def _x_registrar_chamado(self, caso: Caso, p: Proposta, status: str = "aberto") -> dict:
        par = p.parametros
        info = self.ctx.bases.tipo(par["tipo"]) or {}
        dados = {"tipo": info.get("tipo", par["tipo"]), "campos": par.get("campos") or {}, "resumo": mascarar(par.get("resumo") or caso.assunto)[:300], "status": status}
        if info.get("aprovacao"):
            dados["aprovador"] = info["aprovacao"]
        r = await self._acao(
            caso, "registrar_chamado", "registrar", f"registrar chamado {dados['tipo']} ({status}) com os campos obrigatórios do catálogo",
            verificar=self._verificar_registro("chamados", caso.evento_id), base=self.ctx.bases.nome("chamados"), evento_id=caso.evento_id, dados=dados,
        )
        ch = r.get("registro") or {}
        caso.registro_criado = {"base": "chamados", "id": ch.get("id"), "tipo": dados["tipo"], "status": status}
        self.ctx.bases.chamados.append(ch)
        self.salvar(caso)
        await self._ligar_extras(caso, "chamados", ch.get("id"))
        if status != "aberto":
            return ch
        prazo = info.get("prazo_dias_uteis")
        fatos = {"chamado": ch.get("id"), "time_responsavel": info.get("time"), "prazo_dias_uteis": prazo}
        modelo = (f"{self._saudacao(caso)}\nAbrimos o chamado {ch.get('id')} ({dados['tipo']}) com o time {info.get('time')}."
                  + (f"\nPrazo de atendimento: {prazo} dias úteis." if prazo else "\nO prazo depende da criticidade avaliada pelo time.") + f"\n{ASSINATURA}")
        texto = await self._redigir(caso, "informar o número do chamado, o time e o prazo do catálogo", fatos, modelo)
        await self._responder(caso, "responder_chamado", texto, f"informar o chamado {ch.get('id')}, time e prazo do catálogo")
        await self._resultado(caso, "CONCLUIDO", "registrar_chamado", {"chamado_id": ch.get("id"), "tipo": dados["tipo"]}, f"chamado {ch.get('id')} aberto")
        return ch

    async def _x_lancar_ferias(self, caso: Caso, p: Proposta) -> None:
        caso.estado = "EXECUTANDO"
        self.salvar(caso)
        await self.enviar("operador_tela", "LANCAR_FERIAS", caso, {**p.parametros, "aprovacao": caso.aprovacao})

    # ---------- aprovação humana ----------
    async def _pedir_aprovacao(self, caso: Caso, p: Proposta) -> None:
        info = self.ctx.bases.tipo(p.parametros.get("tipo")) or self.ctx.bases.tipo_ferias() or {}
        aprovador = info.get("aprovacao") or "gestor"
        detalhes: dict[str, Any] = {}
        if p.acao == "registrar_chamado":
            ch = await self._x_registrar_chamado(caso, p, status="aguardando aprovação")
            detalhes["chamado_id"] = ch.get("id")
            modelo = (f"{self._saudacao(caso)}\nRegistramos seu pedido no chamado {ch.get('id')} ({info.get('tipo')}). "
                      f"Ele aguarda a aprovação de: {aprovador}. Avisaremos assim que houver a decisão.\n{ASSINATURA}")
            fatos = {"chamado": ch.get("id"), "aprovacao_necessaria": aprovador}
        else:
            modelo = (f"{self._saudacao(caso)}\nRecebemos seu pedido de férias de {p.parametros.get('inicio')} a {p.parametros.get('fim')}. "
                      f"Ele aguarda a aprovação de: {aprovador} antes do lançamento. Avisaremos assim que houver a decisão.\n{ASSINATURA}")
            fatos = {"inicio": p.parametros.get("inicio"), "fim": p.parametros.get("fim"), "aprovacao_necessaria": aprovador}
        texto = await self._redigir(caso, "avisar que o pedido foi registrado e aguarda aprovação (sem prometer resultado)", fatos, modelo)
        await self._responder(caso, "responder_aguardando_aprovacao", texto, f"avisar que {p.acao} aguarda aprovação de {aprovador}")
        caso.estado = "AGUARDANDO_APROVACAO"
        caso.aprovacao = {"status": "pendente", "proposta": p.model_dump(), "aprovador_catalogo": aprovador, **detalhes}
        self.salvar(caso)
        await self.enviar("escalador", "PEDIR_APROVACAO", caso, {
            "acao": {"tipo": p.acao, "parametros": p.parametros, **detalhes},
            "justificativa": f"{p.motivo} O catálogo exige aprovação de: {aprovador}.",
            "aprovador_catalogo": aprovador,
        })
        await self._resultado(caso, "AGUARDANDO_APROVACAO", p.acao, detalhes, f"aguardando OK humano ({aprovador})")

    async def _decisao(self, caso: Caso, d: DecisaoHumana) -> None:
        if not caso.aprovacao or caso.aprovacao.get("status") != "pendente":
            self.anotar(caso, "decisao_humana", "decisão sem aprovação pendente: ignorada", "ignorado")
            return
        p = Proposta.model_validate(caso.aprovacao["proposta"])
        caso.aprovacao.update({"status": d.decisao, "decidido_por": d.decidido_por, "decidido_em": d.decidido_em, "comentario": d.comentario})
        self.salvar(caso)
        chamado_id = caso.aprovacao.get("chamado_id")
        if d.decisao == "recusada":
            if chamado_id:
                await self._atualizar(caso, "cancelar_chamado", "chamados", chamado_id,
                                      {"status": "cancelado", "observacao": f"Recusado por {d.decidido_por} no canal humano em {d.decidido_em}. {d.comentario or ''}"[:1900]},
                                      f"registrar a recusa humana de {d.decidido_por} no chamado")
            await self._resultado(caso, "CONCLUIDO", "recusa_humana", {"chamado_id": chamado_id, "decidido_por": d.decidido_por}, "recusado por uma pessoa; o Escalador informou o solicitante")
            return
        # aprovada: agora sim executa
        if p.acao == "registrar_chamado" and chamado_id:
            await self._atualizar(caso, "aprovar_chamado", "chamados", chamado_id,
                                  {"status": "aberto", "aprovador": f"{d.decidido_por} (canal humano)"[:190], "observacao": f"Aprovado por {d.decidido_por} em {d.decidido_em}. {d.comentario or ''}"[:1900]},
                                  f"registrar o OK humano de {d.decidido_por} e liberar o chamado")
            info = self.ctx.bases.tipo(p.parametros.get("tipo")) or {}
            prazo = info.get("prazo_dias_uteis")
            fatos = {"chamado": chamado_id, "time_responsavel": info.get("time"), "prazo_dias_uteis": prazo}
            modelo = (f"{self._saudacao(caso)}\nSeu pedido no chamado {chamado_id} foi aprovado e segue com o time {info.get('time')}."
                      + (f"\nPrazo de atendimento: {prazo} dias úteis." if prazo else "") + f"\n{ASSINATURA}")
            texto = await self._redigir(caso, "informar que o chamado foi aprovado, o time e o prazo do catálogo", fatos, modelo)
            await self._responder(caso, "responder_aprovado", texto, f"informar aprovação do chamado {chamado_id}")
            await self._resultado(caso, "CONCLUIDO", "registrar_chamado", {"chamado_id": chamado_id, "aprovado_por": d.decidido_por}, "chamado aprovado e liberado")
        elif p.acao == "lancar_ferias":
            await self._x_lancar_ferias(caso, p)
        else:
            await getattr(self, f"_x_{p.acao}")(caso, p)

    async def _confirmar_ferias(self, caso: Caso, det: dict) -> None:
        fatos = {"protocolo": det.get("comprovante"), "inicio": det.get("inicio"), "fim": det.get("fim")}
        modelo = (f"{self._saudacao(caso)}\nSuas férias de {det.get('inicio')} a {det.get('fim')} foram lançadas no sistema de férias. "
                  f"Protocolo {det.get('comprovante')}.\n{ASSINATURA}")
        texto = await self._redigir(caso, "confirmar o lançamento das férias com o protocolo", fatos, modelo)
        await self._responder(caso, "responder_ferias", texto, f"confirmar o lançamento de férias {det.get('comprovante')}")
        caso.registro_criado = {"base": "tela/ferias", "id": det.get("comprovante")}
        await self._resultado(caso, "CONCLUIDO", "lancar_ferias", fatos, "férias lançadas pela tela e confirmadas ao solicitante")

    # ---------- pedir o que falta (faz sozinho) ----------
    async def _pedir_info(self, caso: Caso, info: dict) -> None:
        faltantes = info.get("campos_faltantes") or []
        n = caso.pedidos_info + 1
        if faltantes:
            lista = "\n".join(f"- {rotulo_campo(c)}" for c in faltantes)
            modelo = f"{self._saudacao(caso)}\nPara seguir com seu pedido, precisamos destas informações:\n{lista}\nÉ só responder este e-mail.\n{ASSINATURA}"
            objetivo = "pedir exatamente os campos faltantes, um por linha"
            fatos = {"campos_faltantes": [rotulo_campo(c) for c in faltantes], "tipo_de_pedido": info.get("tipo")}
        else:
            modelo = (f"{self._saudacao(caso)}\nPara encaminhar corretamente, pode detalhar um pouco mais o que você precisa "
                      f"(o que deve ser feito, em qual sistema ou equipamento e para quando)?\nÉ só responder este e-mail.\n{ASSINATURA}")
            objetivo = "pedir esclarecimento sobre o que o solicitante precisa (tipo do pedido não ficou claro)"
            fatos = {"esclarecer": "o que deve ser feito, em qual sistema ou equipamento e para quando"}
        texto = await self._redigir(caso, objetivo, fatos, modelo)
        if faltantes and not all(rotulo_campo(c).split()[0].lower() in sem_acento(texto) for c in faltantes):
            texto = modelo  # garante que TODOS os campos faltantes estão na mensagem
        await self._responder(caso, f"pedir_info_{n}", texto, f"pedir o que falta: {', '.join(faltantes) or 'esclarecimento'}", aguardar=True)
        caso.pedidos_info = n
        caso.estado = "AGUARDANDO_SOLICITANTE"
        self.salvar(caso)
        await self._resultado(caso, "AGUARDANDO_SOLICITANTE", "pedir_info", {"campos_faltantes": faltantes}, "aguardando resposta do solicitante")

    # ---------- fim e erros ----------
    async def _resultado(self, caso: Caso, estado: str, acao: str, detalhes: dict, motivo: str) -> None:
        if estado in ("CONCLUIDO", "AGUARDANDO_APROVACAO", "AGUARDANDO_SOLICITANTE") and not (caso.registro_criado or {}).get("id"):
            await self._cobrir_extras(caso)
        self.salvar(caso)
        await self.enviar("despachante", "RESULTADO", caso, ResultadoFinal(estado=estado, acao=acao, detalhes=detalhes, motivo=motivo))

    async def _cobrir_extras(self, caso: Caso) -> None:
        """E-mail novo (não resposta automática do mundo) que foi juntado ao caso também recebe retorno."""
        for c in caso.complementos:
            if c.get("origem") in ("cenario", "painel") and c.get("evento_id"):
                texto = f"{self._saudacao(caso)}\nRecebemos sua nova mensagem e ela foi juntada ao seu pedido em andamento ({caso.assunto}).\n{ASSINATURA}"
                await self._responder(caso, f"extra_{c['evento_id']}", texto, f"confirmar que {c['evento_id']} foi juntado ao caso {caso.caso_id}", evento_id=c["evento_id"])

    async def _tratar_erro(self, caso: Caso, e: ErroMCP, env: Envelope) -> None:
        self.anotar(caso, "erro_execucao", f"{e.codigo}: {e.mensagem}"[:300], f"erro_{e.codigo}")
        self.salvar(caso)
        if e.codigo in (400, 422) and env.tipo == "EXECUTAR":
            p = env.payload["proposta"]
            await self.enviar("despachante", "REVISAO", caso, Revisao(
                proposta_id=p["proposta_id"], decisao="devolver", problemas=[f"o servidor recusou a ação ({e.codigo}): {e.mensagem}"[:300]],
                motivo="erro de valor/regra na execução: devolvido ao autor, sem insistir com o mesmo valor",
            ))
            return
        await self.enviar("escalador", "ESCALAR", caso, PedidoEscalar(categoria="erro_repetido", motivo=f"erro {e.codigo} persistente na execução: {e.mensagem}"[:300], urgencia="alta"))
