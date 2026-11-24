"""Log local estruturado (um JSON por linha), sempre com dados sensíveis mascarados."""

from __future__ import annotations

import json
import pathlib
import sys
import threading
from collections import Counter
from datetime import datetime
from typing import Any

from .util import mascarar_obj

CORES = {
    "despachante": "\033[90m", "triador": "\033[94m", "pesquisador": "\033[96m", "revisor": "\033[95m",
    "executor": "\033[92m", "operador_tela": "\033[93m", "escalador": "\033[91m", "canal_humano": "\033[97m",
}
FIM = "\033[0m"


class Log:
    def __init__(self, pasta: pathlib.Path, nome: str = "agentes", console: bool = True) -> None:
        pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = pasta / f"{nome}-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        self.console = console
        self._trava = threading.Lock()
        self.contagem: Counter = Counter()
        self.erros: Counter = Counter()

    def registrar(
        self,
        agente: str,
        acao: str,
        resultado: str = "ok",
        motivo: str = "",
        caso_id: str | None = None,
        evento_id: str | None = None,
        tentativas: int = 1,
        **extra: Any,
    ) -> None:
        linha = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "agente": agente,
            "caso_id": caso_id,
            "evento_id": evento_id,
            "acao": acao,
            "resultado": resultado,
            "motivo": motivo,
            "tentativas": tentativas,
            **extra,
        }
        linha = mascarar_obj(linha)
        self.contagem[(agente, acao)] += 1
        if resultado not in ("ok", "verificado"):
            self.erros[resultado] += 1
        with self._trava:
            with self.arquivo.open("a", encoding="utf-8") as f:
                f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
        if self.console:
            cor = CORES.get(agente, "")
            ref = f" [{caso_id}/{evento_id}]" if caso_id or evento_id else ""
            texto = f"{cor}{linha['ts'][11:]} {agente:<13}{FIM} {acao}{ref} {resultado if resultado != 'ok' else ''} {linha['motivo'][:140]}"
            try:
                print(texto, file=sys.stderr, flush=True)
            except UnicodeEncodeError:
                print(texto.encode("ascii", "replace").decode(), file=sys.stderr, flush=True)
