"""Implementações dos papéis inteligentes do fluxo de Triagem N1."""

import asyncio
import json
import sys
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import ValidationError

from triagem_n1_agentes.cliente_ia import criar_cliente
from triagem_n1_agentes.configuracao import Configuracao, obter_configuracao
from triagem_n1_agentes.modelos import DecisaoTriagem
from triagem_n1_agentes.prompts import carregar_prompt


class ErroAgenteIA(Exception):
    """Resposta inválida ou falha de comunicação de um agente inteligente."""


class TriadorIA:
    """Propõe uma decisão estruturada, sem executar ferramentas."""

    def __init__(
        self,
        configuracao: Configuracao | None = None,
        cliente: AsyncOpenAI | None = None,
    ) -> None:
        self.configuracao = configuracao or obter_configuracao()
        self.cliente = cliente or criar_cliente(self.configuracao)
        self._gerencia_cliente = cliente is None

    async def fechar(self) -> None:
        if self._gerencia_cliente:
            await self.cliente.close()

    async def analisar(
        self,
        evento: dict[str, Any],
        contexto: dict[str, Any],
    ) -> DecisaoTriagem:
        if not self.configuracao.ai_model:
            raise ErroAgenteIA("AI_MODEL não está configurado.")

        entrada = json.dumps(
            {"evento": evento, "contexto_autorizado": contexto},
            ensure_ascii=False,
            default=str,
        )
        try:
            resposta = await self.cliente.chat.completions.create(
                model=self.configuracao.ai_model,
                messages=[
                    {"role": "system", "content": carregar_prompt("TRIADOR")},
                    {
                        "role": "user",
                        "content": (
                            "Analise o evento usando somente o contexto autorizado. "
                            "Devolva exclusivamente o JSON solicitado.\n\n" + entrada
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=1200,
            )
        except APIStatusError as erro:
            raise ErroAgenteIA(
                f"O gateway respondeu com HTTP {erro.status_code}."
            ) from erro
        except APIConnectionError as erro:
            raise ErroAgenteIA("Falha de conexão com o gateway.") from erro

        conteudo = resposta.choices[0].message.content or ""
        try:
            decisao = DecisaoTriagem.model_validate_json(conteudo)
        except ValidationError as erro:
            raise ErroAgenteIA(
                "O Triador não devolveu uma decisão no formato esperado."
            ) from erro

        # O evento original sempre prevalece sobre qualquer cópia devolvida pelo modelo.
        return decisao.model_copy(update={"evento": evento})


async def _demonstrar_triador() -> DecisaoTriagem:
    evento = {
        "id": "DEMO-001",
        "de": "marina.alves@t4h.exemplo",
        "assunto": "Dúvida sobre VPN",
        "corpo": "Peguei um notebook novo. Como faço para entrar na VPN de casa?",
    }
    contexto = {
        "faq": [
            {
                "id": "FAQ-01",
                "pergunta": "Como me conecto à VPN para trabalhar de fora do escritório?",
                "resposta": (
                    "Instale o cliente de VPN pela Central de Software do notebook "
                    "e entre com seu usuário e senha da rede."
                ),
            }
        ],
        "catalogo": [],
        "chamados": [],
        "incidentes": [],
    }
    triador = TriadorIA()
    try:
        return await triador.analisar(evento, contexto)
    finally:
        await triador.fechar()


def main() -> int:
    """Testa o Triador real com dados fictícios, sem consumir evento MCP."""
    try:
        decisao = asyncio.run(_demonstrar_triador())
    except ErroAgenteIA as erro:
        print(f"Falha no Triador: {erro}", file=sys.stderr)
        return 1

    print("Triador conectado e resposta estruturada validada:")
    print(decisao.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

