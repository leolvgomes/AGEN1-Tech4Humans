"""
Testes dos modelos de dados
"""

import pytest
from datetime import datetime
from src.models import (
    Evento, EventoStatus, CriticalityLevel,
    FAQ, CatalogItem, Time,
    Ticket, TicketType, TicketStatus,
    Incident, IncidentSeverity
)


class TestEventoModel:
    """Testes do modelo Evento"""
    
    def test_create_evento(self):
        """Testa criação de um evento"""
        evento = Evento(
            id="evt_001",
            tipo="email",
            de="user@t4h.exemplo",
            para="triagem@t4h.exemplo",
            assunto="Sistema fora do ar",
            corpo="O sistema está indisponível",
            timestamp=datetime.now()
        )
        
        assert evento.id == "evt_001"
        assert evento.de == "user@t4h.exemplo"
        assert evento.status == "novo"
    
    def test_evento_with_observacao(self):
        """Testa evento com observação"""
        evento = Evento(
            id="evt_002",
            tipo="email",
            de="admin@t4h.exemplo",
            para="triagem@t4h.exemplo",
            assunto="Acesso negado",
            corpo="Não consigo acessar o sistema",
            timestamp=datetime.now(),
            status="atendido",
            observacao="Classificado como P0"
        )
        
        assert evento.status == "atendido"
        assert evento.observacao == "Classificado como P0"


class TestFAQModel:
    """Testes do modelo FAQ"""
    
    def test_create_faq(self):
        """Testa criação de uma resposta FAQ"""
        faq = FAQ(
            id="faq_001",
            pergunta="Como resetar senha",
            resposta="Clique em 'Esqueci minha senha' na tela de login"
        )
        
        assert faq.id == "faq_001"
        assert "senha" in faq.pergunta.lower()


class TestCatalogItemModel:
    """Testes do modelo CatalogItem"""
    
    def test_create_catalog_item(self):
        """Testa criação de um item do catálogo"""
        item = CatalogItem(
            tipo="suporte_produto",
            time="Suporte Técnico",
            campos_obrigatorios=["produto", "descricao"],
            requer_aprovacao=False,
            prazo_horas=24
        )
        
        assert item.tipo == "suporte_produto"
        assert len(item.campos_obrigatorios) == 2


class TestTimeModel:
    """Testes do modelo Time"""
    
    def test_create_time(self):
        """Testa criação de um time"""
        time = Time(
            time="Suporte Técnico",
            email="suporte@t4h.exemplo",
            atende=["Problemas de acesso", "Bugs de produto"]
        )
        
        assert time.time == "Suporte Técnico"
        assert len(time.atende) == 2


class TestTicketModel:
    """Testes do modelo Ticket"""
    
    def test_create_ticket(self):
        """Testa criação de um chamado"""
        ticket = Ticket(
            id="ticket_001",
            ticket_type=TicketType.PRODUCT_SUPPORT,
            title="Suporte ao produto",
            description="Problema com o produto",
            requester_email="user@t4h.exemplo",
            assigned_team="Suporte Técnico"
        )
        
        assert ticket.id == "ticket_001"
        assert ticket.ticket_type == TicketType.PRODUCT_SUPPORT
        assert ticket.status == TicketStatus.OPEN


class TestIncidentModel:
    """Testes do modelo Incident"""
    
    def test_create_incident(self):
        """Testa criação de um incidente"""
        incident = Incident(
            id="incident_001",
            severity=IncidentSeverity.P0,
            title="Produto fora do ar",
            description="Todos os clientes sem acesso",
            affected_systems=["API", "Web App"],
            business_impact="Perda de receita",
            assigned_team="Infraestrutura"
        )
        
        assert incident.id == "incident_001"
        assert incident.severity == IncidentSeverity.P0
        assert len(incident.affected_systems) == 2
