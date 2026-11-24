"""Funções de apoio: texto, mascaramento de dados sensíveis, datas e tokens."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any

PRIORIDADE = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "nenhum": 5, None: 5}

STOPWORDS = set(
    """a o os as um uma uns umas de do da dos das em no na nos nas por para pra pro com sem que e ou se
    nao sim meu minha meus minhas seu sua seus suas eu voce voces ele ela eles elas nos isso isto esse essa este esta
    ao aos ja mais muito pouco tem ter estou esta estao foi ser sao como quando onde qual quais porque pq
    oi ola bom dia boa tarde noite obrigado obrigada abraco abs att favor pfv pf re fwd enc fw ai la aqui
    ainda tambem so mas me te lhe""".split()
)


def sem_acento(texto: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


_PREFIXOS = re.compile(r"^\s*((re|res|fwd|fw|enc|tr)\s*:\s*)+", re.IGNORECASE)


def normalizar_assunto(assunto: str) -> str:
    return re.sub(r"\s+", " ", sem_acento(_PREFIXOS.sub("", assunto or ""))).strip()


def eh_resposta(assunto: str) -> bool:
    return bool(_PREFIXOS.match(assunto or ""))


def tokens(texto: str, minimo: int = 3) -> list[str]:
    vistos, saida = set(), []
    for t in re.findall(r"[a-z0-9]+", sem_acento(texto)):
        if len(t) >= minimo and t not in STOPWORDS and t not in vistos:
            vistos.add(t)
            saida.append(t)
    return saida


def similaridade(a: str, b: str) -> float:
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


# ---------- dados sensíveis ----------
_SENSIVEIS = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}\s?-?\s?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[CNPJ]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARTAO]"),
    (re.compile(r"(?i)\b(ag[eê]ncia|ag\.?)\s*:?\s*\d{3,5}(-\d)?"), "[AGENCIA]"),
    (re.compile(r"(?i)\b(conta(?:\s+corrente)?|c/c|cc)\s*:?\s*\d{3,12}-?[\dxX]?"), "[CONTA]"),
    (re.compile(r"(?i)\bpix\s*:?\s*\S+"), "[PIX]"),
    (re.compile(r"(?i)\b(senha|password|pwd)\s*(?:e|é|:|=)?\s*\S+"), "[SENHA]"),
    (re.compile(r"(?i)\bcid\s*-?\s*[a-z]\d{2}(\.\d)?\b"), "[CID]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[TELEFONE]"),
    (re.compile(r"(?i)\brg\s*:?\s*[\d.\-xX]{5,}"), "[RG]"),
]


def mascarar(texto: Any) -> str:
    """Mascara CPF, cartão, conta, senha, CID etc. Usado em tudo que vai para painel, log e canal humano."""
    s = str(texto or "")
    for padrao, troca in _SENSIVEIS:
        s = padrao.sub(troca, s)
    return s


def mascarar_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return mascarar(obj)
    if isinstance(obj, dict):
        return {k: mascarar_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mascarar_obj(v) for v in obj]
    return obj


def tem_dado_sensivel(texto: str) -> list[str]:
    """Sinais objetivos de dado pessoal sensível no texto (independente do modelo de IA)."""
    achados = []
    detectores = [p for p in _SENSIVEIS if p[1] in ("[CPF]", "[CARTAO]", "[AGENCIA]", "[CONTA]", "[PIX]", "[CID]", "[RG]")]
    contexto_bancario = re.search(r"(?i)\b(banco|ag[eê]ncia|corrente|poupan[cç]a|pix|dep[oó]sito)\b", texto or "")
    for padrao, rotulo in detectores:
        if rotulo == "[CONTA]" and not contexto_bancario:
            continue  # "conta 31877" de um cliente não é dado bancário
        if padrao.search(texto or ""):
            achados.append(rotulo.strip("[]").lower())
    return achados


# ---------- evidências (usadas pelo Revisor) ----------
_COLETIVO = re.compile(r"\b(clientes|todos|todo mundo|ninguem|varios|varias|muitos|muitas|usuarios|pessoal|equipe|geral|fora do ar|caiu|parou tudo)\b")


def sinal_coletivo(texto: str) -> bool:
    """Há qualquer sinal de que a falha atinge mais de uma pessoa? (na dúvida, sim: nunca rebaixa a criticidade)"""
    return bool(_COLETIVO.search(sem_acento(texto)))


def _achatar(texto: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento(texto)))


def trecho_no_texto(trecho: Any, texto: str) -> bool:
    """O trecho é mesmo uma cópia (sem acento/pontuação) de pelo menos duas palavras do texto?"""
    t = _achatar(trecho)
    return len(t.split()) >= 2 and f" {t} " in f" {_achatar(texto)} "


def valor_no_texto(valor: Any, texto: str) -> bool:
    """O valor de um campo está apoiado no texto? Todo número precisa aparecer e a maioria das palavras também."""
    if isinstance(valor, (dict, list)):
        valor = json.dumps(valor, ensure_ascii=False)
    alvo = {a.lstrip("0") or "0" for a in _achatar(texto).split()}
    palavras = [p.lstrip("0") or "0" for p in _achatar(valor).split()]
    if any(p.isdigit() and p not in alvo for p in palavras):
        return False
    uteis = [p for p in palavras if len(p) > 2 and p not in STOPWORDS and not p.isdigit()]
    if not uteis:
        return True
    return sum(any(a[:5] == p[:5] for a in alvo) for p in uteis) / len(uteis) >= 0.5


# ---------- datas ----------
_DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def data_do_agora(agora: str | None) -> date | None:
    """'seg 07/12/2026 08:05' -> date(2026, 12, 7)."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", agora or "")
    if not m:
        return None
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def momento_do_agora(agora: str | None) -> datetime | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", agora or "")
    if not m:
        return None
    d, mo, a, h, mi = (int(x) for x in m.groups())
    return datetime(a, mo, d, h, mi)


def parse_data(valor: Any, referencia: date | None = None) -> date | None:
    s = str(valor or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", s)
    if m and referencia:
        d = date(referencia.year, int(m.group(2)), int(m.group(1)))
        if d < referencia:
            d = date(referencia.year + 1, d.month, d.day)
        return d
    return None


def formatar_data(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ---------- JSON ----------
def extrair_json(texto: str) -> Any:
    """Extrai o primeiro objeto JSON de uma resposta de modelo (tolera ```json ... ```)."""
    s = (texto or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    inicio = s.find("{")
    if inicio < 0:
        raise ValueError("resposta sem JSON")
    nivel = 0
    for i in range(inicio, len(s)):
        if s[i] == "{":
            nivel += 1
        elif s[i] == "}":
            nivel -= 1
            if nivel == 0:
                return json.loads(s[inicio : i + 1])
    raise ValueError("JSON incompleto")


def rotulo_campo(campo: str) -> str:
    return campo.replace("_", " ")
