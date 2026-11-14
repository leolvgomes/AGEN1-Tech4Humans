"""Testes básicos da estrutura inicial do projeto."""

from pathlib import Path

from triagem_n1_agentes.banco import conectar
from triagem_n1_agentes.configuracao import Configuracao
from triagem_n1_agentes.modelos import Solicitacao, StatusSolicitacao


def test_configuracao_padrao_e_url_mcp() -> None:
    configuracao = Configuracao(_env_file=None)

    assert str(configuracao.mcp_url) == "http://localhost:8765/mcp"


def test_configuracao_carrega_variaveis_de_ambiente(monkeypatch) -> None:
    monkeypatch.setenv("TRIAGEM_NIVEL_LOG", "DEBUG")
    configuracao = Configuracao(_env_file=None)

    assert configuracao.nivel_log == "DEBUG"


def test_modelo_solicitacao_tem_estado_inicial() -> None:
    solicitacao = Solicitacao(descricao="Solicitação de teste")

    assert solicitacao.status is StatusSolicitacao.RECEBIDA
    assert solicitacao.id is not None


def test_conexao_sqlite_cria_pasta_temporaria(tmp_path: Path) -> None:
    caminho = tmp_path / "dados" / "triagem.db"

    with conectar(caminho) as conexao:
        conexao.execute("SELECT 1")

    assert caminho.is_file()

