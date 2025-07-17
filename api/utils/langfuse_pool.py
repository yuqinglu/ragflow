#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
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
import threading
import time
import weakref
from typing import Optional, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class LangfuseConnection:
    """Langfuse连接包装器，提供引用计数和自动清理"""
    
    def __init__(self, langfuse_client, tenant_id: str):
        self.client = langfuse_client
        self.tenant_id = tenant_id
        self.ref_count = 0
        self.last_used = time.time()
        self.created_at = time.time()
        self._lock = threading.RLock()
    
    def acquire(self):
        """获取连接引用"""
        with self._lock:
            self.ref_count += 1
            self.last_used = time.time()
            logger.debug(f"Langfuse连接获取 - 租户: {self.tenant_id}, 引用计数: {self.ref_count}")
    
    def release(self):
        """释放连接引用"""
        with self._lock:
            self.ref_count = max(0, self.ref_count - 1)
            self.last_used = time.time()
            logger.debug(f"Langfuse连接释放 - 租户: {self.tenant_id}, 引用计数: {self.ref_count}")
    
    def is_idle(self, idle_timeout: float = 300.0) -> bool:
        """检查连接是否闲置（5分钟无使用且无引用）"""
        with self._lock:
            return (self.ref_count == 0 and 
                   (time.time() - self.last_used) > idle_timeout)
    
    def force_close(self):
        """强制关闭连接"""
        try:
            if hasattr(self.client, 'flush'):
                self.client.flush()
            if hasattr(self.client, 'close'):
                self.client.close()
            elif hasattr(self.client, '_client') and hasattr(self.client._client, 'close'):
                self.client._client.close()
            logger.debug(f"Langfuse连接已关闭 - 租户: {self.tenant_id}")
        except Exception as e:
            logger.warning(f"关闭Langfuse连接失败 - 租户: {self.tenant_id}, 错误: {e}")


class LangfuseConnectionPool:
    """Langfuse连接池管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._connections: Dict[str, LangfuseConnection] = {}
        self._pool_lock = threading.RLock()
        self._cleanup_interval = 300  # 5分钟清理一次
        self._max_idle_time = 600.0   # 10分钟无使用自动关闭，使用float类型
        self._last_cleanup = time.time()
        self._initialized = True
        
        logger.info("Langfuse连接池初始化完成")
    
    def get_connection(self, tenant_id: str) -> Optional['LangfuseConnection']:
        """获取或创建Langfuse连接"""
        if not tenant_id:
            return None
        
        with self._pool_lock:
            # 定期清理闲置连接
            self._cleanup_idle_connections()
            
            # 尝试复用现有连接
            if tenant_id in self._connections:
                conn = self._connections[tenant_id]
                conn.acquire()
                logger.debug(f"复用Langfuse连接 - 租户: {tenant_id}")
                return conn
            
            # 创建新连接
            conn = self._create_new_connection(tenant_id)
            if conn:
                self._connections[tenant_id] = conn
                conn.acquire()
                logger.info(f"创建新Langfuse连接 - 租户: {tenant_id}")
                return conn
            
            return None
    
    def _create_new_connection(self, tenant_id: str) -> Optional['LangfuseConnection']:
        """创建新的Langfuse连接"""
        try:
            from langfuse import Langfuse
            from api.db.services.langfuse_service import TenantLangfuseService
            
            langfuse_keys = TenantLangfuseService.filter_by_tenant(tenant_id=tenant_id)
            if not langfuse_keys:
                logger.debug(f"租户 {tenant_id} 未配置Langfuse")
                return None
            
            langfuse_client = Langfuse(
                public_key=langfuse_keys.public_key,
                secret_key=langfuse_keys.secret_key,
                host=langfuse_keys.host
            )
            
            # 验证连接
            if not langfuse_client.auth_check():
                logger.warning(f"Langfuse认证失败 - 租户: {tenant_id}")
                return None
            
            return LangfuseConnection(langfuse_client, tenant_id)
            
        except ImportError:
            logger.info("Langfuse包未安装，跳过连接创建")
            return None
        except Exception as e:
            logger.error(f"创建Langfuse连接失败 - 租户: {tenant_id}, 错误: {e}")
            return None
    
    def _cleanup_idle_connections(self):
        """清理闲置连接"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        self._last_cleanup = now
        idle_tenants = []
        
        for tenant_id, conn in self._connections.items():
            if conn.is_idle(self._max_idle_time):
                idle_tenants.append(tenant_id)
        
        for tenant_id in idle_tenants:
            conn = self._connections.pop(tenant_id, None)
            if conn:
                conn.force_close()
                logger.info(f"清理闲置Langfuse连接 - 租户: {tenant_id}")
    
    def release_connection(self, connection: 'LangfuseConnection'):
        """释放连接（减少引用计数）"""
        if connection:
            connection.release()
    
    def close_all_connections(self):
        """关闭所有连接（程序退出时调用）"""
        with self._pool_lock:
            for tenant_id, conn in self._connections.items():
                conn.force_close()
                logger.info(f"强制关闭Langfuse连接 - 租户: {tenant_id}")
            self._connections.clear()
            logger.info("所有Langfuse连接已关闭")
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        with self._pool_lock:
            stats = {
                "total_connections": len(self._connections),
                "active_connections": sum(1 for conn in self._connections.values() if conn.ref_count > 0),
                "idle_connections": sum(1 for conn in self._connections.values() if conn.ref_count == 0),
                "connections_by_tenant": {
                    tenant_id: {
                        "ref_count": conn.ref_count,
                        "last_used": conn.last_used,
                        "age_seconds": time.time() - conn.created_at
                    }
                    for tenant_id, conn in self._connections.items()
                }
            }
            return stats


@contextmanager
def get_langfuse_connection(tenant_id: str):
    """上下文管理器：自动获取和释放Langfuse连接"""
    pool = LangfuseConnectionPool()
    connection = pool.get_connection(tenant_id)
    
    try:
        yield connection.client if connection else None
    finally:
        if connection:
            pool.release_connection(connection)


# 全局连接池实例
_langfuse_pool = LangfuseConnectionPool()


def get_langfuse_client(tenant_id: str):
    """获取Langfuse客户端（兼容现有代码的简单接口）"""
    with get_langfuse_connection(tenant_id) as client:
        return client


def cleanup_langfuse_connections():
    """清理所有Langfuse连接（在程序退出时调用）"""
    _langfuse_pool.close_all_connections()


def get_langfuse_pool_stats():
    """获取连接池统计信息"""
    return _langfuse_pool.get_pool_stats() 