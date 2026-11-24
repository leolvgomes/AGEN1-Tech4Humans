"""Testes unitários (rodam sem servidor e sem chave de IA): python -m pytest -q"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from src.config import Config
from src.contratos import ClassificacaoIndependente, Envelope, Proposta
from src.log import Log
from src.mcp_client import ClienteMCP, ErroMCP, FerramentasAgente, PermissaoNegada
from src.memoria import Banco, MemoriaCurta, MemoriaLonga
from src.util import mascarar, normalizar_assunto, parse_data, tem_dado_sensivel


def test_mascarar_dados_sensiveis():  # T11
    texto = "CPF 123.456.789-09, CID J11, agência 1234 conta 98765-4, senha: abc123"
    m = mascarar(texto)
    assert "123.456.789-09" not in m and "J11" not in m and "abc123" not in m and "98765" not in m
    assert tem_dado_sensivel(texto)
    assert not tem_dado_sensivel("O cliente é o da conta 31877 no App Agenda")  # conta de cliente não é dado bancário
    assert not tem_dado_sensivel("Como troco a minha senha da rede?")


def test_assunto_e_datas():
    assert normalizar_assunto("RE: Fwd: Férias Fevereiro") == "ferias fevereiro"
    assert parse_data("11/01/2027").isoformat() == "2027-01-11"
    assert parse_data("2027-01-22").isoformat() == "2027-01-22"


def test_envelope_rota_invalida():
    with pytest.raises(Exception):
        Envelope(de="triador", para="executor", tipo="EXECUTAR", caso_id="c-1")  # só o Revisor manda EXECUTAR
    with pytest.raises(Exception):
        Envelope(de="triador", para="revisor", tipo="PROPOSTA", caso_id="c-1", payload={"acao": "inventada"})


def _cliente(tmp_path: pathlib.Path) -> ClienteMCP:
    c = ClienteMCP("http://x/mcp", 15, Log(tmp_path, console=False))
    props = {"agente": {}, "motivo": {}, "base": {}, "dados": {}, "evento_id": {}}
    c.ferramentas = {
        "registrar": {"name": "registrar", "inputSchema": {"properties": props, "required": ["agente", "base", "dados"]}, "annotations": {"readOnlyHint": False}},
        "consultar": {"name": "consultar", "inputSchema": {"properties": {**props, "filtro": {}}, "required": ["agente", "base"]}, "annotations": {"readOnlyHint": True}},
    }
    return c


def test_permissoes_bloqueiam_antes_do_servidor(tmp_path):
    c = _cliente(tmp_path)
    ferr = FerramentasAgente(c, "triador", lambda: 1)
    with pytest.raises(PermissaoNegada):
        asyncio.run(ferr.chamar("registrar", "tentar escrever", base="chamados", dados={}))


def test_parametro_desconhecido_falha_antes(tmp_path):
    c = _cliente(tmp_path)
    with pytest.raises(ErroMCP):
        asyncio.run(c.chamar("executor", "registrar", {"base": "x", "dados": {"a": 1}, "inventado": 1}, motivo="m"))


def test_503_repete_e_504_verifica_sem_duplicar(tmp_path, monkeypatch):  # T15
    c = _cliente(tmp_path)
    respostas = [{"status": "erro", "codigo": 503}, {"status": "erro", "codigo": 504}]
    chamadas = []

    async def falsa(ferramenta, args, timeout):
        chamadas.append(ferramenta)
        return respostas.pop(0) if respostas else {"status": "ok", "registro": {"id": "CH-1"}}

    async def sem_espera(_):
        return None

    monkeypatch.setattr(c, "_chamar_uma_vez", falsa)
    monkeypatch.setattr(asyncio, "sleep", sem_espera)
    verificados = []

    async def ja_foi_feito():
        verificados.append(1)
        return {"registro": {"id": "CH-1"}}  # o 504 tinha feito a ação: não pode repetir

    r = asyncio.run(c.chamar("executor", "registrar", {"base": "chamados", "dados": {"a": 1}}, motivo="m", verificar=ja_foi_feito))
    assert r["verificado"] and len(chamadas) == 2 and verificados == [1]


def test_idempotencia_de_evento_e_acao(tmp_path):
    curta = MemoriaCurta(Banco(tmp_path / "t.db"))
    assert curta.marcar_visto(1, "PED-001", None) is True
    assert curta.marcar_visto(1, "PED-001", None) is False  # um evento nunca é processado duas vezes
    assert curta.marcar_visto(2, "PED-001", None) is True  # servidor reiniciado: nova rodada
    curta.registrar_acao(1, "PED-001:registrar_chamado", {"id": "CH-1"})
    assert curta.acao_feita(1, "PED-001:registrar_chamado") == {"id": "CH-1"}


def test_memoria_longa_so_vale_confirmada(tmp_path):
    longa = MemoriaLonga(Banco(tmp_path / "t.db"))
    longa.observar("urgencia_falsa", "urgente", "'urgente' costuma vir sem impacto", "c-1")
    assert longa.ativas() == []
    longa.observar("urgencia_falsa", "urgente", "'urgente' costuma vir sem impacto", "c-2")
    assert len(longa.ativas()) == 1
    longa.observar("correcao_revisor", "abrir_incidente: criticidade", "Revisor já corrigiu", "c-3")
    assert len(longa.ativas()) == 2  # correção do Revisor vale na hora


def test_revisor_devolve_criticidade_menor(tmp_path):  # T14
    from src.agentes import Revisor
    from src.agentes.base import Bases, Contexto

    class Falso:
        log = Log(tmp_path, console=False)

    ctx = Contexto(cfg=Config(), log=Falso.log, banco=Banco(tmp_path / "t.db"), curta=None, longa=None, mcp=_cliente(tmp_path), llm=None, bus=None)  # type: ignore[arg-type]
    rev = Revisor(ctx)
    from src.contratos import Caso

    caso = Caso(caso_id="c-1", rodada=1, evento_id="E1")
    p = Proposta(proposta_id="p-1", caso_id="c-1", autor="triador", acao="abrir_incidente", criticidade="P2",
                 parametros={"resumo": "x", "produto": "App Agenda"}, motivo="m")
    problemas = rev._checklist(caso, p, ClassificacaoIndependente(impacto="P1", tipo_caso="incidente"))
    assert any("menor que a do revisor" in x for x in problemas)
    p2 = p.model_copy(update={"criticidade": "P1", "parametros": {"resumo": "x", "produto": "App", "escalar_na_hora": True}})
    assert rev._checklist(caso, p2, ClassificacaoIndependente(impacto="P1", tipo_caso="incidente")) == []
    seg = rev._checklist(caso, p2, ClassificacaoIndependente(seguranca=True, impacto="P1", tipo_caso="incidente"))
    assert any("segurança" in x for x in seg)
