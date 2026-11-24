"""LLM SIMULADO — SÓ PARA TESTES AUTOMATIZADOS DO ENCANAMENTO (MCP, barramento, falhas, tela, canal humano).

Não é usado pelo sistema de verdade (src/main.py exige LLM_API_KEY). Usa heurísticas genéricas por palavra-chave
para devolver JSON no esquema de cada agente, permitindo rodar os testes da Seção 15 sem chave de API.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.agentes import prompts
from src.util import sem_acento, similaridade


def _email(usuario: str) -> str:
    return usuario.split("E-MAIL:", 1)[-1] if "E-MAIL:" in usuario else usuario.split("CASO ORIGINAL:", 1)[-1]


def classificar(texto: str) -> dict[str, Any]:
    t = sem_acento(texto)
    de = re.search(r"de: .*<([^>]+)>", t)
    externo = bool(de and not de.group(1).endswith("@t4h.exemplo"))
    seg = externo or ("senha" in t and ("link" in t or "http" in t)) or "invadi" in t
    if "fora do ar" in t and ("todos" in t or "nenhum cliente" in t):
        imp = "P0"
    elif ("muitos clientes" in t or "varios clientes" in t) and ("nao conseguem" in t or "erro" in t):
        imp = "P1"
    elif ("lent" in t or "demora" in t) and ("contorno" in t or "da para" in t):
        imp = "P2"
    else:
        imp = "P3"
    if imp in ("P0", "P1", "P2"):
        tipo = "incidente"
    elif "?" in t and re.search(r"\b(como|qual|quando|onde|posso)\b", t) and not re.search(r"\b(preciso|quero|solicito|gostaria)\b", t):
        tipo = "duvida"
    else:
        tipo = "pedido"
    return {"seguranca": seg, "impacto": imp, "tipo_caso": tipo}


def triagem(usuario: str) -> dict[str, Any]:
    texto = _email(usuario)
    t = sem_acento(texto)
    c = classificar(texto)
    cat, campos = None, {}
    datas = re.findall(r"\d{2}/\d{2}/\d{4}", texto)
    if "ferias" in t:
        cat = "Férias"
        if len(datas) >= 2:
            campos = {"data_de_inicio": datas[0], "data_de_fim": datas[1]}
    elif "acesso" in t:
        cat = "Acesso a sistema"
        m = re.search(r"\b(crm|erp|financeiro|repositorio)\b", t)
        n = re.search(r"\b(leitura|edicao|escrita|admin)\b", t)
        j = re.search(r"(para [^.\n]{8,})", texto, re.I)
        campos = {k: v for k, v in {"sistema": m and m.group(1), "nivel_de_acesso": n and n.group(1), "justificativa": j and j.group(1)}.items() if v}
    elif "reembolso" in t:
        cat = "Reembolso"
    elif re.search(r"\b(mouse|teclado)\b", t) and "defeito" in t:
        cat = "Troca de equipamento"
        item = re.search(r"\b(mouse|teclado)\b", t)
        pat = re.search(r"patrimonio\s*(\d+)", t)
        dfe = re.search(r"(o clique[^.]*|nao liga[^.]*|falha[^.]*)", t)
        campos = {k: v for k, v in {"item": item and item.group(1), "patrimonio": pat and pat.group(1), "defeito": dfe and dfe.group(1)}.items() if v}
    elif c["impacto"] != "P3" or re.search(r"\b(portal|app|painel)\b", t):
        cat = "Suporte a produto"
        prod = re.search(r"(portal do cliente|app agenda|painel de vendas)", t)
        campos = {k: v for k, v in {"produto": prod and prod.group(1), "o_que_aconteceu": texto.strip()[:150], "desde_quando": "hoje" if re.search(r"\b(hoje|desde|ontem)\b", t) else None}.items() if v}
    else:
        cat = "Outros pedidos"
        campos = {"descricao": texto.strip()[:200]}
    prod = re.search(r"(portal do cliente|app agenda|painel de vendas)", t)
    return {
        **c, "categoria_seguranca": "seguranca" if c["seguranca"] else None, "motivo_seguranca": "sinal de golpe" if c["seguranca"] else None,
        "urgencia_falsa": "urgente" in t and c["impacto"] == "P3", "tipo_catalogo": cat if c["tipo_caso"] == "pedido" else None,
        "campos": campos, "campos_faltantes": [], "produto": prod.group(1).title() if prod else None, "sintomas": texto.strip()[:120],
        "impacto_descricao": "clientes afetados", "contorno": None, "time_responsavel": "Produto" if prod else "Operações",
        "resumo": texto.strip().splitlines()[0][:100] if texto.strip() else "", "pergunta": texto.strip()[:200], "confianca": 0.9,
        "motivo": f"simulado: {c['impacto']} {c['tipo_caso']}",
    }


class LLMSimulado:
    def __init__(self) -> None:
        self.chamadas = 0

    async def json(self, agente, sistema, usuario, esquema, revisor=False, caso_id=None):
        self.chamadas += 1
        if sistema == prompts.TRIADOR:
            dados = triagem(usuario)
        elif sistema == prompts.REVISOR_CLASSIFICAR:
            dados = {**classificar(_email(usuario)), "motivo": "simulado"}
        elif sistema == prompts.REVISOR_CONFERIR:
            dados = {"ok": True, "explicacao": "simulado"}
        elif sistema == prompts.PESQUISADOR_DUPLICADO:
            caso = usuario.split("CANDIDATOS ABERTOS:")[0]
            de = re.search(r"<([^>]+)>", caso)
            dados = {"duplicado": False, "registro_id": None, "similaridade": 0.0, "motivo": "simulado: nada igual"}
            for linha in usuario.split("CANDIDATOS ABERTOS:")[1].splitlines():
                if not linha.strip():
                    continue
                cand = eval(linha)  # noqa: S307 - linha gerada pelo próprio teste (repr de dict)
                if de and cand.get("solicitante") == de.group(1) and similaridade(caso, str(cand.get("resumo"))) >= 0.3:
                    dados = {"duplicado": True, "registro_id": cand["id"], "similaridade": 0.85, "motivo": "simulado: mesmo solicitante e assunto"}
                    break
                if cand.get("base") == "incidentes" and cand.get("produto") and sem_acento(cand["produto"]) in sem_acento(caso):
                    dados = {"duplicado": True, "registro_id": cand["id"], "similaridade": 0.8, "motivo": "simulado: mesmo produto fora"}
                    break
        elif sistema == prompts.PESQUISADOR_FAQ:
            pergunta = usuario.split("PERGUNTA:")[1].split("\n")[0]
            melhor, nota = None, 0.0
            for fid, perg in re.findall(r"\[(FAQ-\d+)\] P: (.*)", usuario):
                s = similaridade(pergunta, perg)
                if s > nota:
                    melhor, nota = fid, s
            dados = {"encontrou": nota >= 0.5, "faq_id": melhor if nota >= 0.5 else None, "confianca": 0.9 if nota >= 0.5 else 0.2, "time_responsavel": "Operações", "motivo": f"simulado {nota:.2f}"}
        elif sistema == prompts.ESCALADOR_RESUMIR:
            dados = {"resumo": "Caso escalado pelo time (simulado).", "recomendacao_do_time": "Avaliar com o time responsável."}
        elif sistema == prompts.OPERADOR_MAPEAR:
            campos = eval(usuario.split("CAMPOS DO FORMULÁRIO: ")[1].split("\n")[0])  # noqa: S307
            mapa = {}
            for c in campos:
                r = sem_acento(c["rotulo"])
                for chave, p in (("agente", "lancando"), ("email", "e-mail"), ("inicio", "primeiro"), ("fim", "ultimo"), ("evento", "evento")):
                    if p in r:
                        mapa[c["id"]] = chave
            dados = {"mapa": mapa, "motivo": "simulado"}
        else:
            dados = {}
        return esquema.model_validate(json.loads(json.dumps(dados)))

    async def texto(self, agente, sistema, usuario, caso_id=None):
        return ""  # força o modelo pronto do Executor

    async def testar(self):
        return "ok"
