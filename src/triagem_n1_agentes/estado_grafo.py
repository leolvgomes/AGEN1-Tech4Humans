"""Estado bruto compartilhado pelos nós do LangGraph."""

from typing import Any, TypedDict

from triagem_n1_agentes.modelos import DecisaoTriagem, RevisaoTriagem


class EstadoTriagem(TypedDict, total=False):
    evento: dict[str, Any]
    contexto: dict[str, Any]
    decisao: DecisaoTriagem
    revisao: RevisaoTriagem
    exige_humano: bool
    resultado_execucao: dict[str, Any]
    erro: str | None

