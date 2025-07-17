#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import logging
import os
import socket
import threading
import time
from typing import Dict, Optional

try:
    from nacos import NacosClient
except ImportError:
    NacosClient = None

logger = logging.getLogger(__name__)


class NacosServiceRegistry:
    """Nacos服务注册客户端"""
    
    def __init__(self, 
                 server_addresses: str = None,
                 namespace: str = None,
                 username: str = None,
                 password: str = None):
        """
        初始化Nacos客户端
        
        Args:
            server_addresses: Nacos服务器地址，格式：ip:port,ip:port
            namespace: 命名空间，默认为空（使用默认命名空间）
            username: 用户名，默认为空（无认证）
            password: 密码，默认为空（无认证）
        """
        if NacosClient is None:
            raise ImportError("nacos-sdk-python is not installed")
            
        self.server_addresses = server_addresses or os.getenv('NACOS_SERVER_ADDRESSES', 'localhost:8848')
        self.namespace = namespace or os.getenv('NACOS_NAMESPACE', '')
        self.username = username or os.getenv('NACOS_USERNAME', '')
        self.password = password or os.getenv('NACOS_PASSWORD', '')
        
        # 构建NacosClient参数
        client_kwargs = {
            'server_addresses': self.server_addresses
        }
        
        # 只有当命名空间不为空时才添加
        if self.namespace:
            client_kwargs['namespace'] = self.namespace
            
        # 只有当用户名不为空时才添加认证信息
        if self.username:
            client_kwargs['username'] = self.username
            client_kwargs['password'] = self.password
        
        self.client = NacosClient(**client_kwargs)
        
        self._registered_service = None
        self._lock = threading.Lock()
        
    def get_local_ip(self) -> str:
        """获取本机IP地址"""
        try:
            # 创建一个UDP socket连接到外部地址来获取本机IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def get_registration_ip(self) -> str:
        """获取用于Nacos注册的IP地址"""
        # 优先使用环境变量配置的注册IP
        registration_ip = os.getenv('NACOS_REGISTRATION_IP')
        if registration_ip:
            logger.info(f"Using configured registration IP: {registration_ip}")
            return registration_ip
        
        # 如果没有配置，则自动获取本机IP
        local_ip = self.get_local_ip()
        logger.info(f"Using auto-detected local IP: {local_ip}")
        return local_ip
    
    def register_ragflow_service(self, 
                                service_name: str = "ragflow",
                                ip: str = None, 
                                port: int = None,
                                metadata: Dict = None,
                                weight: float = 1.0,
                                ephemeral: bool = True) -> bool:
        """
        注册RAGFlow服务到Nacos
        
        Args:
            service_name: 服务名称，默认为ragflow
            ip: 服务IP地址，默认自动获取
            port: 服务端口
            metadata: 服务元数据
            weight: 权重
            ephemeral: 是否为临时实例
            
        Returns:
            bool: 注册是否成功
        """
        if not ip:
            ip = self.get_registration_ip()
            
        if not port:
            logger.error(f"Service port is required for {service_name}")
            return False
            
        try:
            # 注册服务 - 尝试不同的API调用方式
            try:
                # 方式1：使用add_naming_instance
                success = self.client.add_naming_instance(
                    service_name=service_name,
                    ip=ip,
                    port=port,
                    weight=weight,
                    ephemeral=ephemeral,
                    metadata=metadata or {}
                )
            except TypeError as e:
                # 方式2：如果参数不匹配，尝试简化参数
                logger.warning(f"add_naming_instance with full params failed: {e}, trying simplified params")
                success = self.client.add_naming_instance(
                    service_name=service_name,
                    ip=ip,
                    port=port
                )
            
            if success:
                with self._lock:
                    self._registered_service = {
                        'service_name': service_name,
                        'ip': ip,
                        'port': port,
                        'metadata': metadata or {}
                    }
                logger.info(f"Successfully registered RAGFlow service {service_name} at {ip}:{port}")
                return True
            else:
                logger.error(f"Failed to register RAGFlow service {service_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error registering RAGFlow service {service_name}: {e}")
            return False
    
    def deregister_ragflow_service(self, service_name: str = "ragflow", ip: str = None, port: int = None) -> bool:
        """
        注销RAGFlow服务
        
        Args:
            service_name: 服务名称
            ip: 服务IP地址
            port: 服务端口
            
        Returns:
            bool: 注销是否成功
        """
        if not ip:
            ip = self.get_registration_ip()
            
        try:
            success = self.client.remove_naming_instance(
                service_name=service_name,
                ip=ip,
                port=port
            )
            
            if success:
                with self._lock:
                    self._registered_service = None
                logger.info(f"Successfully deregistered RAGFlow service {service_name}")
                return True
            else:
                logger.error(f"Failed to deregister RAGFlow service {service_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error deregistering RAGFlow service {service_name}: {e}")
            return False
    
    def heartbeat(self, service_name: str = "ragflow", ip: str = None, port: int = None) -> bool:
        """
        发送心跳
        
        Args:
            service_name: 服务名称
            ip: 服务IP地址
            port: 服务端口
            
        Returns:
            bool: 心跳是否成功
        """
        if not ip:
            ip = self.get_registration_ip()
            
        try:
            response = self.client.send_heartbeat(
                service_name=service_name,
                ip=ip,
                port=port
            )
            
            # 处理响应：如果是字典，检查code字段；如果是布尔值，直接返回
            if isinstance(response, dict):
                # Nacos API返回字典格式，检查code字段
                code = response.get('code', 0)
                success = code == 10200  # 10200表示成功
                if success:
                    logger.debug(f"Heartbeat successful for {service_name}: {response}")
                else:
                    logger.warning(f"Heartbeat failed for {service_name}, code: {code}, response: {response}")
                return success
            elif isinstance(response, bool):
                # 直接返回布尔值
                return response
            else:
                # 其他类型，尝试转换为布尔值
                logger.warning(f"Unexpected heartbeat response type for {service_name}: {type(response)}, value: {response}")
                return bool(response)
                
        except Exception as e:
            logger.error(f"Error sending heartbeat for {service_name}: {e}")
            return False
    
    def start_heartbeat_thread(self, service_name: str = "ragflow", ip: str = None, port: int = None, interval: int = 30):
        """
        启动心跳线程
        
        Args:
            service_name: 服务名称
            ip: 服务IP地址
            port: 服务端口
            interval: 心跳间隔（秒）
        """
        def heartbeat_worker():
            while True:
                try:
                    self.heartbeat(service_name, ip, port)
                    time.sleep(interval)
                except Exception as e:
                    logger.error(f"Heartbeat error for {service_name}: {e}")
                    time.sleep(interval)
        
        thread = threading.Thread(target=heartbeat_worker, daemon=True)
        thread.start()
        logger.info(f"Started heartbeat thread for RAGFlow service {service_name}")
    
    def get_registered_service(self) -> Optional[Dict]:
        """获取已注册的服务信息"""
        with self._lock:
            return self._registered_service.copy() if self._registered_service else None


# 全局Nacos客户端实例
_nacos_client = None


def get_nacos_client() -> Optional[NacosServiceRegistry]:
    """获取全局Nacos客户端实例"""
    global _nacos_client
    if _nacos_client is None:
        try:
            _nacos_client = NacosServiceRegistry()
        except Exception as e:
            logger.error(f"Failed to initialize Nacos client: {e}")
            return None
    return _nacos_client


def register_ragflow_service(host: str = None, port: int = None, metadata: Dict = None) -> bool:
    """
    注册RAGFlow服务到Nacos
    
    Args:
        host: 服务主机地址
        port: 服务端口
        metadata: 服务元数据
        
    Returns:
        bool: 注册是否成功
    """
    client = get_nacos_client()
    if not client:
        return False
        
    service_name = "ragflow"
    if not port:
        port = int(os.getenv('SVR_HTTP_PORT', 9380))
        
    if not metadata:
        metadata = {
            'version': os.getenv('RAGFLOW_VERSION', '0.19.1'),
            'environment': os.getenv('ENVIRONMENT', 'production'),
            'service_type': 'ragflow',
            'description': 'RAGFlow RAG Engine Service'
        }
    
    return client.register_ragflow_service(
        service_name=service_name,
        ip=host,
        port=port,
        metadata=metadata
    )


def deregister_ragflow_service(host: str = None, port: int = None) -> bool:
    """
    注销RAGFlow服务
    
    Args:
        host: 服务主机地址
        port: 服务端口
        
    Returns:
        bool: 注销是否成功
    """
    client = get_nacos_client()
    if not client:
        return False
        
    service_name = "ragflow"
    if not port:
        port = int(os.getenv('SVR_HTTP_PORT', 9380))
    
    return client.deregister_ragflow_service(
        service_name=service_name,
        ip=host,
        port=port
    ) 