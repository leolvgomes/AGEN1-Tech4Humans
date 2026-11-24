"""Esquemas das mensagens entre agentes (Seção 6 da especificação), com validação Pydantic."""

from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..util import sinal_coletivo

AGENTES = ("despachante", "triador", "pesquisador", "revisor", "executor", "operador_tela", "escalador")
NomeAgente = Literal["despachante", "triador", "pesquisador", "revisor", "executor", "operador_tela", "escalador", "canal_humano"]

TipoMensagem = Literal[
    "CASO_NOVO", "PESQUISAR_DUPLICADO", "RESULTADO_DUPLICADO", "PESQUISAR_FAQ", "RESULTADO_FAQ",
    "PROPOSTA", "REVISAO", "PEDIR_INFO", "EXECUTAR", "ESCALAR", "PEDIR_APROVACAO", "DECISAO_HUMANA",
    "LANCAR_FERIAS", "RESULTADO",
    # extensões documentadas em DECISOES.md
    "COBRANCA", "CONFIRMAR_FERIAS",
]

# Quem pode mandar cada tipo de mensagem para quem (o barramento recusa o resto).
ROTAS: dict[str, set[tuple[str, str]]] = {
    "CASO_NOVO": {("despachante", "triador")},
    "PESQUISAR_DUPLICADO": {("triador", "pesquisador")},
    "RESULTADO_DUPLICADO": {("pesquisador", "triador")},
    "PESQUISAR_FAQ": {("triador", "pesquisador")},
    "RESULTADO_FAQ": {("pesquisador", "triador")},
    "PROPOSTA": {("triador", "revisor"), ("pesquisador", "revisor")},
    "REVISAO": {("revisor", "despachante"), ("executor", "despachante")},
    "PEDIR_INFO": {("triador", "executor")},
    "EXECUTAR": {("revisor", "executor")},
    "ESCALAR": {("triador", "escalador"), ("executor", "escalador"), ("despachante", "escalador"), ("operador_tela", "escalador"), ("revisor", "escalador")},
    "PEDIR_APROVACAO": {("executor", "escalador")},
    "DECISAO_HUMANA": {("canal_humano", "escalador"), ("escalador", "executor")},
    "LANCAR_FERIAS": {("executor", "operador_tela")},
    "RESULTADO": {("executor", "despachante"), ("operador_tela", "despachante"), ("escalador", "despachante")},
    "COBRANCA": {("despachante", "escalador")},
    "CONFIRMAR_FERIAS": {("despachante", "executor")},
}

_seq = itertools.count(1)


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{datetime.now():%H%M%S}-{next(_seq):05d}"


class Envelope(BaseModel):
    id: str = Field(default_factory=lambda: novo_id("msg"))
    de: NomeAgente
    para: NomeAgente
    tipo: TipoMensagem
    caso_id: str
    ts: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def rota_valida(self) -> "Envelope":
        if (self.de, self.para) not in ROTAS[self.tipo]:
            raise ValueError(f"rota não permitida: {self.tipo} de {self.de} para {self.para}")
        modelo = PAYLOADS.get(self.tipo)
        if modelo:
            modelo.model_validate(self.payload)
        return self


Impacto = Literal["P0", "P1", "P2", "P3", "P4", "nenhum"]


def _norm_impacto(v: Any) -> str:
    v = str(v or "nenhum").strip().upper()
    return v if v in ("P0", "P1", "P2", "P3", "P4") else "nenhum"


def _norm_alcance(v: Any) -> Optional[str]:
    v = str(v or "").strip().lower().replace(" ", "_")
    return v if v in ("todos_clientes", "muitos_clientes", "alguns_clientes", "uma_pessoa", "nenhum") else None


def rebaixar_se_individual(impacto: str, alcance: Optional[str], texto: str) -> str:
    """Falha de uma única pessoa é P3 (Seção 7.2). Só vale para P1/P2, quando o próprio modelo disse que afeta
    uma pessoa (ou ninguém) E o texto não traz nenhum sinal coletivo. P0 nunca é rebaixado."""
    if impacto in ("P1", "P2") and alcance in ("uma_pessoa", "nenhum") and not sinal_coletivo(texto):
        return "P3"
    return impacto


def _norm_tipo(v: Any) -> str:
    v = str(v or "pedido").strip().lower().replace("ú", "u")
    return v if v in ("incidente", "duvida", "pedido") else "pedido"


class Triagem(BaseModel):
    seguranca: bool = False
    motivo_seguranca: Optional[str] = None
    categoria_seguranca: Optional[Literal["seguranca", "dado_sensivel"]] = None
    impacto: Impacto = "nenhum"
    alcance: Optional[str] = None
    tipo_caso: Literal["incidente", "duvida", "pedido"] = "pedido"
    urgencia_falsa: bool = False
    tipo_catalogo: Optional[str] = None
    campos: dict[str, Any] = Field(default_factory=dict)
    campos_faltantes: list[str] = Field(default_factory=list)
    produto: Optional[str] = None
    sintomas: Optional[str] = None
    impacto_descricao: Optional[str] = None
    contorno: Optional[str] = None
    time_responsavel: Optional[str] = None
    resumo: str = ""
    pergunta: Optional[str] = None
    confianca: float = 0.0
    motivo: str = ""

    @field_validator("impacto", mode="before")
    @classmethod
    def _imp(cls, v):
        return _norm_impacto(v)

    @field_validator("tipo_caso", mode="before")
    @classmethod
    def _tipo(cls, v):
        return _norm_tipo(v)

    @field_validator("alcance", mode="before")
    @classmethod
    def _alc(cls, v):
        return _norm_alcance(v)

    @field_validator("confianca", mode="before")
    @classmethod
    def _conf(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("campos", mode="before")
    @classmethod
    def _campos(cls, v):
        return {k: x for k, x in (v or {}).items() if x not in (None, "", [], {})} if isinstance(v, dict) else {}

    @field_validator("campos_faltantes", mode="before")
    @classmethod
    def _falt(cls, v):
        return [str(x) for x in v] if isinstance(v, list) else []


AcaoProposta = Literal["abrir_incidente", "vincular_duplicado", "responder_faq", "encaminhar_time", "registrar_chamado", "lancar_ferias"]


class Proposta(BaseModel):
    proposta_id: str
    caso_id: str
    autor: Literal["triador", "pesquisador"]
    acao: AcaoProposta
    parametros: dict[str, Any] = Field(default_factory=dict)
    criticidade: Optional[Literal["P0", "P1", "P2"]] = None
    exige_aprovacao_humana: bool = False
    motivo: str


class ClassificacaoIndependente(BaseModel):
    seguranca: bool = False
    impacto: Impacto = "nenhum"
    alcance: Optional[str] = None
    tipo_caso: Literal["incidente", "duvida", "pedido"] = "pedido"
    motivo: str = ""

    @field_validator("alcance", mode="before")
    @classmethod
    def _alc(cls, v):
        return _norm_alcance(v)

    @field_validator("impacto", mode="before")
    @classmethod
    def _imp(cls, v):
        return _norm_impacto(v)

    @field_validator("tipo_caso", mode="before")
    @classmethod
    def _tipo(cls, v):
        return _norm_tipo(v)


class Revisao(BaseModel):
    proposta_id: str
    classificacao_independente: ClassificacaoIndependente = Field(default_factory=ClassificacaoIndependente)
    decisao: Literal["aprovar", "devolver"]
    problemas: list[str] = Field(default_factory=list)
    motivo: str = ""
    categorias: list[str] = Field(default_factory=list)
    objecoes_ignoradas: list[str] = Field(default_factory=list)
    exigir_escalacao: bool = False


CategoriaEscalacao = Literal["seguranca", "dado_sensivel", "incidente_p0", "incidente_p1", "aprovacao", "revisao_esgotada", "erro_repetido"]


class Escalacao(BaseModel):
    escalacao_id: str
    caso_id: str
    evento_id: Optional[str] = None
    categoria: CategoriaEscalacao
    urgencia: Literal["imediata", "alta", "normal"] = "normal"
    resumo: str
    o_que_ja_foi_feito: list[str] = Field(default_factory=list)
    recomendacao_do_time: str = ""
    dados_sensiveis_mascarados: bool = True
    status: Literal["pendente", "em_atendimento", "resolvida"] = "pendente"


class PedidoAprovacao(BaseModel):
    aprovacao_id: str
    caso_id: str
    acao: dict[str, Any]
    justificativa: str
    status: Literal["pendente", "aprovada", "recusada"] = "pendente"
    decidido_por: Optional[str] = None
    decidido_em: Optional[str] = None
    comentario: Optional[str] = None


class DecisaoHumana(BaseModel):
    aprovacao_id: str
    decisao: Literal["aprovada", "recusada"]
    decidido_por: str
    decidido_em: str
    comentario: Optional[str] = None


class PedidoEscalar(BaseModel):
    categoria: CategoriaEscalacao
    motivo: str
    urgencia: Literal["imediata", "alta", "normal"] = "normal"
    detalhes: dict[str, Any] = Field(default_factory=dict)


class ResultadoFinal(BaseModel):
    estado: Literal["CONCLUIDO", "ESCALADO", "AGUARDANDO_SOLICITANTE", "AGUARDANDO_APROVACAO", "ERRO"]
    acao: str
    sucesso: bool = True
    detalhes: dict[str, Any] = Field(default_factory=dict)
    motivo: str = ""


class ResultadoTela(BaseModel):
    sucesso: bool
    comprovante: Optional[str] = None
    motivo: str = ""


PAYLOADS: dict[str, type[BaseModel]] = {
    "PROPOSTA": Proposta,
    "REVISAO": Revisao,
    "ESCALAR": PedidoEscalar,
    "DECISAO_HUMANA": DecisaoHumana,
    "RESULTADO": ResultadoFinal,
}

EstadoCaso = Literal[
    "NOVO", "EM_TRIAGEM", "AGUARDANDO_SOLICITANTE", "EM_REVISAO", "AGUARDANDO_APROVACAO", "EXECUTANDO", "ESCALADO", "CONCLUIDO", "ERRO"
]
ESTADOS_FINAIS = ("ESCALADO", "CONCLUIDO", "ERRO")


class Caso(BaseModel):
    caso_id: str
    rodada: int
    evento_id: str
    eventos: list[str] = Field(default_factory=list)
    origem: str = "servidor"
    remetente: str = ""
    nome: str = ""
    assunto: str = ""
    corpo: str = ""
    complementos: list[dict[str, str]] = Field(default_factory=list)
    recebido_em: str = ""
    estado: EstadoCaso = "NOVO"
    caso_anterior: Optional[str] = None
    contexto_anterior: Optional[str] = None
    triagem: Optional[dict[str, Any]] = None
    propostas: list[dict[str, Any]] = Field(default_factory=list)
    revisoes: list[dict[str, Any]] = Field(default_factory=list)
    devolucoes: int = 0
    problemas_revisor: list[str] = Field(default_factory=list)
    pedidos_info: int = 0
    aprovacao: Optional[dict[str, Any]] = None
    execucao: Optional[dict[str, Any]] = None
    escalacao: Optional[dict[str, Any]] = None
    registro_criado: Optional[dict[str, Any]] = None
    historico: list[dict[str, Any]] = Field(default_factory=list)

    def texto_completo(self) -> str:
        partes = [f"Assunto: {self.assunto}", f"De: {self.nome} <{self.remetente}>", "", self.corpo]
        for c in self.complementos:
            partes += ["", f"--- Mensagem posterior do solicitante ({c.get('evento_id')}): {c.get('assunto', '')}", c.get("corpo", "")]
        return "\n".join(partes)

    def anotar(self, agente: str, acao: str, motivo: str, ts: str = "") -> None:
        self.historico.append({"ts": ts or datetime.now().isoformat(timespec="seconds"), "agente": agente, "acao": acao, "motivo": motivo})
