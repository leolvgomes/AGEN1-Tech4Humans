"""Cliente MCP resiliente (Seção 11): único caminho dos agentes até o servidor.

- Fala Streamable HTTP (JSON-RPC por POST; respostas em JSON ou SSE).
- Descobre as ferramentas com tools/list e valida os parâmetros antes de enviar.
- 503/500: backoff exponencial. 504 em consulta: repete. 504 em ação: verifica antes de repetir.
- 409: consulta (verificar) e reavalia. 410: sinaliza fim do cenário. 400/404/405/422: devolve ao agente.
- Conexão perdida ou sessão inválida: reconecta e avisa quem quiser saber (on_reconectar).
- FerramentasAgente aplica a matriz de permissões: chamada fora da matriz falha antes de sair.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Awaitable, Callable, Optional

import httpx

from ..log import Log

PROTOCOLO = "2025-06-18"


class ErroMCP(Exception):
    def __init__(self, codigo: int, mensagem: str, dados: dict | None = None) -> None:
        super().__init__(f"{codigo}: {mensagem}")
        self.codigo = codigo
        self.mensagem = mensagem
        self.dados = dados or {}


class CenarioEncerrado(ErroMCP):
    pass


class PermissaoNegada(Exception):
    pass


class RodadaObsoleta(Exception):
    """O servidor reiniciou: o caso pertence a uma rodada anterior e não pode mais agir."""


class ConexaoPerdida(Exception):
    pass


Verificador = Callable[[], Awaitable[Optional[dict]]]


class ClienteMCP:
    def __init__(self, url: str, timeout_s: float, log: Log) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.log = log
        self.sessao: Optional[str] = None
        self.ferramentas: dict[str, dict] = {}
        self.encerrado = False
        self.ultimo_agora: str = ""
        self.on_reconectar: list[Callable[[], Awaitable[None]]] = []
        self._ids = itertools.count(1)
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5))
        self._trava_conexao = asyncio.Lock()
        self.estatisticas: dict[str, int] = {}

    def _contar(self, chave: str) -> None:
        self.estatisticas[chave] = self.estatisticas.get(chave, 0) + 1

    # ---------- transporte ----------
    def _cabecalhos(self) -> dict:
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "MCP-Protocol-Version": PROTOCOLO}
        if self.sessao:
            h["Mcp-Session-Id"] = self.sessao
        return h

    @staticmethod
    def _ler_resposta(resp: httpx.Response, rid: int) -> dict:
        tipo = resp.headers.get("content-type", "")
        if "text/event-stream" in tipo:
            for bloco in resp.text.split("\n\n"):
                dados = "\n".join(l[5:].strip() for l in bloco.splitlines() if l.startswith("data:"))
                if not dados:
                    continue
                msg = json.loads(dados)
                if msg.get("id") == rid:
                    return msg
            raise ConexaoPerdida("resposta SSE sem a mensagem esperada")
        return resp.json()

    async def _rpc(self, metodo: str, params: dict | None, timeout: float | None = None, notificacao: bool = False) -> dict:
        rid = next(self._ids)
        corpo: dict[str, Any] = {"jsonrpc": "2.0", "method": metodo}
        if params is not None:
            corpo["params"] = params
        if not notificacao:
            corpo["id"] = rid
        try:
            resp = await self._http.post(self.url, json=corpo, headers=self._cabecalhos(), timeout=timeout or self.timeout_s)
        except httpx.TimeoutException:
            raise
        except httpx.HTTPError as e:
            raise ConexaoPerdida(str(e)) from e
        if resp.status_code in (404, 400) and self.sessao and metodo != "initialize":
            raise ConexaoPerdida(f"sessão inválida ({resp.status_code}); o servidor pode ter reiniciado")
        if resp.status_code >= 500 and resp.status_code != 504:
            raise ConexaoPerdida(f"HTTP {resp.status_code}")
        if notificacao:
            return {}
        msg = self._ler_resposta(resp, rid)
        if "error" in msg:
            raise ErroMCP(400, f"JSON-RPC: {msg['error'].get('message')}")
        return msg.get("result", {})

    async def conectar(self) -> None:
        async with self._trava_conexao:
            atraso = 1.0
            while True:
                try:
                    self.sessao = None
                    rid = next(self._ids)
                    corpo = {
                        "jsonrpc": "2.0", "id": rid, "method": "initialize",
                        "params": {"protocolVersion": PROTOCOLO, "capabilities": {}, "clientInfo": {"name": "triagem-n1", "version": "1.0"}},
                    }
                    resp = await self._http.post(self.url, json=corpo, headers=self._cabecalhos())
                    resp.raise_for_status()
                    self.sessao = resp.headers.get("mcp-session-id")
                    self._ler_resposta(resp, rid)
                    await self._rpc("notifications/initialized", None, notificacao=True)
                    lista = await self._rpc("tools/list", {})
                    self.ferramentas = {t["name"]: t for t in lista.get("tools", [])}
                    self.log.registrar("despachante", "mcp/conectar", motivo=f"{len(self.ferramentas)} ferramentas descobertas")
                    return
                except (httpx.HTTPError, ConexaoPerdida, ValueError) as e:
                    self.log.registrar("despachante", "mcp/conectar", "falha", motivo=f"{e}; nova tentativa em {atraso:.0f}s")
                    await asyncio.sleep(atraso)
                    atraso = min(atraso * 2, 15)

    async def _reconectar(self) -> None:
        self._contar("reconexoes")
        await self.conectar()
        for cb in list(self.on_reconectar):
            try:
                await cb()
            except Exception as e:  # nunca deixar o aviso derrubar a chamada
                self.log.registrar("despachante", "mcp/reconectar", "erro", motivo=str(e))

    # ---------- validação contra o tools/list ----------
    def validar(self, ferramenta: str, args: dict) -> None:
        t = self.ferramentas.get(ferramenta)
        if not t:
            raise ErroMCP(404, f"ferramenta '{ferramenta}' não existe no servidor (tools/list)")
        esquema = t.get("inputSchema", {})
        props = esquema.get("properties", {})
        desconhecidos = [k for k in args if k not in props]
        if desconhecidos:
            raise ErroMCP(400, f"parâmetros desconhecidos para {ferramenta}: {desconhecidos}")
        faltando = [k for k in esquema.get("required", []) if args.get(k) in (None, "", [], {})]
        if faltando:
            raise ErroMCP(400, f"faltam parâmetros obrigatórios para {ferramenta}: {faltando}")

    def eh_leitura(self, ferramenta: str) -> bool:
        return bool((self.ferramentas.get(ferramenta, {}).get("annotations") or {}).get("readOnlyHint"))

    def aceita(self, ferramenta: str, parametro: str) -> bool:
        return parametro in self.ferramentas.get(ferramenta, {}).get("inputSchema", {}).get("properties", {})

    # ---------- chamada resiliente ----------
    async def _chamar_uma_vez(self, ferramenta: str, args: dict, timeout: float) -> dict:
        r = await self._rpc("tools/call", {"name": ferramenta, "arguments": args}, timeout=timeout)
        conteudo = r.get("content") or [{}]
        texto = conteudo[0].get("text", "{}")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            dados = {"status": "erro", "codigo": 500, "mensagem": texto}
        if dados.get("agora"):
            self.ultimo_agora = dados["agora"]
        return dados

    async def chamar(
        self,
        agente: str,
        ferramenta: str,
        args: dict,
        motivo: str = "",
        verificar: Verificador | None = None,
        caso_id: str | None = None,
    ) -> dict:
        if not self.ferramentas:
            await self.conectar()
        args = {k: v for k, v in args.items() if v is not None}
        completo = {"agente": agente, "motivo": motivo, **args}
        self.validar(ferramenta, completo)
        leitura = self.eh_leitura(ferramenta)
        if self.encerrado and not leitura:
            raise CenarioEncerrado(410, "o cenário acabou: nenhuma ação nova")
        timeout = self.timeout_s + float(args.get("esperar_segundos") or 0)
        evento_id = args.get("evento_id")
        atraso = 2.0
        tentativa = 0
        while True:
            tentativa += 1
            try:
                resp = await self._chamar_uma_vez(ferramenta, completo, timeout)
            except httpx.TimeoutException:
                resp = {"status": "erro", "codigo": 504, "mensagem": "timeout do cliente"}
            except ConexaoPerdida as e:
                self.log.registrar(agente, f"mcp/{ferramenta}", "conexao_perdida", motivo=str(e), caso_id=caso_id, evento_id=evento_id, tentativas=tentativa)
                await self._reconectar()
                if not leitura and verificar:
                    feito = await verificar()
                    if feito is not None:
                        return {"status": "ok", "verificado": True, **feito}
                if tentativa > 6:
                    raise
                continue

            if resp.get("status") == "ok":
                if tentativa > 1:
                    self.log.registrar(agente, f"mcp/{ferramenta}", "ok", motivo="sucesso após falha", caso_id=caso_id, evento_id=evento_id, tentativas=tentativa)
                return resp

            codigo = int(resp.get("codigo") or 500)
            mensagem = str(resp.get("mensagem") or "")
            self._contar(str(codigo))
            self.log.registrar(agente, f"mcp/{ferramenta}", f"erro_{codigo}", motivo=mensagem[:200], caso_id=caso_id, evento_id=evento_id, tentativas=tentativa)

            if codigo == 410:
                if not leitura:
                    self.encerrado = True
                raise CenarioEncerrado(410, mensagem, resp)
            if codigo in (503, 500):
                if tentativa >= 5:
                    raise ErroMCP(codigo, mensagem, resp)
                await asyncio.sleep(atraso)
                atraso = min(atraso * 2, 16)
                continue
            if codigo == 504:
                if leitura:
                    if tentativa >= 5:
                        raise ErroMCP(codigo, mensagem, resp)
                    continue
                # Ação com 504: pode ou não ter sido feita. Conferir antes de repetir.
                if verificar:
                    await asyncio.sleep(1)
                    feito = await verificar()
                    if feito is not None:
                        self.log.registrar(agente, f"mcp/{ferramenta}", "verificado", motivo="504: a ação já tinha sido feita, não repeti", caso_id=caso_id, evento_id=evento_id)
                        return {"status": "ok", "verificado": True, **feito}
                    if tentativa >= 4:
                        raise ErroMCP(codigo, mensagem, resp)
                    continue
                raise ErroMCP(codigo, mensagem + " (sem rotina de verificação: não repeti)", resp)
            if codigo == 409:
                # Conflito: consultar de novo e reavaliar antes de agir outra vez.
                if verificar and tentativa < 4:
                    await asyncio.sleep(1 + tentativa)
                    feito = await verificar()
                    if feito is not None:
                        return {"status": "ok", "verificado": True, **feito}
                    continue
                raise ErroMCP(codigo, mensagem, resp)
            raise ErroMCP(codigo, mensagem, resp)

    async def fechar(self) -> None:
        await self._http.aclose()


# ---------- matriz de permissões (Seção 5.2) ----------
LEITURA = {"consultar", "listar_bases", "registrar_conversa"}
PERMISSOES: dict[str, dict[str, Any]] = {
    "despachante": {"ferramentas": LEITURA | {"proximo_evento", "listar_eventos", "ler_evento"}},
    "triador": {"ferramentas": LEITURA},
    "pesquisador": {"ferramentas": LEITURA},
    "revisor": {"ferramentas": LEITURA},
    "executor": {"ferramentas": LEITURA | {"registrar", "atualizar", "responder_evento", "enviar_mensagem"}},
    "operador_tela": {"ferramentas": {"registrar_conversa"}, "tela": True},
    "escalador": {"ferramentas": LEITURA | {"enviar_mensagem", "responder_evento"}, "bases": {"times", "mensagens", "eventos"}},
}


class FerramentasAgente:
    """O que cada agente enxerga do servidor. Fora da matriz: PermissaoNegada, sem chegar ao servidor."""

    def __init__(self, cliente: ClienteMCP, agente: str, rodada_atual: Callable[[], int]) -> None:
        self.cliente = cliente
        self.agente = agente
        self.regras = PERMISSOES[agente]
        self.rodada_atual = rodada_atual

    def pode(self, ferramenta: str) -> bool:
        return ferramenta in self.regras["ferramentas"]

    async def chamar(self, ferramenta: str, motivo: str, *, verificar: Verificador | None = None, rodada: int | None = None, caso_id: str | None = None, **args) -> dict:
        if not self.pode(ferramenta):
            raise PermissaoNegada(f"{self.agente} não pode usar {ferramenta} (matriz de permissões)")
        bases = self.regras.get("bases")
        if bases and ferramenta == "consultar" and args.get("base") not in bases:
            raise PermissaoNegada(f"{self.agente} só consulta as bases {sorted(bases)}")
        if rodada is not None and rodada != self.rodada_atual() and ferramenta not in ("consultar", "listar_bases", "registrar_conversa"):
            raise RodadaObsoleta(f"caso da rodada {rodada}, servidor na rodada {self.rodada_atual()}")
        if not motivo:
            raise ValueError("toda chamada leva motivo (Regra R7)")
        return await self.cliente.chamar(self.agente, ferramenta, args, motivo=motivo, verificar=verificar, caso_id=caso_id)

    async def conversa(self, para: str, mensagem: str, de: str | None = None) -> None:
        """registrar_conversa nunca derruba o fluxo: é só espelho no painel."""
        from ..util import mascarar

        try:
            await self.chamar("registrar_conversa", "espelhar conversa entre agentes no painel", para=para, mensagem=mascarar(mensagem)[:1900], de=de or self.agente)
        except Exception as e:
            self.cliente.log.registrar(self.agente, "registrar_conversa", "erro", motivo=str(e))
