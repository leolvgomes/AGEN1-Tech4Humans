"""
Modelos de dados para chamados e incidentes
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class TicketType(str, Enum):
    """Tipos de chamado disponíveis no catálogo"""
    SYSTEM_ACCESS = "system_access"
    EQUIPMENT = "equipment"
    VACATION = "vacation"
    PRODUCT_SUPPORT = "product_support"
    INCIDENT = "incident"
    GENERAL_REQUEST = "general_request"
    SECURITY_ALERT = "security_alert"
    DATA_REQUEST = "data_request"


class TicketStatus(str, Enum):
    """Status do chamado"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_INFO = "waiting_info"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSeverity(str, Enum):
    """Severidade do incidente"""
    P0 = "P0"  # Crítico - Produto fora do ar para todos
    P1 = "P1"  # Alto - Função importante fora para muitos
    P2 = "P2"  # Médio - Falha parcial com contorno
    P3 = "P3"  # Baixo - Falha para uma pessoa
    P4 = "P4"  # Mínimo - Dúvida ou melhoria


class Ticket(BaseModel):
    """Modelo de chamado"""
    
    id: str = Field(..., description="ID único do chamado")
    ticket_type: TicketType = Field(..., description="Tipo de chamado")
    status: TicketStatus = Field(default=TicketStatus.OPEN, description="Status atual")
    
    # Informações básicas
    title: str = Field(..., description="Título do chamado")
    description: str = Field(..., description="Descrição detalhada")
    requester_email: str = Field(..., description="E-mail de quem solicitou")
    requester_name: Optional[str] = Field(None, description="Nome de quem solicitou")
    
    # Atribuição
    assigned_team: str = Field(..., description="Time responsável")
    assigned_to: Optional[str] = Field(None, description="Pessoa responsável")
    
    # Campos obrigatórios por tipo
    required_fields: Dict[str, Any] = Field(default_factory=dict, description="Campos obrigatórios preenchidos")
    
    # Datas
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    due_date: Optional[datetime] = Field(None, description="Prazo para resolução")
    
    # Rastreamento
    source_email_id: Optional[str] = Field(None, description="ID do e-mail que originou o chamado")
    requires_approval: bool = Field(default=False, description="Requer aprovação")
    approved_by: Optional[str] = Field(None, description="Aprovado por")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "ticket_001",
                "ticket_type": "product_support",
                "status": "open",
                "title": "Sistema de vendas fora do ar",
                "description": "O sistema de vendas está indisponível desde as 10h",
                "requester_email": "user@company.com",
                "assigned_team": "Suporte Técnico",
                "source_email_id": "email_001"
            }
        }


class Incident(BaseModel):
    """Modelo de incidente"""
    
    id: str = Field(..., description="ID único do incidente")
    severity: IncidentSeverity = Field(..., description="Severidade do incidente")
    status: TicketStatus = Field(default=TicketStatus.OPEN, description="Status atual")
    
    # Informações básicas
    title: str = Field(..., description="Título do incidente")
    description: str = Field(..., description="Descrição detalhada")
    affected_systems: List[str] = Field(default_factory=list, description="Sistemas afetados")
    affected_users_count: Optional[int] = Field(None, description="Número de usuários afetados")
    
    # Impacto
    business_impact: str = Field(..., description="Impacto no negócio")
    estimated_resolution_time: Optional[str] = Field(None, description="Tempo estimado de resolução")
    
    # Atribuição
    assigned_team: str = Field(..., description="Time responsável")
    assigned_to: Optional[str] = Field(None, description="Pessoa responsável")
    escalated_to: Optional[str] = Field(None, description="Escalado para")
    
    # Datas
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = Field(None, description="Data de resolução")
    
    # Rastreamento
    source_email_id: Optional[str] = Field(None, description="ID do e-mail que originou o incidente")
    related_tickets: List[str] = Field(default_factory=list, description="Chamados relacionados")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "incident_001",
                "severity": "P0",
                "status": "open",
                "title": "Produto fora do ar",
                "description": "Todos os clientes sem acesso ao produto",
                "affected_systems": ["API", "Web App"],
                "affected_users_count": 5000,
                "business_impact": "Perda de receita e reputação",
                "assigned_team": "Infraestrutura",
                "source_email_id": "email_001"
            }
        }


class TicketCatalog(BaseModel):
    """Catálogo de tipos de chamado com campos obrigatórios"""
    
    type: TicketType
    name: str
    description: str
    assigned_team: str
    team_email: str
    required_fields: List[str]
    approval_required: bool
    sla_hours: int  # Service Level Agreement em horas
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "product_support",
                "name": "Suporte a Produto",
                "description": "Problemas e dúvidas sobre os produtos",
                "assigned_team": "Suporte Técnico",
                "team_email": "support@company.com",
                "required_fields": ["product_name", "issue_description", "affected_users"],
                "approval_required": False,
                "sla_hours": 24
            }
        }
