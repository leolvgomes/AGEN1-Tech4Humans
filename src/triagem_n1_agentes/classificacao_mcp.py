"""Classificação somente leitura dos e-mails novos disponíveis no MCP."""

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPError, streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, TextContent

from triagem_n1_agentes.agentes_ia import ErroAgenteIA, TriadorIA
from triagem_n1_agentes.configuracao import obter_configuracao
from triagem_n1_agentes.logs import configurar_logs
from triagem_n1_agentes.modelos import (
    AcaoProposta,
    CategoriaTriagem,
    Criticidade,
    DecisaoTriagem,
    NivelRiscoSeguranca,
)

logger = structlog.get_logger(__name__)
_AGENTE = "orquestrador"
_LIMITE_PAGINA = 100
_DADO_SENSIVEL = re.compile(
    r"\b(atestado|laudo|diagn[oó]stico|exame(?:\s+m[eé]dico)?|cpf|"
    r"dados?\s+de\s+sa[uú]de|credencial|phishing|golpe|vazamento|"
    r"acesso\s+indevido|informe\s+sua\s+senha|digite\s+sua\s+senha)\b",
    re.IGNORECASE,
)
_RISCO_SEGURANCA = re.compile(
    r"\b(phishing|golpe|vazamento|acesso\s+indevido|credencial)\b",
    re.IGNORECASE,
)
_DADO_PESSOAL_SENSIVEL = re.compile(
    r"\b(atestado|laudo|diagn[oó]stico|exame(?:\s+m[eé]dico)?|cpf|"
    r"dados?\s+de\s+sa[uú]de)\b",
    re.IGNORECASE,
)
_CREDENCIAL_EXPLICITA = re.compile(
    r"\b(senha|password|token|api[_ -]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_SENHA_EXPIRANDO = re.compile(
    r"\bsenha.{0,40}expir|\bexpir.{0,40}senha",
    re.IGNORECASE,
)
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_TELEFONE = re.compile(r"(?<!\d)(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?9?\d{4}[- ]?\d{4}(?!\d)")


class ErroClassificacaoMCP(Exception):
    """Indica erro ou resposta inválida durante a leitura do MCP."""


@dataclass(frozen=True)
class ResultadoClassificacao:
    """Resultado individual, incluindo falhas sem ocultar classificações válidas."""

    evento_id: str
    decisao: DecisaoTriagem | None = None
    erro: str | None = None


def _decodificar_resposta(resultado: CallToolResult, ferramenta: str) -> dict[str, Any]:
    if resultado.isError:
        detalhes = "\n".join(
            item.text for item in resultado.content if isinstance(item, TextContent)
        )
        raise ErroClassificacaoMCP(
            detalhes or f"A ferramenta MCP {ferramenta} retornou um erro."
        )

    dados = resultado.structuredContent
    if dados is None:
        textos = [
            item.text for item in resultado.content if isinstance(item, TextContent)
        ]
        if not textos:
            raise ErroClassificacaoMCP(
                f"A ferramenta MCP {ferramenta} não retornou conteúdo."
            )
        try:
            dados = json.loads(textos[0])
        except json.JSONDecodeError as erro:
            raise ErroClassificacaoMCP(
                f"A ferramenta MCP {ferramenta} retornou JSON inválido."
            ) from erro

    if not isinstance(dados, dict):
        raise ErroClassificacaoMCP(
            f"A ferramenta MCP {ferramenta} retornou um objeto inválido."
        )
    return dados


async def _chamar_ferramenta(
    sessao: ClientSession,
    nome: str,
    argumentos: dict[str, Any],
) -> dict[str, Any]:
    logger.info("mcp_tool_call_started", tool=nome, agent=_AGENTE)
    resultado = await sessao.call_tool(nome, argumentos)
    dados = _decodificar_resposta(resultado, nome)
    logger.info("mcp_tool_call_completed", tool=nome, agent=_AGENTE)
    return dados


async def _consultar_base(
    sessao: ClientSession,
    base: str,
) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    offset = 0
    while True:
        dados = await _chamar_ferramenta(
            sessao,
            "consultar",
            {
                "agente": _AGENTE,
                "motivo": f"Obter contexto autorizado da base {base} para triagem",
                "base": base,
                "limite": _LIMITE_PAGINA,
                "offset": offset,
            },
        )
        pagina = dados.get("registros")
        if not isinstance(pagina, list) or not all(
            isinstance(registro, dict) for registro in pagina
        ):
            raise ErroClassificacaoMCP(
                f"A consulta à base {base} retornou uma lista inválida."
            )
        registros.extend(pagina)
        if not dados.get("tem_mais", False):
            return registros
        if not pagina:
            raise ErroClassificacaoMCP(
                f"A consulta à base {base} indicou mais páginas sem registros."
            )
        offset += len(pagina)


def _contem_dado_sensivel(evento: dict[str, Any]) -> bool:
    texto = " ".join(
        str(evento.get(chave, ""))
        for chave in ("assunto", "corpo", "acoes")
    )
    return bool(
        _DADO_SENSIVEL.search(texto)
        or _CREDENCIAL_EXPLICITA.search(texto)
        or _SENHA_EXPIRANDO.search(texto)
        or _CPF.search(texto)
    )


def _sanitizar_valor(valor: Any) -> Any:
    if isinstance(valor, dict):
        chaves_pessoais = {"email", "nome", "solicitante", "aprovador"}
        return {
            chave: _sanitizar_valor(item)
            for chave, item in valor.items()
            if chave not in chaves_pessoais
        }
    if isinstance(valor, list):
        return [_sanitizar_valor(item) for item in valor]
    if isinstance(valor, str):
        if (
            _DADO_SENSIVEL.search(valor)
            or _CREDENCIAL_EXPLICITA.search(valor)
            or _SENHA_EXPIRANDO.search(valor)
            or _CPF.search(valor)
        ):
            return "[CONTEUDO SENSIVEL REMOVIDO]"
        texto = _CPF.sub("[CPF]", valor)
        texto = _TELEFONE.sub("[TELEFONE]", texto)
        return _EMAIL.sub("[EMAIL]", texto)
    return valor


def _preparar_evento_para_ia(evento: dict[str, Any]) -> dict[str, Any]:
    evento_seguro = {
        chave: valor
        for chave, valor in evento.items()
        if chave not in {"de", "nome", "acoes"}
    }
    nome = evento.get("nome")
    if isinstance(nome, str) and nome:
        for chave in ("assunto", "corpo"):
            texto = evento_seguro.get(chave)
            if isinstance(texto, str):
                evento_seguro[chave] = re.sub(
                    re.escape(nome),
                    "[NOME]",
                    texto,
                    flags=re.IGNORECASE,
                )
    remetente = evento.get("de")
    if isinstance(remetente, str) and "@" in remetente:
        evento_seguro["dominio_remetente"] = remetente.rsplit("@", 1)[1]
    return _sanitizar_valor(evento_seguro)


def _remetente_anonimizado(evento: dict[str, Any]) -> str | None:
    remetente = evento.get("de")
    if not isinstance(remetente, str) or "@" not in remetente:
        return None
    return remetente.rsplit("@", 1)[1]


def _decisao_revisao_humana(evento: dict[str, Any]) -> DecisaoTriagem:
    evento_id = str(evento.get("id", "desconhecido"))
    texto = " ".join(
        str(evento.get(chave, ""))
        for chave in ("assunto", "corpo", "acoes")
    )
    risco_seguranca = bool(
        _RISCO_SEGURANCA.search(texto)
        or _CREDENCIAL_EXPLICITA.search(texto)
        or _SENHA_EXPIRANDO.search(texto)
    )
    dado_pessoal_sensivel = bool(
        _DADO_PESSOAL_SENSIVEL.search(texto)
        or _CREDENCIAL_EXPLICITA.search(texto)
    )
    logger.info(
        "agent_call_skipped",
        agent="triador",
        event_id=evento_id,
        reason="sensitive_content_local_gate",
    )
    return DecisaoTriagem(
        evento=evento,
        categoria=(
            CategoriaTriagem.INCIDENTE
            if risco_seguranca
            else CategoriaTriagem.SOLICITACAO
        ),
        tipo_catalogo=None,
        criticidade=Criticidade.P3,
        faq_utilizada=None,
        campos_encontrados=[],
        campos_ausentes=[],
        possivel_duplicidade=False,
        risco_seguranca=(
            NivelRiscoSeguranca.ALTO
            if risco_seguranca
            else NivelRiscoSeguranca.NENHUM
        ),
        dado_sensivel_presente=dado_pessoal_sensivel,
        necessita_aprovacao=True,
        acao_proposta=(
            AcaoProposta.ESCALAR_INCIDENTE
            if risco_seguranca
            else AcaoProposta.ENCAMINHAR_APROVACAO
        ),
        justificativa=(
            "O conteúdo pode conter dado pessoal sensível ou credencial; "
            "não foi enviado ao modelo e requer revisão humana."
        ),
        confianca=0.95,
    )


async def classificar_emails_disponiveis(
    evento_ids: set[str] | None = None,
) -> list[ResultadoClassificacao]:
    """Classifica eventos com status novo sem marcar, responder ou atualizar."""
    configuracao = obter_configuracao()
    endereco = str(configuracao.mcp_url)

    async with streamable_http_client(endereco) as (leitura, escrita, _):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()
            eventos = await _consultar_base(sessao, "eventos")
            novos = [
                evento
                for evento in eventos
                if evento.get("status") == "novo" and evento.get("id")
            ]
            if evento_ids is not None:
                ids_disponiveis = {str(evento["id"]) for evento in novos}
                ids_ausentes = evento_ids - ids_disponiveis
                if ids_ausentes:
                    raise ErroClassificacaoMCP(
                        "Eventos solicitados não estão disponíveis com status novo: "
                        + ", ".join(sorted(ids_ausentes))
                    )
                novos = [
                    evento
                    for evento in novos
                    if str(evento["id"]) in evento_ids
                ]
            contexto: dict[str, Any] = {}
            for base in ("faq", "catalogo", "times", "chamados", "incidentes"):
                contexto[base] = await _consultar_base(sessao, base)
            contexto["eventos"] = [
                {
                    "id": evento.get("id"),
                    "dominio_remetente": _remetente_anonimizado(evento),
                    "assunto": evento.get("assunto"),
                    "status": evento.get("status"),
                    "responde_a": evento.get("responde_a"),
                }
                for evento in eventos
            ]
            contexto = _sanitizar_valor(contexto)
            emails = novos

    logger.info(
        "email_classification_started",
        pending_count=len(emails),
        agent="triador",
    )
    resultados: list[ResultadoClassificacao] = []
    triador: TriadorIA | None = None
    try:
        for indice, evento in enumerate(emails):
            evento_id = str(evento.get("id", "desconhecido"))
            if _contem_dado_sensivel(evento):
                resultados.append(
                    ResultadoClassificacao(
                        evento_id=evento_id,
                        decisao=_decisao_revisao_humana(evento),
                    )
                )
                continue

            if triador is None:
                triador = TriadorIA(configuracao)
            try:
                decisao = await triador.analisar(
                    _preparar_evento_para_ia(evento),
                    contexto,
                )
            except ErroAgenteIA as erro:
                resultados.append(
                    ResultadoClassificacao(
                        evento_id=evento_id,
                        erro=str(erro),
                    )
                )
                for restante in emails[indice + 1 :]:
                    restante_id = str(restante.get("id", "desconhecido"))
                    if _contem_dado_sensivel(restante):
                        resultados.append(
                            ResultadoClassificacao(
                                evento_id=restante_id,
                                decisao=_decisao_revisao_humana(restante),
                            )
                        )
                    else:
                        resultados.append(
                            ResultadoClassificacao(
                                evento_id=restante_id,
                                erro=(
                                    "Não processado após falha do agente no evento "
                                    f"{evento_id}."
                                ),
                            )
                        )
                break
            resultados.append(
                ResultadoClassificacao(evento_id=evento_id, decisao=decisao)
            )
    finally:
        if triador is not None:
            await triador.fechar()

    logger.info(
        "email_classification_completed",
        classified_count=sum(item.decisao is not None for item in resultados),
        failed_count=sum(item.erro is not None for item in resultados),
        agent="triador",
    )
    return resultados


def main() -> int:
    """Classifica e-mails novos e imprime somente os dados da decisão."""
    configurar_logs(obter_configuracao().nivel_log)
    try:
        resultados = asyncio.run(classificar_emails_disponiveis())
    except (
        httpx.HTTPError,
        StreamableHTTPError,
        McpError,
        ErroClassificacaoMCP,
        ErroAgenteIA,
        ValueError,
    ) as erro:
        logger.error(
            "email_classification_failed",
            error_type=type(erro).__name__,
        )
        print(f"Falha ao classificar e-mails: {erro}", file=sys.stderr)
        return 1

    falhas = 0
    for resultado in resultados:
        if resultado.decisao is None:
            falhas += 1
            print(
                json.dumps(
                    {"evento_id": resultado.evento_id, "erro": resultado.erro},
                    ensure_ascii=False,
                )
            )
            continue
        decisao = resultado.decisao
        print(
            json.dumps(
                {
                    "evento_id": decisao.evento.get("id"),
                    "categoria": decisao.categoria.value,
                    "tipo_catalogo": decisao.tipo_catalogo,
                    "criticidade": decisao.criticidade.value,
                    "risco_seguranca": decisao.risco_seguranca.value,
                    "dado_sensivel_presente": decisao.dado_sensivel_presente,
                    "necessita_aprovacao": decisao.necessita_aprovacao,
                    "acao_proposta": decisao.acao_proposta.value,
                    "campos_ausentes": decisao.campos_ausentes,
                    "justificativa": _sanitizar_valor(decisao.justificativa),
                    "confianca": decisao.confianca,
                },
                ensure_ascii=False,
            )
        )
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
