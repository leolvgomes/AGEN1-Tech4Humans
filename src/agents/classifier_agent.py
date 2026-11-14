"""
Agente de classificação de eventos
Responsável por analisar eventos (e-mails) e classificá-los por urgência/importância
"""

import logging
import json
from typing import Optional, List
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from src.models import Evento, EventoClassification, CriticalityLevel, FAQ, CatalogItem, Time
from src.config import Settings

logger = logging.getLogger(__name__)


class ClassifierAgent:
    """Agente responsável por classificar eventos"""
    
    def __init__(self, settings: Settings, faq: List[FAQ] = None, 
                 catalogo: List[CatalogItem] = None, times: List[Time] = None):
        self.settings = settings
        self.faq = faq or []
        self.catalogo = catalogo or []
        self.times = times or []
        
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=settings.agent_temperature,
            max_tokens=settings.agent_max_tokens
        )
        self.parser = PydanticOutputParser(pydantic_object=EventoClassification)
        logger.info("ClassifierAgent inicializado")
    
    def classify_evento(self, evento: Evento) -> Optional[EventoClassification]:
        """
        Classifica um evento analisando seu conteúdo
        
        Retorna:
            EventoClassification com criticidade, categoria e ação recomendada
        """
        try:
            prompt = self._create_classification_prompt(evento)
            response = self.llm.invoke(prompt)
            
            classification = self.parser.parse(response.content)
            logger.info(f"Evento {evento.id} classificado como {classification.criticality}")
            
            return classification
        
        except Exception as e:
            logger.error(f"Erro ao classificar evento {evento.id}: {e}")
            return None
    
    def _create_classification_prompt(self, evento: Evento) -> ChatPromptTemplate:
        """Cria o prompt para classificação do evento"""
        
        format_instructions = self.parser.get_format_instructions()
        
        # Preparar contexto do FAQ
        faq_context = "Respostas prontas disponíveis:\n"
        for faq in self.faq[:5]:  # Limitar a 5 para não sobrecarregar o prompt
            faq_context += f"- {faq.pergunta}: {faq.resposta}\n"
        
        # Preparar contexto do catálogo
        catalogo_context = "Tipos de chamado disponíveis:\n"
        for item in self.catalogo[:5]:
            catalogo_context += f"- {item.tipo} (Time: {item.time})\n"
        
        prompt_text = f"""
Você é um agente especializado em triagem de eventos internos de uma empresa de tecnologia (T4H).
Sua tarefa é analisar o evento abaixo e classificá-lo corretamente.

{faq_context}

{catalogo_context}

IMPORTANTE - Regras de Criticidade (baseadas em IMPACTO, não em urgência declarada):
- P0: Produto fora do ar para TODOS os clientes → Abrir incidente e escalar na hora
- P1: Função importante fora para MUITOS clientes → Abrir incidente e escalar na hora
- P2: Falha parcial com contorno → Abrir incidente
- P3: Falha para uma pessoa, dúvida ou melhoria → Chamado de Suporte ou resposta
- P4: Dúvida ou melhoria → Resposta ou FAQ

IMPORTANTE - Segurança:
- Se o evento menciona golpe, vazamento, acesso indevido ou dados pessoais sensíveis → Marcar para revisão humana
- Nunca responda sozinho em casos de segurança

Evento a classificar:
De: {evento.de}
Para: {evento.para}
Assunto: {evento.assunto}
Corpo: {evento.corpo}
Timestamp: {evento.timestamp}

Analise o evento e retorne a classificação em JSON com os seguintes campos:
- evento_id: ID do evento
- criticality: Nível de criticidade (P0, P1, P2, P3 ou P4)
- category: Categoria do pedido (ex: "Incidente", "Suporte a Produto", "Acesso a Sistema", etc)
- action: Ação recomendada ("responder_faq", "abrir_chamado", "abrir_incidente", "escalar", "pedir_info")
- action_reason: Motivo da ação em uma frase
- requires_human_review: true se precisa revisão humana, false caso contrário
- security_concerns: Lista de preocupações de segurança (vazio se nenhuma)
- confidence_score: Confiança da classificação de 0.0 a 1.0

{format_instructions}
"""
        
        return ChatPromptTemplate.from_template(prompt_text)
    
    def batch_classify(self, eventos: List[Evento]) -> List[EventoClassification]:
        """Classifica um lote de eventos"""
        classifications = []
        
        for evento in eventos:
            classification = self.classify_evento(evento)
            if classification:
                classifications.append(classification)
        
        logger.info(f"Classificados {len(classifications)}/{len(eventos)} eventos")
        return classifications
