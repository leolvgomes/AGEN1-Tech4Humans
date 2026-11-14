"""
Ponto de entrada da aplicação
Hackathon Tech4Hum - Triagem N1 de Chamados e Incidentes
"""

import logging
import sys
from src.config import get_settings
from src.utils import setup_logging
from src.services import MCPClient
from src.agents import ClassifierAgent

logger = logging.getLogger(__name__)


def main():
    """Função principal da aplicação"""
    
    try:
        # Carregar configurações
        settings = get_settings()
        
        # Configurar logging
        setup_logging(settings)
        logger.info("=" * 80)
        logger.info("Iniciando aplicação de Triagem N1 de Chamados e Incidentes")
        logger.info("=" * 80)
        
        # Inicializar cliente MCP
        logger.info("Conectando ao servidor MCP...")
        mcp_client = MCPClient(settings)
        
        # Carregar dados do servidor
        logger.info("Carregando FAQ, Catálogo e Times...")
        faq = mcp_client.get_faq()
        catalogo = mcp_client.get_catalogo()
        times = mcp_client.get_times()
        
        logger.info(f"✓ FAQ: {len(faq)} respostas")
        logger.info(f"✓ Catálogo: {len(catalogo)} tipos de chamado")
        logger.info(f"✓ Times: {len(times)} times")
        
        # Inicializar agente classificador
        logger.info("Inicializando agente classificador...")
        classifier_agent = ClassifierAgent(settings, faq=faq, catalogo=catalogo, times=times)
        
        # Buscar eventos do servidor MCP
        logger.info("Buscando eventos do servidor MCP...")
        eventos = mcp_client.fetch_eventos(limit=10)
        
        if not eventos:
            logger.warning("Nenhum evento encontrado no servidor")
            return
        
        logger.info(f"✓ Encontrados {len(eventos)} eventos")
        logger.info("")
        
        # Classificar eventos
        logger.info("Iniciando classificação de eventos...")
        logger.info("-" * 80)
        classifications = classifier_agent.batch_classify(eventos)
        
        logger.info("-" * 80)
        logger.info(f"✓ Classificação concluída: {len(classifications)}/{len(eventos)} eventos processados")
        logger.info("")
        
        # Exibir resultados
        logger.info("RESULTADOS DA CLASSIFICAÇÃO:")
        logger.info("=" * 80)
        
        for i, classification in enumerate(classifications, 1):
            logger.info(f"\n[{i}] Evento: {classification.evento_id}")
            logger.info(f"    Criticidade: {classification.criticality}")
            logger.info(f"    Categoria: {classification.category}")
            logger.info(f"    Ação: {classification.action}")
            logger.info(f"    Motivo: {classification.action_reason}")
            logger.info(f"    Confiança: {classification.confidence_score:.1%}")
            if classification.requires_human_review:
                logger.warning(f"    ⚠️  REQUER REVISÃO HUMANA")
            if classification.security_concerns:
                logger.warning(f"    🔒 Preocupações de segurança: {', '.join(classification.security_concerns)}")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ Aplicação finalizada com sucesso")
        logger.info("=" * 80)
    
    except KeyboardInterrupt:
        logger.info("Aplicação interrompida pelo usuário")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Erro na aplicação: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
