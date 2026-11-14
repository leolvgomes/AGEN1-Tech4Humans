"""Máquina de estados persistente para orquestrar eventos."""

import sqlite3
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from triagem_n1_agentes.banco import conectar
from triagem_n1_agentes.configuracao import obter_configuracao
from triagem_n1_agentes.modelos import (
    EstadoOrquestracao,
    ResultadoExecucaoEvento,
    TransicaoOrquestracao,
)

T = TypeVar("T")


class ErroOrquestrador(Exception):
    """Erro base da máquina de estados."""


class EventoNaoEncontrado(ErroOrquestrador):
    """O identificador do evento não está registrado."""


class TransicaoInvalida(ErroOrquestrador):
    """A transição solicitada não é permitida pelo fluxo."""


class EventoJaExecutado(ErroOrquestrador):
    """O evento já teve sua execução iniciada e não pode ser repetido."""


class FalhaRecuperavel(Exception):
    """Falha transitória que deve ser registrada sem parar o lote."""


_TRANSICOES_PERMITIDAS: dict[
    EstadoOrquestracao, set[EstadoOrquestracao]
] = {
    EstadoOrquestracao.RECEBIDO: {
        EstadoOrquestracao.EM_ANALISE,
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.EM_ANALISE: {
        EstadoOrquestracao.AGUARDANDO_REVISAO,
        EstadoOrquestracao.APROVADO,
        EstadoOrquestracao.AGUARDANDO_HUMANO,
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.AGUARDANDO_REVISAO: {
        EstadoOrquestracao.EM_ANALISE,
        EstadoOrquestracao.APROVADO,
        EstadoOrquestracao.AGUARDANDO_HUMANO,
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.APROVADO: {
        EstadoOrquestracao.AGUARDANDO_HUMANO,
        EstadoOrquestracao.EM_EXECUCAO,
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.AGUARDANDO_HUMANO: {
        EstadoOrquestracao.EM_ANALISE,
        EstadoOrquestracao.APROVADO,
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.EM_EXECUCAO: {
        EstadoOrquestracao.CONCLUIDO,
        EstadoOrquestracao.ERRO_RECUPERAVEL,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.ERRO_RECUPERAVEL: {
        EstadoOrquestracao.EM_ANALISE,
        EstadoOrquestracao.ERRO_FINAL,
    },
    EstadoOrquestracao.CONCLUIDO: set(),
    EstadoOrquestracao.ERRO_FINAL: set(),
}


class Orquestrador:
    """Persiste estados e histórico, e reivindica cada execução uma única vez."""

    def __init__(self, caminho_banco: Path | None = None) -> None:
        self._caminho_banco = (
            caminho_banco or obter_configuracao().banco_caminho
        )
        self._criar_tabelas()

    def _abrir_conexao(self) -> sqlite3.Connection:
        conexao = conectar(self._caminho_banco)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
        return conexao

    @contextmanager
    def _transacao(self) -> Iterator[sqlite3.Connection]:
        with closing(self._abrir_conexao()) as conexao:
            conexao.execute("BEGIN IMMEDIATE")
            try:
                yield conexao
            except BaseException:
                conexao.rollback()
                raise
            else:
                conexao.commit()

    def _criar_tabelas(self) -> None:
        with closing(self._abrir_conexao()) as conexao:
            conexao.executescript(
                """
                CREATE TABLE IF NOT EXISTS eventos_orquestracao (
                    evento_id TEXT PRIMARY KEY,
                    estado TEXT NOT NULL,
                    execucao_iniciada INTEGER NOT NULL DEFAULT 0
                        CHECK (execucao_iniciada IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS historico_transicoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evento_id TEXT NOT NULL
                        REFERENCES eventos_orquestracao(evento_id),
                    estado_anterior TEXT,
                    estado_novo TEXT NOT NULL,
                    ocorrida_em TEXT NOT NULL,
                    detalhe TEXT
                );
                """
            )

    def registrar_evento(self, evento_id: str) -> bool:
        """Registra um evento uma vez e persiste sua entrada em RECEBIDO."""
        self._validar_evento_id(evento_id)
        with self._transacao() as conexao:
            cursor = conexao.execute(
                """
                INSERT OR IGNORE INTO eventos_orquestracao (evento_id, estado)
                VALUES (?, ?)
                """,
                (evento_id, EstadoOrquestracao.RECEBIDO.value),
            )
            if cursor.rowcount == 0:
                return False
            self._gravar_transicao(
                conexao,
                evento_id,
                None,
                EstadoOrquestracao.RECEBIDO,
                None,
            )
            return True

    def obter_estado(self, evento_id: str) -> EstadoOrquestracao:
        """Retorna o estado atual persistido do evento."""
        with closing(self._abrir_conexao()) as conexao:
            linha = conexao.execute(
                "SELECT estado FROM eventos_orquestracao WHERE evento_id = ?",
                (evento_id,),
            ).fetchone()
        if linha is None:
            raise EventoNaoEncontrado(f"Evento não registrado: {evento_id}")
        return EstadoOrquestracao(linha["estado"])

    def obter_historico(self, evento_id: str) -> list[TransicaoOrquestracao]:
        """Retorna todas as transições persistidas do evento, em ordem."""
        with closing(self._abrir_conexao()) as conexao:
            linhas = conexao.execute(
                """
                SELECT evento_id, estado_anterior, estado_novo, ocorrida_em, detalhe
                FROM historico_transicoes
                WHERE evento_id = ?
                ORDER BY id
                """,
                (evento_id,),
            ).fetchall()
        if not linhas:
            with closing(self._abrir_conexao()) as conexao:
                existe = conexao.execute(
                    "SELECT 1 FROM eventos_orquestracao WHERE evento_id = ?",
                    (evento_id,),
                ).fetchone()
            if existe is None:
                raise EventoNaoEncontrado(f"Evento não registrado: {evento_id}")
        return [
            TransicaoOrquestracao(
                evento_id=linha["evento_id"],
                estado_anterior=linha["estado_anterior"],
                estado_novo=linha["estado_novo"],
                ocorrida_em=datetime.fromisoformat(linha["ocorrida_em"]),
                detalhe=linha["detalhe"],
            )
            for linha in linhas
        ]

    def transicionar(
        self,
        evento_id: str,
        estado_novo: EstadoOrquestracao,
        detalhe: str | None = None,
    ) -> TransicaoOrquestracao:
        """Valida e persiste uma transição permitida."""
        if estado_novo is EstadoOrquestracao.EM_EXECUCAO:
            raise TransicaoInvalida(
                "Use executar_uma_vez para iniciar a execução do evento."
            )
        with self._transacao() as conexao:
            return self._transicionar_na_transacao(
                conexao,
                evento_id,
                estado_novo,
                detalhe,
            )

    async def executar_uma_vez(
        self,
        evento_id: str,
        acao: Callable[[], Awaitable[T]],
    ) -> T:
        """Reivindica a execução antes de chamar a ação e impede uma segunda chamada."""
        with self._transacao() as conexao:
            linha = self._obter_evento_na_transacao(conexao, evento_id)
            if linha["execucao_iniciada"]:
                raise EventoJaExecutado(
                    f"A execução do evento {evento_id} já foi iniciada."
                )
            if EstadoOrquestracao(linha["estado"]) is not EstadoOrquestracao.APROVADO:
                raise TransicaoInvalida(
                    "Somente eventos APROVADO podem iniciar execução."
                )
            conexao.execute(
                """
                UPDATE eventos_orquestracao
                SET execucao_iniciada = 1
                WHERE evento_id = ?
                """,
                (evento_id,),
            )
            self._transicionar_na_transacao(
                conexao,
                evento_id,
                EstadoOrquestracao.EM_EXECUCAO,
                "Execução reivindicada de forma atômica.",
            )

        try:
            resultado = await acao()
        except FalhaRecuperavel as erro:
            self.transicionar(
                evento_id,
                EstadoOrquestracao.ERRO_RECUPERAVEL,
                str(erro),
            )
            raise
        except Exception as erro:
            self.transicionar(
                evento_id,
                EstadoOrquestracao.ERRO_FINAL,
                str(erro),
            )
            raise
        self.transicionar(evento_id, EstadoOrquestracao.CONCLUIDO)
        return resultado

    async def executar_lote(
        self,
        acoes: Iterable[tuple[str, Callable[[], Awaitable[object]]]],
    ) -> list[ResultadoExecucaoEvento]:
        """Continua o lote após falhas recuperáveis registradas."""
        resultados = []
        for evento_id, acao in acoes:
            try:
                await self.executar_uma_vez(evento_id, acao)
            except FalhaRecuperavel as erro:
                resultados.append(
                    ResultadoExecucaoEvento(
                        evento_id=evento_id,
                        estado=EstadoOrquestracao.ERRO_RECUPERAVEL,
                        erro=str(erro),
                    )
                )
            else:
                resultados.append(
                    ResultadoExecucaoEvento(
                        evento_id=evento_id,
                        estado=EstadoOrquestracao.CONCLUIDO,
                    )
                )
        return resultados

    def _transicionar_na_transacao(
        self,
        conexao: sqlite3.Connection,
        evento_id: str,
        estado_novo: EstadoOrquestracao,
        detalhe: str | None,
    ) -> TransicaoOrquestracao:
        linha = self._obter_evento_na_transacao(conexao, evento_id)
        estado_anterior = EstadoOrquestracao(linha["estado"])
        if estado_novo not in _TRANSICOES_PERMITIDAS[estado_anterior]:
            raise TransicaoInvalida(
                f"Transição não permitida: {estado_anterior.value} -> "
                f"{estado_novo.value}."
            )
        if (
            estado_anterior is EstadoOrquestracao.ERRO_RECUPERAVEL
            and estado_novo is EstadoOrquestracao.EM_ANALISE
            and linha["execucao_iniciada"]
        ):
            raise EventoJaExecutado(
                "O evento já teve execução iniciada e não pode ser repetido."
            )

        agora = datetime.now(timezone.utc)
        conexao.execute(
            "UPDATE eventos_orquestracao SET estado = ? WHERE evento_id = ?",
            (estado_novo.value, evento_id),
        )
        self._gravar_transicao(
            conexao,
            evento_id,
            estado_anterior,
            estado_novo,
            detalhe,
            agora,
        )
        return TransicaoOrquestracao(
            evento_id=evento_id,
            estado_anterior=estado_anterior,
            estado_novo=estado_novo,
            ocorrida_em=agora,
            detalhe=detalhe,
        )

    @staticmethod
    def _obter_evento_na_transacao(
        conexao: sqlite3.Connection,
        evento_id: str,
    ) -> sqlite3.Row:
        linha = conexao.execute(
            """
            SELECT estado, execucao_iniciada
            FROM eventos_orquestracao
            WHERE evento_id = ?
            """,
            (evento_id,),
        ).fetchone()
        if linha is None:
            raise EventoNaoEncontrado(f"Evento não registrado: {evento_id}")
        return linha

    @staticmethod
    def _gravar_transicao(
        conexao: sqlite3.Connection,
        evento_id: str,
        estado_anterior: EstadoOrquestracao | None,
        estado_novo: EstadoOrquestracao,
        detalhe: str | None,
        ocorrida_em: datetime | None = None,
    ) -> None:
        conexao.execute(
            """
            INSERT INTO historico_transicoes
                (evento_id, estado_anterior, estado_novo, ocorrida_em, detalhe)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                evento_id,
                estado_anterior.value if estado_anterior else None,
                estado_novo.value,
                (ocorrida_em or datetime.now(timezone.utc)).isoformat(),
                detalhe,
            ),
        )

    @staticmethod
    def _validar_evento_id(evento_id: str) -> None:
        if not evento_id.strip():
            raise ValueError("O identificador do evento não pode ser vazio.")
