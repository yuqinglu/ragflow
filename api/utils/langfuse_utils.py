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
from typing import Optional, Dict, Any
from api.db.services.langfuse_service import TenantLangfuseService

logger = logging.getLogger(__name__)


class LangfuseUtils:
    """Langfuse 工具类，提供通用的 Langfuse 操作方法"""
    
    @staticmethod
    def get_client(tenant_id: str):
        """获取租户的 Langfuse 客户端
        
        Args:
            tenant_id: 租户ID
            
        Returns:
            Langfuse 客户端实例，如果配置不存在或连接失败则返回 None
        """
        try:
            from langfuse import Langfuse
            
            langfuse_keys = TenantLangfuseService.filter_by_tenant(tenant_id=tenant_id)
            if not langfuse_keys:
                return None
            
            langfuse = Langfuse(
                public_key=langfuse_keys.public_key,
                secret_key=langfuse_keys.secret_key,
                host=langfuse_keys.host
            )
            
            # 验证连接
            if langfuse.auth_check():
                return langfuse
            else:
                logger.warning(f"Langfuse认证失败，租户ID: {tenant_id}")
                return None
                
        except ImportError:
            logger.info("Langfuse包未安装，跳过追踪")
            return None
        except Exception as e:
            logger.warning(f"初始化Langfuse客户端失败: {str(e)}")
            return None
    
    @staticmethod
    def create_trace(langfuse_client, name: str, input_data: Dict[str, Any], 
                    metadata: Optional[Dict[str, Any]] = None):
        """创建 Langfuse trace
        
        Args:
            langfuse_client: Langfuse 客户端实例
            name: trace 名称
            input_data: 输入数据
            metadata: 元数据
            
        Returns:
            trace 实例，如果创建失败则返回 None
        """
        if not langfuse_client:
            return None
        
        try:
            trace = langfuse_client.trace(
                name=name,
                input=input_data,
                metadata=metadata or {}
            )
            return trace
        except Exception as e:
            logger.warning(f"创建trace失败: {str(e)}")
            return None
    
    @staticmethod
    def create_span(trace, name: str, input_data: Dict[str, Any], 
                   output_data: Optional[Dict[str, Any]] = None):
        """创建 Langfuse span
        
        Args:
            trace: 父 trace 实例
            name: span 名称
            input_data: 输入数据
            output_data: 输出数据（可选）
            
        Returns:
            span 实例，如果创建失败则返回 None
        """
        if not trace:
            return None
        
        try:
            span = trace.span(
                name=name,
                input=input_data
            )
            if output_data:
                span.update(output=output_data)
            return span
        except Exception as e:
            logger.warning(f"创建span失败: {str(e)}")
            return None
    
    @staticmethod
    def update_trace(trace, output_data: Dict[str, Any]):
        """更新 trace 的输出数据
        
        Args:
            trace: trace 实例
            output_data: 输出数据
        """
        if not trace:
            return
        
        try:
            trace.update(output=output_data)
        except Exception as e:
            logger.warning(f"更新trace失败: {str(e)}")
    
    @staticmethod
    def update_span(span, output_data: Dict[str, Any]):
        """更新 span 的输出数据
        
        Args:
            span: span 实例
            output_data: 输出数据
        """
        if not span:
            return
        
        try:
            span.update(output=output_data)
        except Exception as e:
            logger.warning(f"更新span失败: {str(e)}")
    
    @staticmethod
    def create_generation(trace, name: str, model: str, input_data: Dict[str, Any],
                         output_data: Optional[Dict[str, Any]] = None,
                         metadata: Optional[Dict[str, Any]] = None):
        """创建 Langfuse generation
        
        Args:
            trace: 父 trace 实例
            name: generation 名称
            model: 模型名称
            input_data: 输入数据
            output_data: 输出数据（可选）
            metadata: 元数据（可选）
            
        Returns:
            generation 实例，如果创建失败则返回 None
        """
        if not trace:
            return None
        
        try:
            generation = trace.generation(
                name=name,
                model=model,
                input=input_data,
                metadata=metadata or {}
            )
            if output_data:
                generation.end(output=output_data)
            return generation
        except Exception as e:
            logger.warning(f"创建generation失败: {str(e)}")
            return None
    
    @staticmethod
    def end_generation(generation, output_data: Dict[str, Any]):
        """结束 generation 并设置输出
        
        Args:
            generation: generation 实例
            output_data: 输出数据
        """
        if not generation:
            return
        
        try:
            generation.end(output=output_data)
        except Exception as e:
            logger.warning(f"结束generation失败: {str(e)}")


# 为了方便使用，提供简化的函数接口
def get_langfuse_client(tenant_id: str):
    """获取 Langfuse 客户端的简化接口"""
    return LangfuseUtils.get_client(tenant_id)


def create_trace_with_langfuse(langfuse_client, name: str, input_data: Dict[str, Any],
                              metadata: Optional[Dict[str, Any]] = None):
    """创建 trace 的简化接口"""
    return LangfuseUtils.create_trace(langfuse_client, name, input_data, metadata)


def create_span_with_langfuse(trace, name: str, input_data: Dict[str, Any],
                             output_data: Optional[Dict[str, Any]] = None):
    """创建 span 的简化接口"""
    return LangfuseUtils.create_span(trace, name, input_data, output_data) 