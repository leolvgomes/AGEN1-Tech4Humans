#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demo simples - Conecta ao servidor MCP e mostra os dados
Sem dependências de LangChain para evitar conflitos de versão
"""

import requests
import json
import logging
import sys
from datetime import datetime

# Configurar encoding para Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações
MCP_SERVER_URL = "http://localhost:8765/mcp"
TIMEOUT = 10


def make_request(method, endpoint):
    """Faz uma requisição HTTP ao servidor MCP"""
    url = f"{MCP_SERVER_URL}{endpoint}"
    try:
        logger.debug(f"Requisição {method} para {url}")
        if method == "GET":
            response = requests.get(url, timeout=TIMEOUT)
        else:
            response = requests.post(url, timeout=TIMEOUT)
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ Erro de conexão: {e}")
        logger.error(f"   Verifique se o servidor MCP está rodando em {MCP_SERVER_URL}")
        return None
    except Exception as e:
        logger.error(f"❌ Erro: {e}")
        return None


def print_section(title):
    """Imprime um título de seção"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_subsection(title):
    """Imprime um subtítulo"""
    print(f"\n{title}")
    print("-" * 80)


def safe_print(text):
    """Imprime texto com tratamento de encoding"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('utf-8', errors='replace').decode('utf-8'))


def demo():
    """Executa a demo"""
    
    print_section("DEMO - Triagem N1 de Chamados e Incidentes")
    logger.info("Iniciando demo...")
    
    # Teste 1: FAQ
    print_subsection("[1] BUSCANDO FAQ (Respostas Prontas)")
    logger.info("Buscando FAQ...")
    faq_data = make_request("GET", "/faq")
    
    if faq_data:
        faq_list = faq_data.get("faq", [])
        logger.info(f"✅ FAQ carregado com sucesso ({len(faq_list)} respostas)")
        
        if faq_list:
            print(f"\n✅ Encontradas {len(faq_list)} respostas prontas:")
            for i, faq in enumerate(faq_list[:3], 1):
                print(f"\n   [{i}] {faq.get('id', 'N/A')}")
                print(f"       Pergunta: {faq.get('pergunta', 'N/A')}")
                print(f"       Resposta: {faq.get('resposta', 'N/A')[:60]}...")
            if len(faq_list) > 3:
                print(f"\n   ... e mais {len(faq_list) - 3} respostas")
    else:
        print("❌ Erro ao buscar FAQ")
        return
    
    # Teste 2: Catálogo
    print_subsection("[2] BUSCANDO CATALOGO (Tipos de Chamado)")
    logger.info("Buscando catálogo...")
    catalogo_data = make_request("GET", "/catalogo")
    
    if catalogo_data:
        catalogo_list = catalogo_data.get("catalogo", [])
        logger.info(f"OK - Catalogo carregado com sucesso ({len(catalogo_list)} tipos)")
        
        if catalogo_list:
            print(f"\nOK - Encontrados {len(catalogo_list)} tipos de chamado:")
            for i, item in enumerate(catalogo_list[:5], 1):
                print(f"\n   [{i}] {item.get('tipo', 'N/A')}")
                print(f"       Time: {item.get('time', 'N/A')}")
                print(f"       Campos obrigatorios: {', '.join(item.get('campos_obrigatorios', []))}")
                print(f"       Prazo: {item.get('prazo_horas', 'N/A')}h")
            if len(catalogo_list) > 5:
                print(f"\n   ... e mais {len(catalogo_list) - 5} tipos")
    else:
        print("ERRO ao buscar catalogo")
        return
    
    # Teste 3: Times
    print_subsection("[3] BUSCANDO TIMES (Equipes da Empresa)")
    logger.info("Buscando times...")
    times_data = make_request("GET", "/times")
    
    if times_data:
        times_list = times_data.get("times", [])
        logger.info(f"OK - Times carregados com sucesso ({len(times_list)} times)")
        
        if times_list:
            print(f"\nOK - Encontrados {len(times_list)} times:")
            for i, time in enumerate(times_list[:5], 1):
                print(f"\n   [{i}] {time.get('time', 'N/A')}")
                print(f"       Email: {time.get('email', 'N/A')}")
                print(f"       Atende: {', '.join(time.get('atende', []))}")
            if len(times_list) > 5:
                print(f"\n   ... e mais {len(times_list) - 5} times")
    else:
        print("ERRO ao buscar times")
        return
    
    # Teste 4: Eventos
    print_subsection("[4] BUSCANDO EVENTOS (E-mails/Pedidos)")
    logger.info("Buscando eventos...")
    eventos_data = make_request("GET", "/eventos")
    
    if eventos_data:
        eventos_list = eventos_data.get("eventos", [])
        logger.info(f"OK - Eventos carregados com sucesso ({len(eventos_list)} eventos)")
        
        if eventos_list:
            print(f"\nOK - Encontrados {len(eventos_list)} eventos:")
            for i, evento in enumerate(eventos_list[:5], 1):
                print(f"\n   [{i}] {evento.get('id', 'N/A')}")
                print(f"       De: {evento.get('de', 'N/A')}")
                print(f"       Para: {evento.get('para', 'N/A')}")
                print(f"       Assunto: {evento.get('assunto', 'N/A')}")
                print(f"       Status: {evento.get('status', 'N/A')}")
                print(f"       Corpo: {evento.get('corpo', 'N/A')[:60]}...")
            if len(eventos_list) > 5:
                print(f"\n   ... e mais {len(eventos_list) - 5} eventos")
        else:
            print("\nAVISO - Nenhum evento encontrado ainda")
    else:
        print("ERRO ao buscar eventos")
        return
    
    # Teste 5: Chamados
    print_subsection("[5] BUSCANDO CHAMADOS (Tickets Abertos)")
    logger.info("Buscando chamados...")
    chamados_data = make_request("GET", "/chamados")
    
    if chamados_data:
        chamados_list = chamados_data.get("chamados", [])
        logger.info(f"OK - Chamados carregados com sucesso ({len(chamados_list)} chamados)")
        
        if chamados_list:
            print(f"\nOK - Encontrados {len(chamados_list)} chamados:")
            for i, chamado in enumerate(chamados_list[:3], 1):
                print(f"\n   [{i}] {chamado.get('id', 'N/A')}")
                print(f"       Tipo: {chamado.get('tipo', 'N/A')}")
                print(f"       Status: {chamado.get('status', 'N/A')}")
            if len(chamados_list) > 3:
                print(f"\n   ... e mais {len(chamados_list) - 3} chamados")
        else:
            print("\nAVISO - Nenhum chamado aberto ainda")
    else:
        print("ERRO ao buscar chamados")
        return
    
    # Teste 6: Incidentes
    print_subsection("[6] BUSCANDO INCIDENTES (Criticos)")
    logger.info("Buscando incidentes...")
    incidentes_data = make_request("GET", "/incidentes")
    
    if incidentes_data:
        incidentes_list = incidentes_data.get("incidentes", [])
        logger.info(f"OK - Incidentes carregados com sucesso ({len(incidentes_list)} incidentes)")
        
        if incidentes_list:
            print(f"\nOK - Encontrados {len(incidentes_list)} incidentes:")
            for i, incidente in enumerate(incidentes_list[:3], 1):
                print(f"\n   [{i}] {incidente.get('id', 'N/A')}")
                print(f"       Criticidade: {incidente.get('criticidade', 'N/A')}")
                print(f"       Status: {incidente.get('status', 'N/A')}")
                print(f"       Resumo: {incidente.get('resumo', 'N/A')[:60]}...")
            if len(incidentes_list) > 3:
                print(f"\n   ... e mais {len(incidentes_list) - 3} incidentes")
        else:
            print("\nAVISO - Nenhum incidente aberto")
    else:
        print("ERRO ao buscar incidentes")
        return
    
    # Resumo
    print_section("OK - RESUMO DA CONEXAO")
    print(f"""
OK - Servidor MCP conectado com sucesso!
   URL: {MCP_SERVER_URL}

DADOS CARREGADOS:
   * FAQ: {len(faq_list)} respostas prontas
   * Catalogo: {len(catalogo_list)} tipos de chamado
   * Times: {len(times_list)} equipes
   * Eventos: {len(eventos_list)} pedidos/e-mails
   * Chamados: {len(chamados_list)} tickets abertos
   * Incidentes: {len(incidentes_list)} criticos

PROXIMOS PASSOS:
   1. Implementar agente de classificacao de eventos
   2. Implementar agente de revisao
   3. Implementar agente de acao (abrir chamados/incidentes)
   4. Criar dashboard web
""")
    
    logger.info("OK - Demo concluida com sucesso!")


if __name__ == "__main__":
    try:
        demo()
    except KeyboardInterrupt:
        print("\n\nERRO - Demo interrompida pelo usuario")
    except Exception as e:
        logger.error(f"ERRO na demo: {e}", exc_info=True)
