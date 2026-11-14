"""Fila local persistente para aprovações humanas de eventos MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from triagem_n1_agentes.banco import conectar
from triagem_n1_agentes.configuracao import obter_configuracao

logger = structlog.get_logger(__name__)


class TarefaAprovacao(BaseModel):
    evento_id: str
    status: str
    criada_em: str
    payload: dict[str, Any]
    decisao: Literal["aprovar", "rejeitar"] | None = None
    decidido_por: str | None = None
    motivo_decisao: str | None = None


class FilaAprovacaoHumana:
    """Armazena o estado mínimo necessário para pausar e retomar um evento."""

    def __init__(self, caminho: Path | None = None) -> None:
        self.caminho = caminho or obter_configuracao().banco_caminho
        with closing(conectar(self.caminho)) as conexao:
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS aprovacoes_humanas (
                    evento_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    criada_em TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    decisao TEXT,
                    decidido_por TEXT,
                    motivo_decisao TEXT,
                    atualizada_em TEXT NOT NULL
                )
                """
            )

    def registrar_pendente(self, evento_id: str, payload: dict[str, Any]) -> TarefaAprovacao:
        agora = datetime.now(timezone.utc).isoformat()
        with closing(conectar(self.caminho)) as conexao:
            conexao.execute(
                """
                INSERT OR IGNORE INTO aprovacoes_humanas
                    (evento_id, status, criada_em, payload_json, atualizada_em)
                VALUES (?, 'PENDENTE', ?, ?, ?)
                """,
                (
                    evento_id,
                    agora,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    agora,
                ),
            )
            conexao.commit()
        tarefa = self.obter(evento_id)
        if tarefa is None:
            raise RuntimeError(f"Não foi possível persistir a aprovação {evento_id}.")
        return tarefa

    def obter(self, evento_id: str) -> TarefaAprovacao | None:
        with closing(conectar(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row
            linha = conexao.execute(
                "SELECT * FROM aprovacoes_humanas WHERE evento_id = ?",
                (evento_id,),
            ).fetchone()
        return self._mapear(linha) if linha else None

    def listar_pendentes(self) -> list[TarefaAprovacao]:
        with closing(conectar(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row
            linhas = conexao.execute(
                "SELECT * FROM aprovacoes_humanas WHERE status = 'PENDENTE' "
                "ORDER BY criada_em"
            ).fetchall()
        return [self._mapear(linha) for linha in linhas]

    def decidir(
        self,
        evento_id: str,
        decisao: Literal["aprovar", "rejeitar"],
        decidido_por: str,
        motivo: str,
    ) -> TarefaAprovacao:
        if not decidido_por.strip() or not motivo.strip():
            raise ValueError("Informe quem decidiu e o motivo da decisão.")
        with closing(conectar(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row
            conexao.execute("BEGIN IMMEDIATE")
            linha = conexao.execute(
                "SELECT * FROM aprovacoes_humanas WHERE evento_id = ?",
                (evento_id,),
            ).fetchone()
            if linha is None:
                raise ValueError(f"Não existe aprovação pendente para {evento_id}.")
            tarefa = self._mapear(linha)
            if (
                tarefa.status == "APROVADA"
                and decisao == "aprovar"
                and tarefa.decidido_por == decidido_por.strip()
                and tarefa.motivo_decisao == motivo.strip()
            ):
                conexao.rollback()
                return tarefa
            if tarefa.status != "PENDENTE":
                raise ValueError(
                    f"A aprovação {evento_id} já foi decidida: {tarefa.status}."
                )
            if decisao == "aprovar":
                revisao = tarefa.payload.get("revisao", {})
                if not revisao.get("aprovado") or not revisao.get("acao_confirmada"):
                    raise ValueError(
                        "O Revisor não aprovou uma ação executável; a decisão humana "
                        "não pode liberar o Executor."
                    )
            agora = datetime.now(timezone.utc).isoformat()
            conexao.execute(
                """
                UPDATE aprovacoes_humanas
                SET status = ?, decisao = ?, decidido_por = ?, motivo_decisao = ?,
                    atualizada_em = ?
                WHERE evento_id = ? AND status = 'PENDENTE'
                """,
                (
                    "APROVADA" if decisao == "aprovar" else "REJEITADA",
                    decisao,
                    decidido_por.strip(),
                    motivo.strip(),
                    agora,
                    evento_id,
                ),
            )
            conexao.commit()
        resultado = self.obter(evento_id)
        if resultado is None:
            raise RuntimeError(f"A aprovação {evento_id} desapareceu da fila.")
        return resultado

    def reivindicar_execucao(self, evento_id: str) -> TarefaAprovacao:
        with closing(conectar(self.caminho)) as conexao:
            conexao.row_factory = sqlite3.Row
            conexao.execute("BEGIN IMMEDIATE")
            atualizada = conexao.execute(
                """
                UPDATE aprovacoes_humanas
                SET status = 'EM_EXECUCAO', atualizada_em = ?
                WHERE evento_id = ? AND status = 'APROVADA'
                """,
                (datetime.now(timezone.utc).isoformat(), evento_id),
            )
            if atualizada.rowcount != 1:
                conexao.rollback()
                raise ValueError(
                    f"A aprovação {evento_id} não está liberada para execução."
                )
            conexao.commit()
        tarefa = self.obter(evento_id)
        if tarefa is None:
            raise RuntimeError(f"A aprovação {evento_id} desapareceu da fila.")
        return tarefa

    def finalizar_execucao(self, evento_id: str, sucesso: bool) -> None:
        with closing(conectar(self.caminho)) as conexao:
            atualizada = conexao.execute(
                """
                UPDATE aprovacoes_humanas
                SET status = ?, atualizada_em = ?
                WHERE evento_id = ? AND status = 'EM_EXECUCAO'
                """,
                (
                    "CONCLUIDA" if sucesso else "ERRO_EXECUCAO",
                    datetime.now(timezone.utc).isoformat(),
                    evento_id,
                ),
            )
            if atualizada.rowcount != 1:
                raise ValueError(f"A aprovação {evento_id} não estava em execução.")
            conexao.commit()

    @staticmethod
    def _mapear(linha: sqlite3.Row) -> TarefaAprovacao:
        return TarefaAprovacao(
            evento_id=linha["evento_id"],
            status=linha["status"],
            criada_em=linha["criada_em"],
            payload=json.loads(linha["payload_json"]),
            decisao=linha["decisao"],
            decidido_por=linha["decidido_por"],
            motivo_decisao=linha["motivo_decisao"],
        )


async def _decidir_e_continuar(
    evento_id: str,
    decisao: Literal["aprovar", "rejeitar"],
    decidido_por: str,
    motivo: str,
) -> dict[str, Any]:
    from triagem_n1_agentes.cliente_mcp import ClienteMCP, buscar_contexto_evento
    from triagem_n1_agentes.executor_mcp import executar_aprovado
    from triagem_n1_agentes.modelos import DecisaoTriagem, RevisaoTriagem

    fila = FilaAprovacaoHumana()
    tarefa = fila.decidir(evento_id, decisao, decidido_por, motivo)
    async with ClienteMCP(str(obter_configuracao().mcp_url)) as cliente:
        await cliente.registrar_conversa(
            agente="orquestrador",
            de="humano",
            para="orquestrador",
            mensagem=(
                f"Evento {evento_id}: {decisao} por {decidido_por}. Motivo: {motivo}"
            ),
        )
        if decisao == "rejeitar":
            return {"evento_id": evento_id, "status": "REJEITADA"}

        payload = tarefa.payload
        evento = payload["evento"]
        contexto = await buscar_contexto_evento(cliente, evento)
        decisao_triagem = DecisaoTriagem.model_validate(payload["decisao"])
        revisao = RevisaoTriagem.model_validate(payload["revisao"])
        tarefa = fila.reivindicar_execucao(evento_id)
        try:
            resultado = await executar_aprovado(
                cliente,
                evento,
                contexto,
                decisao_triagem,
                revisao,
                aprovacao_humana={
                    "aprovado": True,
                    "evento_id": evento_id,
                    "decidido_por": tarefa.decidido_por,
                    "motivo": tarefa.motivo_decisao,
                },
            )
        except Exception:
            fila.finalizar_execucao(evento_id, sucesso=False)
            raise
        fila.finalizar_execucao(evento_id, sucesso=True)
        retorno_execucao = resultado.get("retorno")
        captura = (
            retorno_execucao.get("captura")
            if isinstance(retorno_execucao, dict)
            else None
        )
        try:
            await cliente.registrar_conversa(
                agente="executor",
                de="executor",
                para="orquestrador",
                mensagem=(
                    f"Evento {evento_id}: computer use no legado retornou "
                    f"status={resultado.get('status')}; "
                    f"captura={captura or 'n/a'}"
                ),
            )
        except Exception as erro:
            logger.warning(
                "legacy_executor_conversation_log_failed",
                event_id=evento_id,
                error_type=type(erro).__name__,
            )
        return {"evento_id": evento_id, "status": "CONCLUIDA", "execucao": resultado}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consulta e decide aprovações humanas do fluxo de triagem."
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)
    subparsers.add_parser("listar", help="Lista as aprovações pendentes.")
    decidir = subparsers.add_parser("decidir", help="Aprova ou rejeita um evento.")
    decidir.add_argument("--evento-id", required=True)
    decidir.add_argument("--decisao", choices=("aprovar", "rejeitar"), required=True)
    decidir.add_argument("--aprovador", required=True)
    decidir.add_argument("--motivo", required=True)
    argumentos = parser.parse_args()

    try:
        fila = FilaAprovacaoHumana()
        if argumentos.comando == "listar":
            pendencias = []
            for tarefa in fila.listar_pendentes():
                decisao = tarefa.payload.get("decisao", {})
                revisao = tarefa.payload.get("revisao", {})
                pendencias.append(
                    {
                        "evento_id": tarefa.evento_id,
                        "status": tarefa.status,
                        "criada_em": tarefa.criada_em,
                        "criticidade": decisao.get("criticidade"),
                        "acao": revisao.get("acao_confirmada"),
                    }
                )
            print(
                json.dumps(
                    pendencias,
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        resultado = asyncio.run(
            _decidir_e_continuar(
                argumentos.evento_id,
                argumentos.decisao,
                argumentos.aprovador,
                argumentos.motivo,
            )
        )
    except Exception as erro:
        parser.exit(1, f"Falha ao processar aprovação: {erro}\n")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
