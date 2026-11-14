"""
Cliente para comunicação com o servidor MCP
Baseado na API do servidor de Triagem N1
"""

import requests
import logging
from typing import Optional, List, Dict, Any
from src.config import Settings
from src.models import Evento, FAQ, CatalogItem, Time

logger = logging.getLogger(__name__)


class MCPClient:
    """Cliente HTTP para comunicação com servidor MCP"""
    
    def __init__(self, settings: Settings):
        self.base_url = settings.mcp_server_url
        self.timeout = settings.mcp_server_timeout
        self.session = requests.Session()
        logger.info(f"MCPClient inicializado com URL: {self.base_url}")
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Faz uma requisição HTTP ao servidor MCP"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            logger.debug(f"Requisição {method} para {url}")
            
            if method.upper() == "GET":
                response = self.session.get(url, params=params, timeout=self.timeout)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data, timeout=self.timeout)
            elif method.upper() == "PUT":
                response = self.session.put(url, json=data, timeout=self.timeout)
            elif method.upper() == "DELETE":
                response = self.session.delete(url, timeout=self.timeout)
            else:
                raise ValueError(f"Método HTTP não suportado: {method}")
            
            response.raise_for_status()
            result = response.json()
            logger.debug(f"Resposta recebida: {result}")
            return result
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Erro de conexão com MCP Server em {url}: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao comunicar com MCP Server: {e}")
            raise
    
    # ==================== Eventos ====================
    
    def fetch_eventos(self, limit: int = 10, offset: int = 0) -> List[Evento]:
        """Busca eventos (e-mails) do servidor MCP"""
        try:
            response = self._make_request(
                "GET",
                "/eventos",
                params={"limit": limit, "offset": offset}
            )
            
            eventos = []
            for evento_data in response.get("eventos", []):
                evento = Evento(**evento_data)
                eventos.append(evento)
            
            logger.info(f"Buscados {len(eventos)} eventos")
            return eventos
        except Exception as e:
            logger.error(f"Erro ao buscar eventos: {e}")
            return []
    
    def get_evento(self, evento_id: str) -> Optional[Evento]:
        """Busca um evento específico"""
        try:
            response = self._make_request("GET", f"/eventos/{evento_id}")
            return Evento(**response)
        except Exception as e:
            logger.error(f"Erro ao buscar evento {evento_id}: {e}")
            return None
    
    def update_evento(self, evento_id: str, status: str = None, observacao: str = None) -> bool:
        """Atualiza o status ou observação de um evento"""
        try:
            data = {}
            if status:
                data["status"] = status
            if observacao:
                data["observacao"] = observacao
            
            self._make_request(
                "PUT",
                f"/eventos/{evento_id}",
                data=data
            )
            logger.info(f"Evento {evento_id} atualizado")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar evento {evento_id}: {e}")
            return False
    
    # ==================== Chamados ====================
    
    def registrar_chamado(self, tipo: str, campos: Dict[str, Any], 
                         status: str = "aberto", observacao: str = None) -> Optional[str]:
        """Registra um novo chamado no servidor MCP"""
        try:
            data = {
                "tipo": tipo,
                "campos": campos,
                "status": status
            }
            if observacao:
                data["observacao"] = observacao
            
            response = self._make_request(
                "POST",
                "/chamados",
                data=data
            )
            chamado_id = response.get("id")
            logger.info(f"Chamado criado: {chamado_id}")
            return chamado_id
        except Exception as e:
            logger.error(f"Erro ao registrar chamado: {e}")
            return None
    
    def get_chamado(self, chamado_id: str) -> Optional[Dict[str, Any]]:
        """Busca um chamado específico"""
        try:
            response = self._make_request("GET", f"/chamados/{chamado_id}")
            return response
        except Exception as e:
            logger.error(f"Erro ao buscar chamado {chamado_id}: {e}")
            return None
    
    def list_chamados(self) -> List[Dict[str, Any]]:
        """Lista todos os chamados"""
        try:
            response = self._make_request("GET", "/chamados")
            chamados = response.get("chamados", [])
            logger.info(f"Listados {len(chamados)} chamados")
            return chamados
        except Exception as e:
            logger.error(f"Erro ao listar chamados: {e}")
            return []
    
    def atualizar_chamado(self, chamado_id: str, status: str = None, 
                         observacao: str = None, pedidos: List[str] = None) -> bool:
        """Atualiza um chamado"""
        try:
            data = {}
            if status:
                data["status"] = status
            if observacao:
                data["observacao"] = observacao
            if pedidos:
                data["pedidos"] = pedidos
            
            self._make_request(
                "PUT",
                f"/chamados/{chamado_id}",
                data=data
            )
            logger.info(f"Chamado {chamado_id} atualizado")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar chamado {chamado_id}: {e}")
            return False
    
    # ==================== Incidentes ====================
    
    def registrar_incidente(self, criticidade: str, resumo: str, 
                           observacao: str = None) -> Optional[str]:
        """Registra um novo incidente no servidor MCP"""
        try:
            data = {
                "criticidade": criticidade,
                "resumo": resumo
            }
            if observacao:
                data["observacao"] = observacao
            
            response = self._make_request(
                "POST",
                "/incidentes",
                data=data
            )
            incidente_id = response.get("id")
            logger.info(f"Incidente criado: {incidente_id}")
            return incidente_id
        except Exception as e:
            logger.error(f"Erro ao registrar incidente: {e}")
            return None
    
    def get_incidente(self, incidente_id: str) -> Optional[Dict[str, Any]]:
        """Busca um incidente específico"""
        try:
            response = self._make_request("GET", f"/incidentes/{incidente_id}")
            return response
        except Exception as e:
            logger.error(f"Erro ao buscar incidente {incidente_id}: {e}")
            return None
    
    def list_incidentes(self) -> List[Dict[str, Any]]:
        """Lista todos os incidentes"""
        try:
            response = self._make_request("GET", "/incidentes")
            incidentes = response.get("incidentes", [])
            logger.info(f"Listados {len(incidentes)} incidentes")
            return incidentes
        except Exception as e:
            logger.error(f"Erro ao listar incidentes: {e}")
            return []
    
    def atualizar_incidente(self, incidente_id: str, status: str = None,
                           criticidade: str = None, observacao: str = None) -> bool:
        """Atualiza um incidente"""
        try:
            data = {}
            if status:
                data["status"] = status
            if criticidade:
                data["criticidade"] = criticidade
            if observacao:
                data["observacao"] = observacao
            
            self._make_request(
                "PUT",
                f"/incidentes/{incidente_id}",
                data=data
            )
            logger.info(f"Incidente {incidente_id} atualizado")
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar incidente {incidente_id}: {e}")
            return False
    
    # ==================== FAQ ====================
    
    def get_faq(self) -> List[FAQ]:
        """Busca todas as respostas do FAQ"""
        try:
            response = self._make_request("GET", "/faq")
            faqs = []
            for faq_data in response.get("faq", []):
                faq = FAQ(**faq_data)
                faqs.append(faq)
            logger.info(f"Carregadas {len(faqs)} respostas do FAQ")
            return faqs
        except Exception as e:
            logger.error(f"Erro ao buscar FAQ: {e}")
            return []
    
    # ==================== Catálogo ====================
    
    def get_catalogo(self) -> List[CatalogItem]:
        """Busca o catálogo de tipos de chamado"""
        try:
            response = self._make_request("GET", "/catalogo")
            items = []
            for item_data in response.get("catalogo", []):
                item = CatalogItem(**item_data)
                items.append(item)
            logger.info(f"Carregados {len(items)} tipos de chamado")
            return items
        except Exception as e:
            logger.error(f"Erro ao buscar catálogo: {e}")
            return []
    
    # ==================== Times ====================
    
    def get_times(self) -> List[Time]:
        """Busca informações sobre os times"""
        try:
            response = self._make_request("GET", "/times")
            times = []
            for time_data in response.get("times", []):
                time = Time(**time_data)
                times.append(time)
            logger.info(f"Carregados {len(times)} times")
            return times
        except Exception as e:
            logger.error(f"Erro ao buscar times: {e}")
            return []
    
    # ==================== Responder Evento ====================
    
    def responder_evento(self, evento_id: str, resposta: str, 
                        aguardar_resposta: bool = False) -> bool:
        """Responde a um evento"""
        try:
            data = {
                "resposta": resposta,
                "aguardar_resposta": aguardar_resposta
            }
            
            self._make_request(
                "POST",
                f"/eventos/{evento_id}/responder",
                data=data
            )
            logger.info(f"Resposta enviada para evento {evento_id}")
            return True
        except Exception as e:
            logger.error(f"Erro ao responder evento {evento_id}: {e}")
            return False
