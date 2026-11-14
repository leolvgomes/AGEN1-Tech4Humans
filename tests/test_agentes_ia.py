import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr
from structlog.testing import capture_logs

from triagem_n1_agentes.agentes_ia import TriadorIA
from triagem_n1_agentes.configuracao import Configuracao
from triagem_n1_agentes.modelos import AcaoProposta, Criticidade


def test_triador_valida_json_e_preserva_evento_original():
    configuracao = Configuracao(
        AI_API_KEY=SecretStr("teste"),
        AI_BASE_URL="https://gateway.exemplo/v1",
        AI_MODEL="modelo-teste",
        _env_file=None,
    )
    evento = {"id": "MAN-123", "assunto": "VPN", "corpo": "Como acesso?"}
    decisao_modelo = {
        "evento": {"id": "ALTERADO-PELO-MODELO"},
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
        "justificativa": "Coberto pela FAQ-01.",
        "confianca": 0.99,
    }
    resposta = MagicMock()
    resposta.choices = [
        MagicMock(message=MagicMock(content=json.dumps(decisao_modelo)))
    ]
    cliente = MagicMock()
    cliente.chat.completions.create = AsyncMock(return_value=resposta)
    triador = TriadorIA(configuracao, cliente)

    with capture_logs() as logs:
        decisao = asyncio.run(triador.analisar(evento, {"faq": []}))

    assert decisao.evento == evento
    assert decisao.criticidade is Criticidade.P4
    assert decisao.acao_proposta is AcaoProposta.RESPONDER_FAQ
    assert [log["event"] for log in logs] == [
        "agent_call_started",
        "agent_call_completed",
    ]
    assert all(log["agent"] == "triador" for log in logs)
    assert all(log["event_id"] == "MAN-123" for log in logs)
    assert "Como acesso?" not in str(logs)

