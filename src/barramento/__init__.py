"""Barramento interno: fila em memória com mensagens validadas (envelope 6.1), persistidas no SQLite.

Os casos correm em paralelo (N trabalhadores), mas cada caso é tratado por um agente de cada vez
(trava por caso_id). Uma falha de um agente fica isolada no caso: ele vai para ERRO e é escalado.
"""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from ..contratos import Envelope
from ..log import Log
from ..memoria import Banco
from ..util import mascarar

Handler = Callable[[Envelope], Awaitable[None]]

# Trocas espelhadas no painel do servidor com registrar_conversa (Seção 13).
ESPELHAR = {"PROPOSTA", "REVISAO", "ESCALAR", "PEDIR_APROVACAO", "DECISAO_HUMANA", "LANCAR_FERIAS", "PEDIR_INFO", "EXECUTAR"}


class Barramento:
    def __init__(self, banco: Banco, log: Log, rodada: Callable[[], int]) -> None:
        self.banco = banco
        self.log = log
        self.rodada = rodada
        self.fila: asyncio.Queue[Envelope] = asyncio.Queue()
        self.handlers: dict[str, Handler] = {}
        self.travas: dict[str, asyncio.Lock] = {}
        self.ao_falhar: Callable[[Envelope, Exception], Awaitable[None]] | None = None
        self.espelho: Callable[[Envelope], Awaitable[None]] | None = None
        self._tarefas: list[asyncio.Task] = []
        self._ocupados = 0
        self.total = 0

    def registrar(self, nome: str, handler: Handler) -> None:
        self.handlers[nome] = handler

    async def enviar(self, env: Envelope) -> None:
        env = Envelope.model_validate(env.model_dump())  # valida de novo: rota e payload
        self.banco.x(
            "INSERT OR IGNORE INTO mensagens (id, rodada, de, para, tipo, caso_id, ts, payload) VALUES (?,?,?,?,?,?,?,?)",
            (env.id, self.rodada(), env.de, env.para, env.tipo, env.caso_id, env.ts, mascarar(json.dumps(env.payload, ensure_ascii=False, default=str))),
        )
        self.total += 1
        await self.fila.put(env)

    def ocioso(self) -> bool:
        return self.fila.empty() and self._ocupados == 0

    async def esperar_ocioso(self, limite_s: float = 120) -> None:
        fim = asyncio.get_running_loop().time() + limite_s
        while not self.ocioso() and asyncio.get_running_loop().time() < fim:
            await asyncio.sleep(0.5)

    async def _trabalhador(self) -> None:
        while True:
            env = await self.fila.get()
            self._ocupados += 1
            try:
                trava = self.travas.setdefault(env.caso_id, asyncio.Lock())
                async with trava:
                    if env.tipo in ESPELHAR and self.espelho:
                        await self.espelho(env)
                    handler = self.handlers.get(env.para)
                    if handler is None:
                        raise RuntimeError(f"ninguém escuta '{env.para}'")
                    await handler(env)
            except Exception as e:
                self.log.registrar(env.para, f"barramento/{env.tipo}", "excecao", motivo=f"{type(e).__name__}: {e}", caso_id=env.caso_id)
                if self.ao_falhar:
                    try:
                        await self.ao_falhar(env, e)
                    except Exception as e2:
                        self.log.registrar("despachante", "barramento/ao_falhar", "excecao", motivo=str(e2), caso_id=env.caso_id)
            finally:
                self._ocupados -= 1
                self.fila.task_done()

    def iniciar(self, n: int) -> None:
        for _ in range(max(1, n)):
            self._tarefas.append(asyncio.create_task(self._trabalhador()))

    async def parar(self) -> None:
        for t in self._tarefas:
            t.cancel()
