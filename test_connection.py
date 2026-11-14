"""
Script para testar a conexão com o servidor MCP
"""

import logging
import sys
from src.config import get_settings
from src.utils import setup_logging
from src.services import MCPClient

logger = logging.getLogger(__name__)


def test_connection():
    """Testa a conexão com o servidor MCP"""
    
    try:
        # Carregar configurações
        settings = get_settings()
        
        # Configurar logging
        setup_logging(settings)
        
        logger.info("=" * 80)
        logger.info("Testando conexão com servidor MCP")
        logger.info("=" * 80)
        logger.info(f"URL do servidor: {settings.mcp_server_url}")
        logger.info("")
        
        # Inicializar cliente MCP
        mcp_client = MCPClient(settings)
        
        # Testar endpoints
        logger.info("Testando endpoints...")
        logger.info("-" * 80)
        
        # Teste 1: FAQ
        logger.info("1. Buscando FAQ...")
        try:
            faq = mcp_client.get_faq()
            logger.info(f"   ✓ FAQ carregado com sucesso ({len(faq)} respostas)")
        except Exception as e:
            logger.error(f"   ✗ Erro ao buscar FAQ: {e}")
        
        # Teste 2: Catálogo
        logger.info("2. Buscando Catálogo...")
        try:
            catalogo = mcp_client.get_catalogo()
            logger.info(f"   ✓ Catálogo carregado com sucesso ({len(catalogo)} tipos)")
        except Exception as e:
            logger.error(f"   ✗ Erro ao buscar Catálogo: {e}")
        
        # Teste 3: Times
        logger.info("3. Buscando Times...")
        try:
            times = mcp_client.get_times()
            logger.info(f"   ✓ Times carregados com sucesso ({len(times)} times)")
        except Exception as e:
            logger.error(f"   ✗ Erro ao buscar Times: {e}")
        
        # Teste 4: Eventos
        logger.info("4. Buscando Eventos...")
        try:
            eventos = mcp_client.fetch_eventos(limit=5)
            logger.info(f"   ✓ Eventos carregados com sucesso ({len(eventos)} eventos)")
            
            if eventos:
                logger.info("\n   Primeiros eventos:")
                for evento in eventos[:3]:
                    logger.info(f"   - {evento.id}: {evento.assunto}")
        except Exception as e:
            logger.error(f"   ✗ Erro ao buscar Eventos: {e}")
        
        # Teste 5: Chamados
        logger.info("5. Buscando Chamados...")
        try:
            chamados = mcp_client.list_chamados()
            logger.info(f"   ✓ Chamados carregados com sucesso ({len(chamados)} chamados)")
        except Exception as e:
            logger.error(f"   ✗ Erro ao buscar Chamados: {e}")
        
        # Teste 6: Incidentes
        logger.info("6. Buscando Incidentes...")
        try:
            incidentes = mcp_client.list_incidentes()
            logger.info(f"   ✓ Incidentes carregados com sucesso ({len(incidentes)} incidentes)")
        except Exception as e:
            logger.error(f"   ✗ Erro ao buscar Incidentes: {e}")
        
        logger.info("-" * 80)
        logger.info("✓ Teste de conexão concluído com sucesso!")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Erro ao testar conexão: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    test_connection()
