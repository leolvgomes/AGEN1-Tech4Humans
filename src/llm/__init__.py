"""Cliente do modelo de IA (qualquer API compatível com a da OpenAI).

Saída JSON validada por Pydantic: se vier fora do esquema, pede UMA correção ao modelo; persistindo, ErroLLM
(o agente então escala o caso com erro_repetido, nunca decide às cegas). Erros de API: nova tentativa com backoff.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any, Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Config
from ..log import Log
from ..util import extrair_json

M = TypeVar("M", bound=BaseModel)


class ErroLLM(Exception):
    pass


class LLM(Protocol):
    async def json(self, agente: str, sistema: str, usuario: str, esquema: type[M], revisor: bool = False, caso_id: str | None = None) -> M: ...

    async def texto(self, agente: str, sistema: str, usuario: str, caso_id: str | None = None) -> str: ...


class ClienteLLM:
    def __init__(self, cfg: Config, log: Log) -> None:
        from openai import AsyncOpenAI

        self.cfg = cfg
        self.log = log
        self.cliente = AsyncOpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url or None, timeout=cfg.llm_timeout_s, max_retries=0)
        self._sem = asyncio.Semaphore(max(1, cfg.llm_max_concorrencia))
        self._janela: deque[float] = deque()
        self._json_mode = cfg.llm_json_mode
        self.chamadas = 0

    async def _limitar(self) -> None:
        """Limite de chamadas por minuto, para evitar custo descontrolado e laços infinitos."""
        while True:
            agora = time.monotonic()
            while self._janela and agora - self._janela[0] > 60:
                self._janela.popleft()
            if len(self._janela) < self.cfg.llm_max_por_minuto:
                self._janela.append(agora)
                return
            await asyncio.sleep(1)

    async def _completar(self, agente: str, mensagens: list[dict], modelo: str, json_saida: bool, caso_id: str | None) -> str:
        atraso = 2.0
        for tentativa in range(1, 5):
            await self._limitar()
            async with self._sem:
                try:
                    kwargs: dict[str, Any] = {"model": modelo, "messages": mensagens, "temperature": self.cfg.llm_temperatura}
                    if json_saida and self._json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    r = await self.cliente.chat.completions.create(**kwargs)
                    self.chamadas += 1
                    return r.choices[0].message.content or ""
                except Exception as e:  # erros de API, timeout, limite de taxa
                    texto = str(e)
                    if json_saida and self._json_mode and ("response_format" in texto or "json_object" in texto):
                        self._json_mode = False  # gateway não suporta modo JSON: seguimos só com o prompt
                        continue
                    if "temperature" in texto and "unsupported" in texto.lower():
                        self.cfg.llm_temperatura = 1.0
                        continue
                    self.log.registrar(agente, "llm", "erro_api", motivo=texto[:200], caso_id=caso_id, tentativas=tentativa)
                    if tentativa == 4:
                        raise ErroLLM(f"API do modelo falhou: {texto[:200]}") from e
            await asyncio.sleep(atraso)
            atraso *= 2
        raise ErroLLM("API do modelo falhou")

    async def json(self, agente: str, sistema: str, usuario: str, esquema: type[M], revisor: bool = False, caso_id: str | None = None) -> M:
        modelo = (self.cfg.llm_model_revisor if revisor else self.cfg.llm_model) or self.cfg.llm_model
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
        ultimo_erro = ""
        for rodada in range(2):
            texto = await self._completar(agente, mensagens, modelo, True, caso_id)
            try:
                return esquema.model_validate(extrair_json(texto))
            except (ValueError, ValidationError, json.JSONDecodeError) as e:
                ultimo_erro = str(e)[:500]
                self.log.registrar(agente, "llm/json_invalido", "erro", motivo=ultimo_erro[:200], caso_id=caso_id, tentativas=rodada + 1)
                mensagens += [
                    {"role": "assistant", "content": texto},
                    {"role": "user", "content": f"Sua resposta não seguiu o esquema JSON pedido ({ultimo_erro}). Responda de novo APENAS com o JSON válido."},
                ]
        raise ErroLLM(f"saída fora do esquema após correção: {ultimo_erro}")

    async def texto(self, agente: str, sistema: str, usuario: str, caso_id: str | None = None) -> str:
        mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]
        return (await self._completar(agente, mensagens, self.cfg.llm_model, False, caso_id)).strip()

    async def testar(self) -> str:
        return await self.texto("despachante", "Responda apenas: ok", "teste de conexão")
