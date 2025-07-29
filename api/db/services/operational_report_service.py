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
import json
import logging
import xxhash
from datetime import datetime
from functools import lru_cache
from peewee import fn

from api import settings
from api.db import StatusEnum, LLMType
from api.db.db_models import OperationalReport
from api.db.services.common_service import CommonService
from api.db.services.user_service import UserTenantService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.llm_service import LLMBundle, TenantLLMService
from api.db.db_models import UserTenant, Knowledgebase
from rag.nlp import rag_tokenizer, search


class OperationalReportService(CommonService):
    """Service class for managing operational reports with vector search capabilities.
    
    This class provides functionality for managing operational failure analysis reports,
    including create, read, update, delete operations, access control based on user
    and group permissions, and vector-based search capabilities.
    """
    model = OperationalReport
    
    # 缓存知识库信息，避免重复查询
    _kb_cache = {}
    
    @classmethod
    @lru_cache(maxsize=128)
    def _get_kb_info(cls, kb_id):
        """获取知识库信息，使用缓存优化性能"""
        if kb_id not in cls._kb_cache:
            exists, kb_info = KnowledgebaseService.get_by_id(kb_id)
            if exists:
                cls._kb_cache[kb_id] = kb_info
            else:
                cls._kb_cache[kb_id] = None
        return cls._kb_cache[kb_id]
    
    @classmethod
    def _clear_kb_cache(cls):
        """清除知识库缓存"""
        cls._kb_cache.clear()
        cls._get_kb_info.cache_clear()
    
    @classmethod
    def _create_vector_chunk(cls, report, kb_info):
        """Create a vector chunk for the report.
        
        Args:
            report: Report object
            kb_info: Knowledge base information
            
        Returns:
            Dictionary representing the vector chunk
        """
        # 将完整的报告数据转换为JSON字符串，保持原始格式
        complete_report_json = {
            "report_data": report.report_data
        }
        
        # 将完整报告转换为JSON字符串，直接存储在content_with_weight中
        report_json_text = json.dumps(complete_report_json, ensure_ascii=False, indent=2)
        
        chunk = {
            "id": xxhash.xxh64((report_json_text + str(report.id)).encode("utf-8")).hexdigest(),
            "doc_id": str(report.id),  # 将整数转换为字符串存储
            "kb_id": [kb_info.id],
            "content_with_weight": report_json_text,  # 直接存储完整的JSON
            "content_ltks": rag_tokenizer.tokenize(report_json_text),
            "content_sm_ltks": rag_tokenizer.fine_grained_tokenize(report_json_text),
            "create_time": str(datetime.now()).replace("T", " ")[:19],
            "create_timestamp_flt": datetime.now().timestamp(),
            "doc_type_kwd": "operational_report",
            "created_by": report.created_by or "",
            # "important_kwd": [],
            # "question_kwd": [],
            # "page_num_int": [1],  
            # "position_int": [],  
            "available_int": 1
        }
        
        return chunk
    
    @classmethod
    def _vectorize_and_store(cls, report, kb_info):
        """Vectorize report content and store in vector database.
        
        Args:
            report: Report object
            kb_info: Knowledge base information
            
        Returns:
            Boolean indicating success
        """
        try:
            # Create chunk data
            chunk = cls._create_vector_chunk(report, kb_info)
            content = chunk["content_with_weight"]
            
            # Validate content
            if not content or len(content.strip()) == 0:
                logging.error(f"Failed to vectorize report {report.id}: Empty content")
                return False
            
            logging.info(f"Starting vectorization for report {report.id}, content length: {len(content)}")
            
            # Get embedding model
            try:
                with LLMBundle(kb_info.tenant_id, LLMType.EMBEDDING, kb_info.embd_id) as embd_mdl:
                    # Generate embeddings
                    vectors, token_count = embd_mdl.encode([content])
                    vector = vectors[0]
                    
                    logging.info(f"Successfully Generated embedding for report {report.id}, vector length: {len(vector)}")
                    
                    # Add vector to chunk
                    chunk[f"q_{len(vector)}_vec"] = vector.tolist()
                    
                    # Create index if not exists
                    logging.info("check index exist")
                    index_name = search.index_name(kb_info.tenant_id)
                    if not settings.docStoreConn.indexExist(index_name, kb_info.id):
                        logging.info(f"Creating index {index_name} for kb {kb_info.id}")
                        settings.docStoreConn.createIdx(index_name, kb_info.id, len(vector))
                    # Insert into vector store
                    settings.docStoreConn.insert([chunk], index_name, kb_info.id)
                    
                    logging.info(f"Successfully vectorized report {report.id}")
                    return True
                    
            except Exception as embd_error:
                import traceback
                logging.error(f"Embedding model error for report {report.id}: {embd_error}")
                logging.error(f"Tenant ID: {kb_info.tenant_id}, Embedding ID: {kb_info.embd_id}")
                logging.error(f"Exception type: {type(embd_error).__name__}")
                logging.error(f"Exception message: {str(embd_error)}")
                logging.error(f"Traceback: {traceback.format_exc()}")
                return False
                
        except Exception as e:
            import traceback
            logging.error(f"Failed to vectorize report {report.id}: {e}")
            logging.error(f"Report data type: {type(report.report_data)}")
            if isinstance(report.report_data, dict):
                logging.error(f"Report data keys: {list(report.report_data.keys())}")
            logging.error(f"Exception type: {type(e).__name__}")
            logging.error(f"Exception message: {str(e)}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    @classmethod
    def _remove_from_vector_store(cls, report_id, kb_info):
        """Remove report from vector store.
        
        Args:
            report_id: Report ID
            kb_info: Knowledge base information
            
        Returns:
            Boolean indicating success
        """
        try:
            index_name = search.index_name(kb_info.tenant_id)
            settings.docStoreConn.delete(
                {"doc_id": str(report_id)},  # 将整数转换为字符串
                index_name, 
                kb_info.id
            )
            logging.info(f"Successfully removed report {report_id} from vector store")
            return True
        except Exception as e:
            logging.error(f"Failed to remove report {report_id} from vector store: {e}")
            return False
    
    @classmethod
    def get_by_kb_id(cls, kb_id, user_id, page_number=1, 
                     items_per_page=20, orderby="create_time", desc=True, keywords=""):
        """Get reports by knowledge base ID with pagination and user filtering.
        
        Args:
            kb_id: Knowledge base ID
            user_id: User ID for data filtering
            page_number: Page number (1-based)
            items_per_page: Number of items per page
            orderby: Field to order by
            desc: Boolean indicating descending order
            
        Returns:
            Tuple of (reports list, total count)
        """
        reports = cls.model.select().where(
            (cls.model.kb_id == kb_id) &
            (cls.model.status == StatusEnum.VALID.value) &
            (cls.model.report_status != "已删除")
        )
        
        # 应用用户数据过滤 - 用户可以看到自己的报告和其他人的已生效报告
        if user_id:
            reports = reports.where(
                (cls.model.created_by == user_id) | 
                (cls.model.report_status == "已生效")
            )
        
        # 应用排序
        if hasattr(cls.model, orderby):
            order_field = getattr(cls.model, orderby)
            if desc:
                reports = reports.order_by(order_field.desc())
            else:
                reports = reports.order_by(order_field)
        else:
            # 默认按创建时间排序
            reports = reports.order_by(cls.model.create_time.desc())
        
        # 获取总数
        count = reports.count()
        
        # 应用分页
        offset = (page_number - 1) * items_per_page
        reports = reports.offset(offset).limit(items_per_page)
        
        # 转换为字典列表
        report_list = []
        for report in reports:
            report_dict = report.to_dict()
            report_list.append(report_dict)
        
        return report_list, count
    
    @classmethod
    def vector_search(cls, query, kb_id, user_id, 
                     page_number=1, items_per_page=20, similarity_threshold=0.4,
                     vector_similarity_weight=0.7):
        """Perform vector search on operational reports with custom sorting.
        
        Args:
            query: Search query string
            kb_id: Knowledge base ID
            user_id: User ID for data filtering
            page_number: Page number (1-based)
            items_per_page: Number of items per page
            similarity_threshold: Minimum similarity threshold
            vector_similarity_weight: Weight for vector similarity
            
        Returns:
            Dictionary with search results
        """
        # 使用缓存获取知识库信息
        kb_info = cls._get_kb_info(kb_id)
        if not kb_info:
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        try:
            # 执行向量搜索 - 获取更多结果用于后续排序
            search_results = search(
                query=query,
                kb_id=kb_info.id,
                page_number=1,  # 获取第一页的所有结果
                items_per_page=1000,  # 获取更多结果用于排序
                similarity_threshold=similarity_threshold,
                vector_similarity_weight=vector_similarity_weight
            )
            
            if not search_results:
                return {"reports": [], "total": 0}
            
            # 处理搜索结果并应用用户数据过滤
            all_reports = []
            for result in search_results.get("results", []):
                try:
                    # 获取报告详情
                    report_id_str = result.get("doc_id")
                    if report_id_str:
                        # 将字符串doc_id转换为整数
                        try:
                            report_id = int(report_id_str)
                        except (ValueError, TypeError):
                            logging.warning(f"Invalid doc_id format: {report_id_str}")
                            continue
                        
                        report = cls.model.get_by_id(report_id)
                        if report and report.status == StatusEnum.VALID.value:
                            # 应用用户数据过滤
                            if user_id:
                                if report.created_by != user_id and report.report_status != "已生效":
                                    continue
                            
                            report_dict = report.to_dict()
                            report_dict["similarity"] = result.get("similarity", 0)
                            all_reports.append({
                                "report": report_dict,
                                "similarity": result.get("similarity", 0),
                                "is_own_report": report.created_by == user_id,
                                "create_time": report.create_time
                            })
                except Exception as e:
                    logging.warning(f"Error processing search result: {e}")
                    continue
            
            # 自定义排序逻辑
            def custom_sort_key(item):
                report = item["report"]
                is_own = item["is_own_report"]
                create_time = item["create_time"]
                
                # 排序优先级：
                # 1. 是否为自己的报告 (True > False)
                # 2. 创建时间 (降序)
                return (not is_own, -create_time.timestamp())
            
            # 应用排序
            all_reports.sort(key=custom_sort_key)
            
            # 应用分页
            total = len(all_reports)
            start_index = (page_number - 1) * items_per_page
            end_index = start_index + items_per_page
            paginated_reports = all_reports[start_index:end_index]
            
            # 移除排序用的临时字段
            for item in paginated_reports:
                item.pop("is_own_report", None)
                item.pop("create_time", None)
            
            return {
                "reports": paginated_reports,
                "total": total
            }
            
        except Exception as e:
            logging.error(f"Vector search failed: {e}")
            return {"reports": [], "total": 0}
    
    @classmethod
    def create_report(cls, kb_id, report_data, created_by, report_id, report_status=None):
        """Create a new operational report.
        
        Args:
            kb_id: Knowledge base ID
            report_data: Report data in JSON format
            created_by: User ID who created the report
            report_id: Report ID (required)
            report_status: Report status (optional, defaults to "未提交")
            
        Returns:
            Created report object
        """
        # 使用缓存获取知识库信息
        kb_info = cls._get_kb_info(kb_id)
        if not kb_info:
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        # Use provided report_status or default
        if not report_status:
            report_status = "未提交"
        
        logging.info(f"Creating report {report_id} in knowledge base {kb_id}, tenant {kb_info.tenant_id}")
        
        report = cls.model.create(
            id=report_id,
            kb_id=kb_id,
            report_data=report_data,
            created_by=created_by,
            report_status=report_status,
            status=StatusEnum.VALID.value
        )
        # 重新获取完整的报告对象
        report = cls.model.get_by_id(report_id)
        # Vectorize and store in vector database
        try:
            vectorization_success = cls._vectorize_and_store(report, kb_info)
            if not vectorization_success:
                logging.warning(f"Report {report.id} created but vectorization failed")
        except Exception as e:
            logging.error(f"Vectorization failed for report {report.id}: {e}")
            # Continue without vectorization - report is still created
        
        return report
    
    @classmethod
    def upsert_report(cls, report_id, kb_id, report_data, created_by, report_status=None):
        """Create or update an operational report based on whether it exists.
        
        Args:
            report_id: Report ID (required)
            kb_id: Knowledge base ID
            report_data: Report data in JSON format
            created_by: User ID who created the report
            report_status: Report status (optional, defaults to "未提交")
            
        Returns:
            Tuple of (report_object, operation_type) where operation_type is "created" or "updated"
        """
        # 使用缓存获取知识库信息
        kb_info = cls._get_kb_info(kb_id)
        if not kb_info:
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        # Check if report exists
        try:
            existing_report = cls.model.get_by_id(report_id)
            if existing_report:
                # Update existing report
                # Check if user has permission to update
                if created_by and existing_report.created_by != created_by:
                    raise ValueError("User does not have permission to update this report")
                
                update_data = {}
                need_re_vectorize = False
                
                if report_data is not None:
                    update_data['report_data'] = report_data
                    need_re_vectorize = True
                if report_status is not None:
                    update_data['report_status'] = report_status
                
                if update_data:
                    query = cls.model.update(**update_data).where(cls.model.id == report_id)
                    success = query.execute() > 0
                    
                    if success:
                        # Re-vectorize if content changed
                        if need_re_vectorize:
                            # Remove old vector and add new one
                            cls._remove_from_vector_store(report_id, kb_info)
                            # Get updated report
                            updated_report = cls.model.get_by_id(report_id)
                            cls._vectorize_and_store(updated_report, kb_info)
                        
                        return updated_report, "updated"
                    else:
                        raise ValueError("Failed to update report")
                else:
                    return existing_report, "updated"
        except cls.model.DoesNotExist:
            pass
        
        # Use provided report_status or default
        if not report_status:
            report_status = "未提交"
        
        logging.info(f"Creating report {report_id} in knowledge base {kb_id}, tenant {kb_info.tenant_id}")
        
        report = cls.model.create(
            id=report_id,
            kb_id=kb_id,
            report_data=report_data,
            created_by=created_by,
            report_status=report_status,
            status=StatusEnum.VALID.value
        )
        
        # 重新获取完整的报告对象
        report = cls.model.get_by_id(report_id)
        
        # Vectorize and store in vector database
        try:
            vectorization_success = cls._vectorize_and_store(report, kb_info)
            if not vectorization_success:
                logging.warning(f"Report {report.id} created but vectorization failed")
        except Exception as e:
            logging.error(f"Vectorization failed for report {report.id}: {e}")
            # Continue without vectorization - report is still created
        
        return report, "created"
    
    @classmethod
    def batch_update_status(cls, status_updates):
        """Batch update report statuses.
        
        Args:
            status_updates: List of dictionaries with 'id' and 'report_status' keys
            
        Returns:
            Dictionary with success and failed updates
        """
        success_updates = []
        failed_updates = []
        
        for update in status_updates:
            try:
                report_id = update.get("id")
                new_status = update.get("report_status")
                
                if not report_id or not new_status:
                    failed_updates.append({"id": report_id, "error": "Missing id or report_status"})
                    continue
                
                # Update report status
                query = cls.model.update(report_status=new_status).where(cls.model.id == report_id)
                affected_rows = query.execute()
                
                if affected_rows > 0:
                    success_updates.append({"id": report_id, "status": new_status})
                else:
                    failed_updates.append({"id": report_id, "error": "Report not found"})
                    
            except Exception as e:
                failed_updates.append({"id": update.get("id"), "error": str(e)})
        
        return {
            "success_updates": success_updates,
            "failed_updates": failed_updates,
            "total_success": len(success_updates),
            "total_failed": len(failed_updates)
        }
    
    @classmethod
    def delete_report(cls, report_id, user_id=None):
        """Delete an operational report and remove from vector store.
        
        Args:
            report_id: Report ID
            user_id: User ID for access control
            
        Returns:
            Boolean indicating success
        """
        report = cls.model.get_by_id(report_id)
        if not report:
            return False
            
        # Check if user has permission to delete
        if user_id and report.created_by != user_id:
            return False
        
        # Remove from vector store first
        exists, kb_info = KnowledgebaseService.get_by_id(report.kb_id)
        if exists:
            cls._remove_from_vector_store(report_id, kb_info)
            
        # Physical delete
        query = cls.model.delete().where(cls.model.id == report_id)
        return query.execute() > 0
    
    @classmethod
    def get_by_id(cls, report_id, user_id=None):
        """Get operational report by ID with access control.
        
        Args:
            report_id: Report ID
            user_id: User ID for access control
            
        Returns:
            Report object or None
        """
        try:
            report = cls.model.get(
                (cls.model.id == report_id) & 
                (cls.model.status == StatusEnum.VALID.value) &
                (cls.model.report_status != "已删除")
            )
            
            # Check access control - 用户可以看到自己的报告和其他人的已生效报告
            if user_id:
                if report.created_by != user_id and report.report_status != "已生效":
                    return None
                    
            return report
        except cls.model.DoesNotExist:
            return None
    
    @classmethod
    def get_user_reports(cls, user_id, page_number=1, items_per_page=20, 
                        orderby="create_time", desc=True, keywords=""):
        """Get reports created by a specific user.
        
        Args:
            user_id: User ID
            page_number: Page number for pagination
            items_per_page: Number of items per page
            orderby: Field to order by
            desc: Boolean indicating descending order
            
        Returns:
            Tuple of (report_list, total_count)
        """
        reports = cls.model.select().where(
            (cls.model.created_by == user_id) & 
            (cls.model.status == StatusEnum.VALID.value) &
            (cls.model.report_status != "已删除")
        )
            
        count = reports.count()
        
        # Apply sorting
        if desc:
            reports = reports.order_by(cls.model.getter_by(orderby).desc())
        else:
            reports = reports.order_by(cls.model.getter_by(orderby).asc())
            
        # Apply pagination
        if page_number and items_per_page:
            reports = reports.paginate(page_number, items_per_page)
            
        return list(reports.dicts()), count 