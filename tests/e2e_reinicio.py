"""Teste de resiliência: reiniciar o servidor no meio da execução (Seção 15.1).

    SERVIDOR_DIR="<pasta do Servidor MCP>" python -m tests.e2e_reinicio

Sobe um servidor próprio (porta 8797), processa um evento, derruba e sobe o servidor de novo, e confere que o time
reconectou, abriu uma rodada nova (o relógio zerou) e seguiu atendendo sem misturar os casos antigos.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import tempfile

import httpx

from src.config import Config
from src.main import montar
from tests.llm_simulado import LLMSimulado

PORTA = 8797
URL = f"http://127.0.0.1:{PORTA}"
PASTA = pathlib.Path(os.environ.get("SERVIDOR_DIR", pathlib.Path(__file__).resolve().parents[2] / "t4h-desafios" / "Hackathon - UNIFEI 2026" / "Servidor MCP (Compartilhado)"))


def subir() -> subprocess.Popen:
    py = PASTA / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return subprocess.Popen([str(py if py.exists() else sys.executable), "mundo.py", "--tema", "triagem", "--porta", str(PORTA), "--sem-navegador",
                             "--sem-cenario", "--erros", "0", "--segundos-por-dia", "1200", "--log", str(pathlib.Path(tempfile.gettempdir()) / "reinicio.jsonl")],
                            cwd=PASTA, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def esperar_no_ar() -> None:
    for _ in range(60):
        try:
            async with httpx.AsyncClient(timeout=2) as h:
                await h.get(f"{URL}/api/estado")
                return
        except httpx.HTTPError:
            await asyncio.sleep(0.5)
    raise RuntimeError("servidor não subiu")


async def evento(corpo: str) -> str:
    async with httpx.AsyncClient(timeout=5) as h:
        r = await h.post(f"{URL}/api/evento", json={"de": "lia.mar@t4h.exemplo", "nome": "Lia", "assunto": "vpn", "corpo": corpo})
        return r.json()["id"]


async def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="triagem-reinicio-"))
    srv = subir()
    try:
        await esperar_no_ar()
        cfg = Config(llm_api_key="x", llm_model="x", mcp_url=f"{URL}/mcp", legado_url=f"{URL}/legado", dados_dir=tmp, logs_dir=tmp, espera_evento_s=2, operador_modo="http")
        ctx = montar(cfg, LLMSimulado(), console=False)
        desp = ctx.agentes["despachante"]
        await desp.iniciar()
        ctx.bus.iniciar(2)
        laco = asyncio.create_task(desp.laco())
        e1 = await evento("Como me conecto à VPN para trabalhar de fora do escritório?")
        await asyncio.sleep(6)
        await ctx.bus.esperar_ocioso(30)
        r1 = ctx.rodada
        c1 = ctx.curta.por_evento(r1, e1)
        print(f"antes: rodada {r1}, {e1} -> {c1.estado if c1 else None}")
        srv.terminate()
        srv.wait()
        print("servidor derrubado; subindo de novo...")
        await asyncio.sleep(3)
        srv = subir()
        await esperar_no_ar()
        await asyncio.sleep(4)
        e2 = await evento("Como me conecto à VPN para trabalhar de fora do escritório?")
        for _ in range(40):
            await asyncio.sleep(1)
            c2 = ctx.curta.por_evento(ctx.rodada, e2)
            if c2 and c2.estado == "CONCLUIDO":
                break
        c2 = ctx.curta.por_evento(ctx.rodada, e2)
        print(f"depois: rodada {ctx.rodada}, {e2} -> {c2.estado if c2 else None}; reconexões {ctx.mcp.estatisticas.get('reconexoes')}")
        laco.cancel()
        ok = c1 and c1.estado == "CONCLUIDO" and ctx.rodada == r1 + 1 and c2 and c2.estado == "CONCLUIDO" and c2.caso_id != c1.caso_id
        print("RESULTADO:", "OK" if ok else "FALHA")
        return 0 if ok else 1
    finally:
        srv.terminate()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(asyncio.run(main()))
