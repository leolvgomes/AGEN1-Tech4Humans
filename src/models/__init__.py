"""Modelos de dados da aplicação"""

from .email import Evento, EventoStatus, CriticalityLevel, EventoClassification, FAQ, CatalogItem, Time
from .ticket import Ticket, Incident, TicketType, TicketStatus, IncidentSeverity, TicketCatalog

__all__ = [
    "Evento",
    "EventoStatus",
    "CriticalityLevel",
    "EventoClassification",
    "FAQ",
    "CatalogItem",
    "Time",
    "Ticket",
    "Incident",
    "TicketType",
    "TicketStatus",
    "IncidentSeverity",
    "TicketCatalog",
]
