"""Testes do fluxo somente leitura de classificação de e-mails."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from mcp.types import TextContent

from triagem_n1_agentes import classificacao_mcp
from triagem_n1_agentes.modelos import DecisaoTriagem


def _resultado(dados: dict) -> SimpleNamespace:
    return SimpleNamespace(
        isError=False,
        structuredContent=None,
        content=[TextContent(type="text", text=json.dumps(dados))],
    )


def test_classifica_apenas_eventos_novos_sem_chamar_ferramentas_de_escrita(
    monkeypatch,
) -> None:
    chamadas = []
    agentes_chamados = []
    dados_decisao = {
        "evento": {"id": "PED-001"},
        "categoria": "duvida",
        "tipo_catalogo": None,
        "criticidade": "P4",
        "faq_utilizada": "FAQ-01",
        "campos_encontrados": [],
        "campos_ausentes": [],
        "possivel_duplicidade": False,
        "risco_seguranca": "nenhum",
        "dado_sensivel_presente": False,
        "necessita_aprovacao": False,
        "acao_proposta": "responder_faq",
        "justificativa": "A dúvida corresponde a uma FAQ.",
        "confianca": 0.9,
    }

    class SessaoFalsa:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def initialize(self):
            return None

        async def call_tool(self, nome, argumentos):
            chamadas.append((nome, argumentos))
            if nome == "consultar" and argumentos["base"] == "eventos":
                return _resultado(
                    {
                        "registros": [
                            {
                                "id": "PED-001",
                                "status": "novo",
                                "assunto": "VPN",
                                "corpo": "Como acesso?",
                            },
                            {
                                "id": "PED-003",
                                "status": "novo",
                                "assunto": "Atestado médico",
                                "corpo": "Segue o laudo médico.",
                            },
                            {"id": "PED-002", "status": "respondido"},
                        ],
                        "tem_mais": False,
                    }
                )
            if nome == "consultar":
                return _resultado({"registros": [], "tem_mais": False})
            raise AssertionError(f"Ferramenta inesperada: {nome}")

    @asynccontextmanager
    async def transporte_falso(_url):
        yield object(), object(), lambda: None

    class TriadorFalso:
        def __init__(self, _configuracao):
            pass

        async def analisar(self, evento, contexto):
            agentes_chamados.append(evento["id"])
            assert "nome" not in evento
            assert "faq" in contexto
            return DecisaoTriagem.model_validate(dados_decisao)

        async def fechar(self):
            return None

    monkeypatch.setattr(classificacao_mcp, "obter_configuracao", lambda: SimpleNamespace(
        mcp_url="http://localhost:8765/mcp",
        nivel_log="INFO",
    ))
    monkeypatch.setattr(
        classificacao_mcp, "streamable_http_client", transporte_falso
    )
    monkeypatch.setattr(classificacao_mcp, "ClientSession", lambda *_: SessaoFalsa())
    monkeypatch.setattr(classificacao_mcp, "TriadorIA", TriadorFalso)

    decisoes = asyncio.run(classificacao_mcp.classificar_emails_disponiveis())

    assert [resultado.evento_id for resultado in decisoes] == ["PED-001", "PED-003"]
    assert decisoes[0].decisao is not None
    assert decisoes[1].decisao is not None
    assert decisoes[1].decisao.dado_sensivel_presente is True
    assert agentes_chamados == ["PED-001"]
    assert {nome for nome, _ in chamadas} == {
        "consultar",
    }
    assert all(
        argumentos["agente"] == "orquestrador" for _, argumentos in chamadas
    )


def test_dado_sensivel_e_identificado_para_revisao_humana() -> None:
    evento = {
        "id": "PED-019",
        "assunto": "Atestado médico",
        "corpo": "Segue meu laudo médico.",
        "de": "pessoa@exemplo.com",
    }

    assert classificacao_mcp._contem_dado_sensivel(evento)
    decisao = classificacao_mcp._decisao_revisao_humana(evento)

    assert decisao.dado_sensivel_presente is True
    assert decisao.necessita_aprovacao is True
    assert decisao.acao_proposta.value == "encaminhar_aprovacao"


def test_sanitiza_identificadores_pessoais_antes_da_ia() -> None:
    evento = {
        "id": "PED-021",
        "de": "marina.alves@t4h.exemplo",
        "nome": "Marina Alves",
        "assunto": "Ajuda Marina Alves",
        "corpo": "Fale comigo em marina.alves@t4h.exemplo, CPF 123.456.789-00.",
    }

    preparado = classificacao_mcp._preparar_evento_para_ia(evento)

    assert preparado["dominio_remetente"] == "t4h.exemplo"
    assert preparado["assunto"] == "Ajuda [NOME]"
    assert "[EMAIL]" in preparado["corpo"]
    assert "[CPF]" in preparado["corpo"]
    assert "Marina Alves" not in str(preparado)
