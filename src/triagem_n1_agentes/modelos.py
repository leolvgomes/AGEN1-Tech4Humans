"""Modelos de dados iniciais do sistema."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class StatusSolicitacao(StrEnum):
    """Estados iniciais possíveis para uma solicitação de triagem."""

    RECEBIDA = "recebida"
    EM_ANALISE = "em_analise"
    CONCLUIDA = "concluida"


class CategoriaTriagem(StrEnum):
    """Categorias gerais para classificar uma solicitação recebida."""

    DUVIDA = "duvida"
    SOLICITACAO = "solicitacao"
    INCIDENTE = "incidente"
    OUTRA = "outra"


class Criticidade(StrEnum):
    """Níveis de criticidade usados pelo catálogo de atendimento."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class NivelRiscoSeguranca(StrEnum):
    """Níveis possíveis de risco relacionado à segurança."""

    NENHUM = "nenhum"
    BAIXO = "baixo"
    MEDIO = "medio"
    ALTO = "alto"
    CRITICO = "critico"


class AcaoProposta(StrEnum):
    """Ações que uma decisão pode propor, sem executá-las."""

    RESPONDER_FAQ = "responder_faq"
    SOLICITAR_INFORMACOES = "solicitar_informacoes"
    ABRIR_CHAMADO = "abrir_chamado"
    ENCAMINHAR_APROVACAO = "encaminhar_aprovacao"
    ESCALAR_INCIDENTE = "escalar_incidente"
    REGISTRAR_FERIAS_LEGADO = "registrar_ferias_legado"
    NAO_AGIR = "nao_agir"
    OUTRA = "outra"


class ImpactoOperacional(StrEnum):
    """Escopo do impacto informado de forma estruturada."""

    PRODUTO_FORA_DO_AR_PARA_TODOS = "produto_fora_do_ar_para_todos"
    FUNCAO_IMPORTANTE_INDISPONIVEL_PARA_MUITOS = (
        "funcao_importante_indisponivel_para_muitos"
    )
    MODERADO = "moderado"
    LIMITADO = "limitado"
    MINIMO = "minimo"


class AcaoPermitida(StrEnum):
    """Ações permitidas pela política; nenhuma é executada pelo modelo."""

    ABRIR_INCIDENTE = "abrir_incidente"
    ABRIR_CHAMADO = "abrir_chamado"
    RESPONDER = "responder"


class EstadoOrquestracao(StrEnum):
    """Estados persistidos do ciclo de vida de um evento."""

    RECEBIDO = "RECEBIDO"
    EM_ANALISE = "EM_ANALISE"
    AGUARDANDO_REVISAO = "AGUARDANDO_REVISAO"
    APROVADO = "APROVADO"
    AGUARDANDO_HUMANO = "AGUARDANDO_HUMANO"
    EM_EXECUCAO = "EM_EXECUCAO"
    CONCLUIDO = "CONCLUIDO"
    ERRO_RECUPERAVEL = "ERRO_RECUPERAVEL"
    ERRO_FINAL = "ERRO_FINAL"


class Solicitacao(BaseModel):
    """Representação tipada e inicial de uma solicitação."""

    id: UUID = Field(default_factory=uuid4)
    descricao: str = Field(min_length=1)
    status: StatusSolicitacao = StatusSolicitacao.RECEBIDA
    criada_em: datetime = Field(default_factory=datetime.now)


class BaseDisponivel(BaseModel):
    """Metadados de uma base retornados pela ferramenta listar_bases."""

    nome: str = Field(validation_alias="base")
    descricao: str
    total: int
    chave: str
    campos: list[str]
    pode_registrar: bool
    pode_atualizar: list[str]
    campos_para_registrar: dict[str, str] | None = None
    exemplo_registrar: dict[str, Any] | None = None


class RespostaBases(BaseModel):
    """Resposta tipada da ferramenta listar_bases."""

    status: str
    bases: list[BaseDisponivel]
    agora: str | None = None


class DecisaoTriagem(BaseModel):
    """Decisão proposta para um evento, sem executar a ação indicada."""

    evento: dict[str, Any]
    categoria: CategoriaTriagem
    tipo_catalogo: str | None = None
    criticidade: Criticidade
    faq_utilizada: str | None = None
    campos_encontrados: list[str]
    campos_ausentes: list[str]
    campos_extraidos: dict[str, Any] = Field(default_factory=dict)
    possivel_duplicidade: bool
    risco_seguranca: NivelRiscoSeguranca
    dado_sensivel_presente: bool
    necessita_aprovacao: bool
    acao_proposta: AcaoProposta
    justificativa: str = Field(min_length=1)
    confianca: float = Field(ge=0, le=1)


class EntradaPoliticaTriagem(BaseModel):
    """Dados estruturados usados para aplicar as políticas de triagem."""

    assunto: str
    impacto: ImpactoOperacional
    risco_seguranca: NivelRiscoSeguranca = NivelRiscoSeguranca.NENHUM
    dado_pessoal_sensivel_presente: bool = False


class ResultadoPoliticaTriagem(BaseModel):
    """Resultado tipado das regras de criticidade e escalonamento."""

    criticidade: Criticidade
    exige_incidente: bool
    escalacao_humana: bool
    escalacao_imediata: bool
    acoes_permitidas: list[AcaoPermitida]


class TransicaoOrquestracao(BaseModel):
    """Registro de auditoria de uma transição de estado."""

    evento_id: str
    estado_anterior: EstadoOrquestracao | None
    estado_novo: EstadoOrquestracao
    ocorrida_em: datetime
    detalhe: str | None = None


class ResultadoExecucaoEvento(BaseModel):
    """Resultado do processamento de um evento em lote."""

    evento_id: str
    estado: EstadoOrquestracao
    erro: str | None = None

class RevisaoTriagem(BaseModel):
    """Revisão da decisão proposta pelo Triador, sem executar ações."""

    evento_id: str = Field(min_length=1)

    aprovado: bool

    exige_humano: bool = False

    problemas: list[str] = Field(default_factory=list)

    criticidade_confirmada: Criticidade

    acao_confirmada: AcaoProposta | None = None

    justificativa: str = Field(min_length=1)

    confianca: float = Field(ge=0, le=1)
