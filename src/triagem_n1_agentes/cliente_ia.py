"""Cliente mínimo da IA fornecida pela organização do evento."""

import asyncio
import sys

from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from triagem_n1_agentes.configuracao import Configuracao, obter_configuracao


class ErroConexaoIA(Exception):
    """Falha segura ao consultar o gateway de IA."""


def normalizar_base_url(url: str) -> str:
    """Aceita a URL-base ou o endpoint completo de chat/completions."""
    base = url.rstrip("/")
    sufixo = "/chat/completions"
    if base.endswith(sufixo):
        base = base[: -len(sufixo)]
    return base


def criar_cliente(configuracao: Configuracao | None = None) -> AsyncOpenAI:
    """Cria o cliente sem registrar ou expor a credencial."""
    config = configuracao or obter_configuracao()
    if config.ai_api_key is None or config.ai_base_url is None:
        raise ValueError("AI_API_KEY e AI_BASE_URL precisam estar preenchidos.")
    return AsyncOpenAI(
        api_key=config.ai_api_key.get_secret_value(),
        base_url=normalizar_base_url(str(config.ai_base_url)),
        timeout=30,
        max_retries=1,
    )


async def testar_conexao(configuracao: Configuracao | None = None) -> bool:
    """Faz uma chamada curta e valida uma resposta controlada."""
    config = configuracao or obter_configuracao()
    if not config.ai_model:
        raise ValueError("AI_MODEL precisa estar preenchido.")
    cliente = criar_cliente(config)
    try:
        resposta = await cliente.chat.completions.create(
            model=config.ai_model,
            messages=[
                {
                    "role": "system",
                    "content": "Responda somente com a palavra CONEXAO_OK.",
                },
                {"role": "user", "content": "Teste de conectividade."},
            ],
            temperature=0,
            max_tokens=10,
        )
    except APIStatusError as erro:
        raise ErroConexaoIA(
            f"O gateway respondeu com HTTP {erro.status_code}."
        ) from erro
    except APIConnectionError as erro:
        raise ErroConexaoIA("Não foi possível alcançar o gateway de IA.") from erro
    finally:
        await cliente.close()

    conteudo = resposta.choices[0].message.content or ""
    return conteudo.strip().upper() == "CONEXAO_OK"


def main() -> int:
    """Executa o diagnóstico sem exibir chave, URL completa ou resposta bruta."""
    try:
        conectado = asyncio.run(testar_conexao())
    except (ErroConexaoIA, ValueError) as erro:
        print(f"Falha no teste da IA: {erro}", file=sys.stderr)
        return 1

    if not conectado:
        print("A IA respondeu, mas não confirmou o teste controlado.", file=sys.stderr)
        return 1

    print("Conexão com a IA confirmada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

