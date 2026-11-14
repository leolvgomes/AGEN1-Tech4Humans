"""
Modelos de dados para eventos (e-mails) do servidor MCP
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class CriticalityLevel(str, Enum):
    """Níveis de criticidade de incidentes"""
    P0 = "P0"  # Produto fora do ar para todos os clientes
    P1 = "P1"  # Função importante fora para muitos clientes
    P2 = "P2"  # Falha parcial, com contorno
    P3 = "P3"  # Falha para uma pessoa, dúvida ou melhoria
    P4 = "P4"  # Dúvida ou melhoria


class EventoStatus(str, Enum):
    """Status do evento no servidor MCP"""
    NOVO = "novo"
    ATENDIDO = "atendido"
    DUPLICADO = "duplicado"
    IGNORADO = "ignorado"


class Evento(BaseModel):
    """Modelo de evento (e-mail) do servidor MCP"""
    
    id: str = Field(..., description="ID único do evento")
    tipo: str = Field(..., description="Tipo do evento (email, resposta, etc)")
    de: str = Field(..., description="E-mail de quem enviou")
    para: str = Field(..., description="E-mail de destino")
    assunto: str = Field(..., description="Assunto do evento")
    corpo: str = Field(..., description="Corpo do evento")
    timestamp: datetime = Field(..., description="Data/hora do evento")
    status: str = Field(default="novo", description="Status do evento")
    observacao: Optional[str] = Field(None, description="Observação do agente")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "evt_001",
                "tipo": "email",
                "de": "user@t4h.exemplo",
                "para": "triagem@t4h.exemplo",
                "assunto": "Sistema fora do ar",
                "corpo": "O sistema de vendas está fora do ar desde as 10h",
                "timestamp": "2026-12-07T10:30:00",
                "status": "novo"
            }
        }


class EventoClassification(BaseModel):
    """Resultado da classificação de um evento"""
    
    evento_id: str
    criticality: CriticalityLevel
    category: str
    action: str  # "responder_faq", "abrir_chamado", "abrir_incidente", "escalar", "pedir_info"
    action_reason: str
    requires_human_review: bool = False
    security_concerns: List[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "evento_id": "evt_001",
                "criticality": "P0",
                "category": "Incidente",
                "action": "abrir_incidente",
                "action_reason": "Produto fora do ar para todos os clientes",
                "requires_human_review": True,
                "confidence_score": 0.95
            }
        }


class FAQ(BaseModel):
    """Modelo de resposta do FAQ"""
    
    id: str = Field(..., description="ID da resposta")
    pergunta: str = Field(..., description="Pergunta/padrão")
    resposta: str = Field(..., description="Resposta pronta")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "faq_001",
                "pergunta": "Como resetar senha",
                "resposta": "Clique em 'Esqueci minha senha' na tela de login"
            }
        }


class CatalogItem(BaseModel):
    """Item do catálogo de tipos de chamado"""
    
    tipo: str = Field(..., description="Tipo do chamado")
    time: str = Field(..., description="Time responsável")
    campos_obrigatorios: List[str] = Field(..., description="Campos obrigatórios")
    requer_aprovacao: bool = Field(default=False, description="Requer aprovação")
    prazo_horas: int = Field(..., description="Prazo em horas")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tipo": "suporte_produto",
                "time": "Suporte Técnico",
                "campos_obrigatorios": ["produto", "descricao", "usuarios_afetados"],
                "requer_aprovacao": False,
                "prazo_horas": 24
            }
        }


class Time(BaseModel):
    """Modelo de time da empresa"""
    
    time: str = Field(..., description="Nome do time")
    email: str = Field(..., description="E-mail do time")
    atende: List[str] = Field(..., description="O que o time atende")
    
    class Config:
        json_schema_extra = {
            "example": {
                "time": "Suporte Técnico",
                "email": "suporte@t4h.exemplo",
                "atende": ["Problemas de acesso", "Bugs de produto"]
            }
        }
