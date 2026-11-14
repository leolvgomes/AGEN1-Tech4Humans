"""Ponto de partida para o armazenamento local em SQLite."""

import sqlite3
from pathlib import Path


def conectar(caminho: Path) -> sqlite3.Connection:
    """Abre uma conexão SQLite e cria a pasta do banco se necessário."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(caminho)

