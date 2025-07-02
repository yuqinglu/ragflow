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

from datetime import datetime

import peewee

from api.db.db_models import DB, TenantLangfuse
from api.db.services.common_service import CommonService
from api.utils import current_timestamp, datetime_format


class TenantLangfuseService(CommonService):
    """
    All methods that modify the status should be enclosed within a DB.atomic() context to ensure atomicity
    and maintain data integrity in case of errors during execution.
    """

    model = TenantLangfuse

    @classmethod
    @DB.connection_context()
    def filter_by_tenant(cls, tenant_id):
        fields = [cls.model.tenant_id, cls.model.host, cls.model.secret_key, cls.model.public_key]
        try:
            keys = cls.model.select(*fields).where(cls.model.tenant_id == tenant_id).first()
            return keys
        except peewee.DoesNotExist:
            return None

    @classmethod
    @DB.connection_context()
    def filter_by_tenant_with_info(cls, tenant_id):
        fields = [cls.model.tenant_id, cls.model.host, cls.model.secret_key, cls.model.public_key]
        try:
            keys = cls.model.select(*fields).where(cls.model.tenant_id == tenant_id).dicts().first()
            return keys
        except peewee.DoesNotExist:
            return None

    @classmethod
    def update_by_tenant(cls, tenant_id, langfuse_keys):
        langfuse_keys["update_time"] = current_timestamp()
        langfuse_keys["update_date"] = datetime_format(datetime.now())
        return cls.model.update(**langfuse_keys).where(cls.model.tenant_id == tenant_id).execute()

    @classmethod
    def save(cls, **kwargs):
        kwargs["create_time"] = current_timestamp()
        kwargs["create_date"] = datetime_format(datetime.now())
        kwargs["update_time"] = current_timestamp()
        kwargs["update_date"] = datetime_format(datetime.now())
        obj = cls.model.create(**kwargs)
        return obj

    @classmethod
    def delete_model(cls, langfuse_model):
        langfuse_model.delete_instance()

    @classmethod
    def test_connection(cls, tenant_id):
        """
        测试langfuse连接和配置
        返回测试结果和详细信息
        """
        try:
            from langfuse import Langfuse
            
            langfuse_keys = cls.filter_by_tenant(tenant_id=tenant_id)
            if not langfuse_keys:
                return {
                    "success": False,
                    "error": "No Langfuse configuration found for this tenant",
                    "details": "Please configure Langfuse keys first"
                }
            
            # 使用连接池测试连接
            try:
                from api.utils.langfuse_pool import get_langfuse_connection
                
                with get_langfuse_connection(tenant_id) as langfuse:
                    if not langfuse:
                        return {
                            "success": False,
                            "error": "Failed to get Langfuse connection from pool",
                            "details": "Connection pool may not be properly initialized"
                        }
                    
                    # 测试认证
                    auth_result = langfuse.auth_check()
                    if not auth_result:
                        return {
                            "success": False,
                            "error": "Authentication failed",
                            "details": "Please check your public key, secret key, and host configuration"
                        }
                    
                    # 测试创建trace
                    test_trace = langfuse.trace(name="test-connection")
                    test_generation = test_trace.generation(
                        name="test-generation",
                        model="test-model",
                        input={"test": "connection"}
                    )
                    test_generation.end(output={"result": "success"})
                    
                    return {
                        "success": True,
                        "message": "Langfuse connection test successful",
                        "details": f"Connected to {langfuse_keys.host}"
                    }
                
            except Exception as conn_error:
                return {
                    "success": False,
                    "error": f"Connection error: {str(conn_error)}",
                    "details": "Please check your host URL and network connectivity"
                }
                
        except ImportError:
            return {
                "success": False,
                "error": "Langfuse library not installed",
                "details": "Please install langfuse: pip install langfuse"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "details": "Please check the system logs for more information"
            }
