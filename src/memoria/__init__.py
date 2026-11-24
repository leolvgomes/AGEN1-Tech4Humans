"""Persistência em SQLite: memória curta (casos), memória longa (lições), ações já feitas,
mensagens do barramento, escalações e aprovações (o canal humano lê e grava aqui também)."""

from __future__ import annotations

import json
import pathlib
import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional

from ..contratos import ESTADOS_FINAIS, Caso
from ..util import mascarar, normalizar_assunto, sem_acento, tokens

ESQUEMA = """
CREATE TABLE IF NOT EXISTS rodadas (id INTEGER PRIMARY KEY, iniciada_em TEXT, ultimo_agora TEXT, encerrada INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS casos (
  caso_id TEXT PRIMARY KEY, rodada INTEGER, evento_id TEXT, remetente TEXT, assunto_norm TEXT,
  estado TEXT, dados TEXT, criado_em TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS eventos_vistos (rodada INTEGER, evento_id TEXT, caso_id TEXT, visto_em TEXT, PRIMARY KEY (rodada, evento_id));
CREATE TABLE IF NOT EXISTS acoes (rodada INTEGER, chave TEXT, status TEXT, resultado TEXT, ts TEXT, PRIMARY KEY (rodada, chave));
CREATE TABLE IF NOT EXISTS mensagens (id TEXT PRIMARY KEY, rodada INTEGER, de TEXT, para TEXT, tipo TEXT, caso_id TEXT, ts TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS escalacoes (
  id TEXT PRIMARY KEY, rodada INTEGER, caso_id TEXT, evento_id TEXT, categoria TEXT, urgencia TEXT,
  dados TEXT, status TEXT, assumido_por TEXT, criado_em TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS aprovacoes (
  id TEXT PRIMARY KEY, rodada INTEGER, caso_id TEXT, dados TEXT, status TEXT, urgencia TEXT,
  decidido_por TEXT, decidido_em TEXT, comentario TEXT, criado_em TEXT, lembretes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS licoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, padrao TEXT, licao TEXT, origem_caso_id TEXT,
  vezes_confirmada INTEGER DEFAULT 1, usos INTEGER DEFAULT 0, atualizado_em TEXT, UNIQUE (tipo, padrao));
CREATE TABLE IF NOT EXISTS ajustes (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS perguntas (id INTEGER PRIMARY KEY AUTOINCREMENT, pessoa TEXT, pergunta TEXT, resposta TEXT, ts TEXT);
"""


def agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho: pathlib.Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho = caminho
        self._con = sqlite3.connect(str(caminho), check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._trava = threading.RLock()
        with self._trava:
            self._con.executescript(ESQUEMA)

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._trava:
            return self._con.execute(sql, args).fetchall()

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._trava:
            cur = self._con.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ---------- rodadas ----------
    def rodada_atual(self) -> Optional[sqlite3.Row]:
        linhas = self.q("SELECT * FROM rodadas ORDER BY id DESC LIMIT 1")
        return linhas[0] if linhas else None

    def nova_rodada(self, agora: str) -> int:
        return self.x("INSERT INTO rodadas (iniciada_em, ultimo_agora) VALUES (?, ?)", (agora_iso(), agora))

    def marcar_agora(self, rodada: int, agora: str) -> None:
        self.x("UPDATE rodadas SET ultimo_agora=? WHERE id=?", (agora, rodada))

    # ---------- ajustes (ex.: modo de demonstração T14) ----------
    def ajuste(self, chave: str, padrao: str = "") -> str:
        linhas = self.q("SELECT valor FROM ajustes WHERE chave=?", (chave,))
        return linhas[0]["valor"] if linhas else padrao

    def definir_ajuste(self, chave: str, valor: str) -> None:
        self.x("INSERT INTO ajustes (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, valor))


class MemoriaCurta:
    """Casos em aberto (estrutura 6.2), persistidos: o time sobrevive a uma reinicialização do processo."""

    def __init__(self, banco: Banco) -> None:
        self.b = banco
        self._seq = None

    def proximo_caso_id(self) -> str:
        n = self.b.q("SELECT COUNT(*) AS n FROM casos")[0]["n"] + 1
        return f"c-{n:04d}"

    def salvar(self, caso: Caso) -> None:
        self.b.x(
            """INSERT INTO casos (caso_id, rodada, evento_id, remetente, assunto_norm, estado, dados, criado_em, atualizado_em)
               VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(caso_id) DO UPDATE SET estado=excluded.estado, dados=excluded.dados,
               atualizado_em=excluded.atualizado_em""",
            (caso.caso_id, caso.rodada, caso.evento_id, caso.remetente.lower(), normalizar_assunto(caso.assunto), caso.estado,
             caso.model_dump_json(), agora_iso(), agora_iso()),
        )

    def obter(self, caso_id: str) -> Optional[Caso]:
        linhas = self.b.q("SELECT dados FROM casos WHERE caso_id=?", (caso_id,))
        return Caso.model_validate_json(linhas[0]["dados"]) if linhas else None

    def por_evento(self, rodada: int, evento_id: str) -> Optional[Caso]:
        linhas = self.b.q("SELECT caso_id FROM eventos_vistos WHERE rodada=? AND evento_id=?", (rodada, evento_id))
        return self.obter(linhas[0]["caso_id"]) if linhas and linhas[0]["caso_id"] else None

    def evento_visto(self, rodada: int, evento_id: str) -> bool:
        return bool(self.b.q("SELECT 1 FROM eventos_vistos WHERE rodada=? AND evento_id=?", (rodada, evento_id)))

    def marcar_visto(self, rodada: int, evento_id: str, caso_id: str | None) -> bool:
        """Idempotência por evento_id: devolve False se o evento já tinha sido visto."""
        try:
            self.b.x("INSERT INTO eventos_vistos (rodada, evento_id, caso_id, visto_em) VALUES (?,?,?,?)", (rodada, evento_id, caso_id, agora_iso()))
            return True
        except sqlite3.IntegrityError:
            return False

    def ligar_evento(self, rodada: int, evento_id: str, caso_id: str) -> None:
        self.b.x("UPDATE eventos_vistos SET caso_id=? WHERE rodada=? AND evento_id=?", (caso_id, rodada, evento_id))

    def abertos_do_remetente(self, rodada: int, remetente: str) -> list[Caso]:
        linhas = self.b.q(
            f"SELECT dados FROM casos WHERE rodada=? AND remetente=? AND estado NOT IN ({','.join('?' * len(ESTADOS_FINAIS))}) ORDER BY criado_em DESC",
            (rodada, remetente.lower(), *ESTADOS_FINAIS),
        )
        return [Caso.model_validate_json(l["dados"]) for l in linhas]

    def em_andamento(self, rodada: int) -> list[Caso]:
        linhas = self.b.q(
            f"SELECT dados FROM casos WHERE rodada=? AND estado NOT IN ({','.join('?' * len(ESTADOS_FINAIS))})",
            (rodada, *ESTADOS_FINAIS),
        )
        return [Caso.model_validate_json(l["dados"]) for l in linhas]

    def todos(self, rodada: int | None = None, limite: int = 500) -> list[Caso]:
        if rodada is None:
            linhas = self.b.q("SELECT dados FROM casos ORDER BY criado_em DESC LIMIT ?", (limite,))
        else:
            linhas = self.b.q("SELECT dados FROM casos WHERE rodada=? ORDER BY criado_em DESC LIMIT ?", (rodada, limite))
        return [Caso.model_validate_json(l["dados"]) for l in linhas]

    # ---------- ações já feitas (idempotência) ----------
    def acao_feita(self, rodada: int, chave: str) -> Optional[dict]:
        linhas = self.b.q("SELECT resultado FROM acoes WHERE rodada=? AND chave=? AND status='feita'", (rodada, chave))
        return json.loads(linhas[0]["resultado"]) if linhas else None

    def registrar_acao(self, rodada: int, chave: str, resultado: dict) -> None:
        self.b.x(
            "INSERT INTO acoes (rodada, chave, status, resultado, ts) VALUES (?,?,?,?,?) ON CONFLICT(rodada, chave) DO UPDATE SET status='feita', resultado=excluded.resultado",
            (rodada, chave, "feita", json.dumps(resultado, ensure_ascii=False, default=str), agora_iso()),
        )


TIPOS_LICAO = ("urgencia_falsa", "remetente_repete", "sinal_p0_p1", "correcao_revisor", "mapeamento_frequente", "padrao_aprovacao")


class MemoriaLonga:
    """Padrões gerais aprendidos de um dia para o outro. Nunca 'evento X -> resposta Y' (Regra R2),
    nunca texto completo de e-mail nem dado sensível. Uma lição só vale depois de confirmada por
    mais de um caso, ou quando vem de uma correção do Revisor."""

    def __init__(self, banco: Banco) -> None:
        self.b = banco

    def observar(self, tipo: str, padrao: str, licao: str, caso_id: str) -> None:
        assert tipo in TIPOS_LICAO
        padrao, licao = mascarar(padrao)[:200], mascarar(licao)[:400]
        self.b.x(
            """INSERT INTO licoes (tipo, padrao, licao, origem_caso_id, vezes_confirmada, atualizado_em) VALUES (?,?,?,?,1,?)
               ON CONFLICT(tipo, padrao) DO UPDATE SET vezes_confirmada = vezes_confirmada + 1, licao=excluded.licao, atualizado_em=excluded.atualizado_em""",
            (tipo, padrao, licao, caso_id, agora_iso()),
        )

    def ativas(self) -> list[dict]:
        linhas = self.b.q("SELECT * FROM licoes WHERE vezes_confirmada >= 2 OR tipo='correcao_revisor' ORDER BY vezes_confirmada DESC, atualizado_em DESC")
        return [dict(l) for l in linhas]

    def todas(self) -> list[dict]:
        return [dict(l) for l in self.b.q("SELECT * FROM licoes ORDER BY tipo, vezes_confirmada DESC")]

    def relevantes(self, tipos: tuple[str, ...], texto: str, n: int = 6) -> list[dict]:
        """As N lições mais relevantes por tipo e por semelhança com o texto (não a base inteira)."""
        alvo = set(tokens(texto))
        candidatas = [l for l in self.ativas() if l["tipo"] in tipos]

        def nota(l: dict) -> float:
            sobre = set(tokens(l["padrao"] + " " + l["licao"]))
            return len(alvo & sobre) * 2 + min(l["vezes_confirmada"], 5) * 0.3 + (1.5 if l["tipo"] == "correcao_revisor" else 0)

        escolhidas = sorted(candidatas, key=nota, reverse=True)[:n]
        for l in escolhidas:
            self.b.x("UPDATE licoes SET usos = usos + 1 WHERE id=?", (l["id"],))
        return escolhidas

    def remetente_repete(self, remetente: str) -> Optional[dict]:
        linhas = self.b.q("SELECT * FROM licoes WHERE tipo='remetente_repete' AND padrao=? AND vezes_confirmada >= 2", (sem_acento(remetente),))
        return dict(linhas[0]) if linhas else None

    @staticmethod
    def formatar(licoes: list[dict]) -> str:
        if not licoes:
            return "(nenhuma lição relevante ainda)"
        return "\n".join(f"- [{l['tipo']}] {l['licao']} (confirmada {l['vezes_confirmada']}x)" for l in licoes)
