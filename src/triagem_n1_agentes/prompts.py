"""Carregamento centralizado das instruções versionadas dos agentes."""

from functools import lru_cache
from pathlib import Path


PASTA_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


@lru_cache
def carregar_prompt(nome: str) -> str:
    """Carrega um prompt conhecido sem aceitar caminhos arbitrários."""
    permitidos = {
        "ORQUESTRADOR",
        "TRIADOR",
        "REVISOR",
        "EXECUTOR",
        "ESCALACAO_HUMANA",
    }
    if nome not in permitidos:
        raise ValueError(f"Prompt desconhecido: {nome}")
    caminho = PASTA_PROMPTS / f"{nome}.md"
    return caminho.read_text(encoding="utf-8")

