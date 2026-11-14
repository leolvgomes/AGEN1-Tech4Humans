from pathlib import Path


PROMPTS = {
    "ORQUESTRADOR.md",
    "TRIADOR.md",
    "REVISOR.md",
    "EXECUTOR.md",
    "ESCALACAO_HUMANA.md",
}


def test_prompts_dos_agentes_existem_e_nao_estao_vazios():
    pasta = Path(__file__).parents[1] / "prompts"
    for nome in PROMPTS:
        conteudo = (pasta / nome).read_text(encoding="utf-8")
        assert len(conteudo.strip()) > 500


def test_orquestrador_exige_revisao_e_idempotencia():
    conteudo = (
        Path(__file__).parents[1] / "prompts" / "ORQUESTRADOR.md"
    ).read_text(encoding="utf-8")
    assert "Nunca pule o Revisor" in conteudo
    assert "resultado incerto" in conteudo

