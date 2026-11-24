"""Regressão do Revisor: na execução real ele devolveu 155 propostas e aprovou 4, porque o modelo repetia os
problemas de exemplo do prompt. Aqui o "papagaio" faz o mesmo; o Revisor só pode aceitar objeção com prova."""

from __future__ import annotations

import asyncio

import pytest

from src.agentes import Pesquisador, Revisor, prompts
from src.agentes.base import Bases, Contexto
from src.config import Config
from src.contratos import Caso, Proposta, Revisao
from src.log import Log
from src.mcp_client import ClienteMCP
from src.memoria import Banco, MemoriaCurta, MemoriaLonga

CATALOGO = [
    {"tipo": "Acesso a sistema", "time": "Segurança", "campos_obrigatorios": ["sistema", "justificativa"], "aprovacao": "Gestor"},
    {"tipo": "Novo equipamento", "time": "Infraestrutura", "campos_obrigatorios": ["item", "motivo"], "aprovacao": None},
    {"tipo": "Férias", "time": "Pessoas", "campos_obrigatorios": ["data_de_inicio", "data_de_fim"], "aprovacao": "Gestor"},
]
TIMES = [{"time": t, "atende": a, "email": f"{e}@t4h.exemplo"} for t, a, e in
         [("Segurança", "acessos", "seg"), ("Infraestrutura", "notebooks", "infra"), ("Marketing", "patrocínios", "mkt")]]
FAQ = [{"id": "FAQ-06", "pergunta": "Qual é o prazo do reembolso?", "resposta": "Até 5 dias úteis."}]
ECOS = ["campo obrigatório ausente ou com valor que não está no e-mail (criticidade)", "tipo do catálogo errado para o pedido", "time errado"]


class Modelo:
    def __init__(self, conferencia: dict, classificacao: dict | None = None) -> None:
        self.conferencia = conferencia
        self.classificacao = classificacao or {"seguranca": False, "impacto": "P3", "alcance": "uma_pessoa", "tipo_caso": "pedido"}

    async def json(self, agente, sistema, usuario, esquema, revisor=False, caso_id=None):
        return esquema.model_validate(self.classificacao if sistema == prompts.REVISOR_CLASSIFICAR else self.conferencia)


PAPAGAIO = {"ok": False, "trecho": "", "alternativa": "", "campo": "criticidade", "explicacao": ECOS[0], "decisao": "devolver", "problemas": ECOS}


def montar(tmp_path, modelo: Modelo) -> tuple[Revisor, list]:
    banco, log, enviados = Banco(tmp_path / "t.db"), Log(tmp_path, console=False), []

    class Bus:
        async def enviar(self, env):
            enviados.append(env)

    ctx = Contexto(cfg=Config(), log=log, banco=banco, curta=MemoriaCurta(banco), longa=MemoriaLonga(banco),
                   mcp=ClienteMCP("http://x/mcp", 15, log), llm=modelo, bus=Bus())  # type: ignore[arg-type]
    ctx.bases = Bases()
    ctx.bases.catalogo, ctx.bases.times, ctx.bases.faq = CATALOGO, TIMES, FAQ
    ctx.bases.chamados = [{"id": "CH-0902", "status": "aberto", "resumo": "notebook com bateria estufada"}]
    rev = Revisor(ctx)

    async def muda(*a, **k):
        return None

    rev.mcp.conversa = muda  # type: ignore[method-assign]
    return rev, enviados


def revisar(tmp_path, modelo, acao, parametros, corpo, exige=False, criticidade=None) -> tuple[Revisao, Revisor, Caso]:
    rev, _ = montar(tmp_path, modelo)
    caso = Caso(caso_id="c-0001", rodada=1, evento_id="E1", remetente="ana@t4h.exemplo", nome="Ana", assunto="pedido", corpo=corpo)
    p = Proposta(proposta_id="p-1", caso_id="c-0001", autor="triador", acao=acao, parametros=parametros, exige_aprovacao_humana=exige, criticidade=criticidade, motivo="m")
    caso.propostas.append(p.model_dump())
    rev.salvar(caso)
    asyncio.run(rev._revisar(caso, p))
    return Revisao.model_validate(caso.revisoes[-1]), rev, caso


CASOS = {
    "registrar_chamado": ({"tipo": "Novo equipamento", "campos": {"item": "headset", "motivo": "o antigo quebrou"}, "time": "Infraestrutura"}, "Preciso de um headset, o antigo quebrou."),
    "responder_faq": ({"faq_id": "FAQ-06", "texto_resposta": "Até 5 dias úteis."}, "Qual o prazo do reembolso? E quem aprova o pedido?"),
    "vincular_duplicado": ({"base": "chamados", "registro_id": "CH-0902", "avisar_solicitante": True}, "O notebook continua desligando. Também preciso de um monitor."),
    "encaminhar_time": ({"time": "Marketing"}, "Podemos patrocinar um evento?"),
    "lancar_ferias": ({"email": "ana@t4h.exemplo", "inicio": "11/01/2027", "fim": "22/01/2027"}, "Quero férias de 11/01/2027 a 22/01/2027."),
}


@pytest.mark.parametrize("acao", CASOS)
def test_objecao_sem_prova_nao_devolve(tmp_path, acao):
    par, corpo = CASOS[acao]
    rev, _, caso = revisar(tmp_path, Modelo(PAPAGAIO), acao, par, corpo, exige=acao == "lancar_ferias")
    assert rev.decisao == "aprovar", rev.problemas
    assert any(h["acao"] == "objecao_sem_prova" for h in caso.historico)  # fica visível no histórico


@pytest.mark.parametrize("acao,prova,parametros", [
    ("registrar_chamado", {"alternativa": "Acesso a sistema", "trecho": "acesso ao CRM"}, {"tipo": "Novo equipamento", "campos": {"item": "crm", "motivo": "acesso"}, "time": "Infraestrutura"}),
    ("registrar_chamado", {"campo": "motivo"}, {"tipo": "Novo equipamento", "campos": {"item": "acesso", "motivo": "cliente internacional exige videoconferência"}, "time": "Infraestrutura"}),
    ("responder_faq", {"trecho": "E quem aprova o pedido?"}, CASOS["responder_faq"][0]),
    ("vincular_duplicado", {"trecho": "preciso de um monitor"}, CASOS["vincular_duplicado"][0]),
    ("encaminhar_time", {"alternativa": "Segurança"}, {"time": "Marketing"}),
    ("lancar_ferias", {"trecho": "12/01/2027 a 22/01/2027"}, CASOS["lancar_ferias"][0]),
])
def test_objecao_com_prova_devolve(tmp_path, acao, prova, parametros):
    corpo = "Preciso de acesso ao CRM." if acao == "registrar_chamado" else CASOS[acao][1].replace("11/01", "12/01")
    rev, _, _ = revisar(tmp_path, Modelo({"ok": False, **prova}), acao, parametros, corpo, exige=acao == "lancar_ferias")
    assert rev.decisao == "devolver"


def test_regras_em_codigo_nao_dependem_do_modelo(tmp_path):
    ok = Modelo({"ok": True})
    r = lambda i, *a, **k: revisar(tmp_path / str(i), ok, *a, **k)[0].decisao  # noqa: E731
    for i in range(4):
        (tmp_path / str(i)).mkdir()
    assert r(0, "registrar_chamado", {"tipo": "Novo equipamento", "campos": {"item": "x"}, "time": "Infraestrutura"}, "x") == "devolver"  # falta campo
    assert r(1, "registrar_chamado", {"tipo": "Acesso a sistema", "campos": {"sistema": "a", "justificativa": "b"}, "time": "Segurança"}, "x") == "devolver"  # sem OK humano
    assert r(2, "responder_faq", {"faq_id": "FAQ-06", "texto_resposta": "Uns 5 dias."}, "x") == "devolver"  # FAQ alterado
    assert r(3, "encaminhar_time", {"time": "Inexistente"}, "x") == "devolver"


def test_p1_nunca_passa_rebaixado_mas_uma_pessoa_nao_vira_p1(tmp_path):
    def decide(nome, corpo, alcance, impacto="P1", acao="abrir_incidente", crit="P2", par=None):
        (tmp_path / nome).mkdir()
        m = Modelo({"ok": True}, {"impacto": impacto, "alcance": alcance, "tipo_caso": "incidente"})
        return revisar(tmp_path / nome, m, acao, par or {"resumo": "x", "produto": "App"}, corpo, criticidade=crit)[0].decisao

    assert decide("a", "Muitos clientes não confirmam agendamento.", "muitos_clientes") == "devolver"
    assert decide("b", "Os clientes não confirmam agendamento.", "uma_pessoa") == "devolver"  # modelo errou o alcance: o texto segura
    dup = {"acao": "vincular_duplicado", "crit": None, "par": CASOS["vincular_duplicado"][0]}
    assert decide("c", "Meu notebook continua desligando sozinho.", "uma_pessoa", **dup) == "aprovar"
    assert decide("d", "O portal não abre para os clientes.", "muitos_clientes", **dup) == "devolver"
    assert decide("e", "O produto parou.", "uma_pessoa", impacto="P0") == "devolver"  # P0 nunca é rebaixado


def test_licao_so_de_correcao_que_deu_certo_e_sem_texto_do_modelo(tmp_path):
    rev, ctxrev, caso = revisar(tmp_path, Modelo({"ok": False, "alternativa": "Acesso a sistema", "trecho": "acesso ao CRM", "explicacao": "Fulano de Tal pediu"}),
                                "registrar_chamado", {"tipo": "Novo equipamento", "campos": {"item": "crm", "motivo": "acesso"}, "time": "Infraestrutura"}, "Preciso de acesso ao CRM. Fulano de Tal")
    assert rev.decisao == "devolver" and ctxrev.ctx.longa.todas() == []  # devolver, sozinho, não ensina nada
    ctxrev.ctx.llm = Modelo({"ok": True})
    p2 = Proposta(proposta_id="p-2", caso_id="c-0001", autor="triador", acao="registrar_chamado", exige_aprovacao_humana=True, motivo="m",
                  parametros={"tipo": "Acesso a sistema", "campos": {"sistema": "CRM", "justificativa": "Preciso de acesso"}, "time": "Segurança"})
    caso.propostas.append(p2.model_dump())
    asyncio.run(ctxrev._revisar(caso, p2))
    licoes = ctxrev.ctx.longa.todas()
    assert len(licoes) == 1 and "Acesso a sistema" in licoes[0]["licao"] and "Fulano" not in str(licoes)


def test_pesquisador_nao_repropoe_o_que_foi_recusado():
    caso = Caso(caso_id="c-1", rodada=1, evento_id="E1")
    caso.propostas = [{"proposta_id": "p-1", "acao": "responder_faq", "parametros": {"faq_id": "FAQ-06"}}]
    caso.revisoes = [{"proposta_id": "p-1", "decisao": "devolver", "problemas": ["o item do FAQ não responde a esta parte"]}]
    assert Pesquisador._recusados(caso, "responder_faq", "faq_id") == {"FAQ-06"}
