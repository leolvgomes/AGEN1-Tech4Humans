#!/usr/bin/env python
"""
Script para executar a aplicação de Triagem N1
Uso: python run.py [--test-connection] [--limit N]
"""

import sys
import argparse
import logging
from src.config import get_settings
from src.utils import setup_logging
from src.services import MCPClient
from src.agents import ClassifierAgent

logger = logging.getLogger(__name__)


def run_classifier(limit: int = 10):
    """Executa o classificador de eventos"""
    
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
        logger.info(f"Buscando eventos do servidor MCP (limite: {limit})...")
        eventos = mcp_client.fetch_eventos(limit=limit)
        
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


def main():
    """Função principal"""
    
    parser = argparse.ArgumentParser(
        description="Aplicação de Triagem N1 de Chamados e Incidentes"
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Testa a conexão com o servidor MCP"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Número máximo de eventos a processar (padrão: 10)"
    )
    
    args = parser.parse_args()
    
    if args.test_connection:
        test_connection()
    else:
        run_classifier(limit=args.limit)


if __name__ == "__main__":
    main()
