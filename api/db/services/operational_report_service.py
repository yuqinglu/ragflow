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
            "title": report.title,
            "report_data": report.report_data
        }
        
        # 将完整报告转换为JSON字符串，直接存储在content_with_weight中
        report_json_text = json.dumps(complete_report_json, ensure_ascii=False, indent=2)
        
        chunk = {
            "id": xxhash.xxh64((report_json_text + str(report.id)).encode("utf-8")).hexdigest(),
            "doc_id": report.id,
            "kb_id": [kb_info.id],
            "docnm_kwd": report.title,
            "title_tks": rag_tokenizer.tokenize(report.title),
            "content_with_weight": report_json_text,  # 直接存储完整的JSON
            "content_ltks": rag_tokenizer.tokenize(report_json_text),
            "content_sm_ltks": rag_tokenizer.fine_grained_tokenize(report_json_text),
            "create_time": str(datetime.now()).replace("T", " ")[:19],
            "create_timestamp_flt": datetime.now().timestamp(),
            "doc_type_kwd": "operational_report",
            "created_by": report.created_by or "",
            "group_id": report.group_id or "",
            "important_kwd": [],
            "question_kwd": [],
            "page_num_int": [1],  
            "position_int": [],  
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
            logging.error(f"Report title: {report.title}")
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
                {"doc_id": report_id}, 
                index_name, 
                kb_info.id
            )
            logging.info(f"Successfully removed report {report_id} from vector store")
            return True
        except Exception as e:
            logging.error(f"Failed to remove report {report_id} from vector store: {e}")
            return False
    
    @classmethod
    def get_by_kb_id(cls, kb_id, user_id=None, group_id=None, page_number=1, 
                     items_per_page=20, orderby="create_time", desc=True, keywords=""):
        """Get operational reports by knowledge base ID with pagination and filtering.
        
        Args:
            kb_id: Knowledge base ID
            user_id: User ID for access control
            group_id: Group ID for access control
            page_number: Page number for pagination
            items_per_page: Number of items per page
            orderby: Field to order by
            desc: Boolean indicating descending order
            keywords: Search keywords
            
        Returns:
            Tuple of (report_list, total_count)
        """
        reports = cls.model.select().where(
            (cls.model.kb_id == kb_id) & 
            (cls.model.status == StatusEnum.VALID.value)
        )
        
        # Apply user/group access control
        if user_id and group_id:
            reports = reports.where(
                (cls.model.created_by == user_id) | 
                (cls.model.group_id == group_id)
            )
        elif user_id:
            reports = reports.where(cls.model.created_by == user_id)
        elif group_id:
            reports = reports.where(cls.model.group_id == group_id)
            
        # Apply keyword search
        if keywords:
            reports = reports.where(
                fn.LOWER(cls.model.title).contains(keywords.lower())
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
    
    @classmethod
    def vector_search(cls, query, kb_id, user_id=None, group_id=None, 
                     page_number=1, items_per_page=20, similarity_threshold=0.2,
                     vector_similarity_weight=0.3):
        """Perform vector-based search on operational reports.
        
        Args:
            query: Search query
            kb_id: Knowledge base ID
            user_id: User ID for access control
            group_id: Group ID for access control
            page_number: Page number for pagination
            items_per_page: Number of items per page
            similarity_threshold: Minimum similarity threshold
            vector_similarity_weight: Weight for vector similarity
            
        Returns:
            Dictionary with search results
        """
        try:
            # Get knowledge base info
            exists, kb_info = KnowledgebaseService.get_by_id(kb_id)
            if not exists:
                return {"total": 0, "reports": []}
            
            # Perform vector search
            with LLMBundle(kb_info.tenant_id, LLMType.EMBEDDING, kb_info.embd_id) as embd_mdl:
                ranks = settings.retrievaler.retrieval(
                    question=query,
                    embd_mdl=embd_mdl,
                    tenant_ids=kb_info.tenant_id,
                    kb_ids=[kb_id],
                    page=page_number,
                    page_size=items_per_page,
                    similarity_threshold=similarity_threshold,
                    vector_similarity_weight=vector_similarity_weight,
                    top=1024
                )
                
                # Filter results by source type and access control
                filtered_chunks = []
                for chunk in ranks.get("chunks", []):
                    # Only include operational report chunks
                    if isinstance(chunk.get("doc_type_kwd"), str):
                        if chunk.get("doc_type_kwd") != "operational_report":
                            continue
                    elif isinstance(chunk.get("doc_type_kwd"), list):
                        if 'operational_report' not in chunk.get("doc_type_kwd"):
                            continue
                    
                    # Apply access control
                    if user_id and group_id:
                        chunk_user = chunk.get("created_by", "")
                        chunk_group = chunk.get("group_id", "")
                        if chunk_user != user_id and chunk_group != group_id:
                            continue
                    elif user_id:
                        if chunk.get("created_by", "") != user_id:
                            continue
                    elif group_id:
                        if chunk.get("group_id", "") != group_id:
                            continue
                    
                    # 收集通过访问控制的报告ID和相似度
                    filtered_chunks.append({
                        "report_id": chunk.get("doc_id"),
                        "similarity": chunk.get("similarity", 0)
                    })
                
                # 根据页数和页面大小要求获取chunk
                start_index = (page_number - 1) * items_per_page
                end_index = start_index + items_per_page
                paginated_chunks = filtered_chunks[start_index:end_index]
                
                # 从数据库中批量获取完整的报告信息
                if paginated_chunks:
                    report_ids = [chunk_info["report_id"] for chunk_info in paginated_chunks]
                    
                    # 批量查询报告，不进行访问控制校验（前面已经过滤过了）
                    reports = cls.model.select().where(
                        (cls.model.id.in_(report_ids)) & 
                        (cls.model.status == StatusEnum.VALID.value)
                    )
                    
                    # 转换为字典格式，便于查找
                    reports_dict = {report.id: report for report in reports}
                    
                    final_results = []
                    for chunk_info in paginated_chunks:
                        report_id = chunk_info["report_id"]
                        similarity = chunk_info["similarity"]
                        report = reports_dict.get(report_id)
                        report_json = report.to_json()
                        report_json.pop("kb_id")
                        final_results.append({
                            "report": report.to_json(),
                            "similarity": similarity
                        })
                else:
                    final_results = []
                
                return {
                    "total": len(filtered_chunks),
                    "reports": final_results
                }
                
        except Exception as e:
            logging.error(f"Vector search failed: {e}")
            return {"total": 0, "reports": []}
    
    @classmethod
    def create_report(cls, kb_id, title, report_data, created_by, group_id=None):
        """Create a new operational report with vector storage.
        
        Args:
            kb_id: Knowledge base ID
            title: Report title
            report_data: Report data in JSON format
            created_by: User ID who created the report
            group_id: Group ID for access control
            
        Returns:
            Created report object
        """
        from api.utils import get_uuid
        
        # Validate knowledge base exists
        exists, kb_info = KnowledgebaseService.get_by_id(kb_id)
        if not exists:
            raise ValueError(f"Knowledge base {kb_id} not found")
        
        logging.info(f"Creating report in knowledge base {kb_id}, tenant {kb_info.tenant_id}")
        
        report_id = get_uuid()
        report = cls.model.create(
            id=report_id,
            kb_id=kb_id,
            title=title,
            report_data=report_data,
            created_by=created_by,
            group_id=group_id,
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
    def update_report(cls, report_id, title=None, report_data=None, user_id=None):
        """Update an existing operational report and re-vectorize if needed.
        
        Args:
            report_id: Report ID
            title: New title
            report_data: New report data
            user_id: User ID for access control
            
        Returns:
            Boolean indicating success
        """
        report = cls.model.get_by_id(report_id)
        if not report:
            return False
            
        # Check if user has permission to update
        if user_id and report.created_by != user_id:
            return False
            
        update_data = {}
        need_re_vectorize = False
        
        if title is not None:
            update_data['title'] = title
            need_re_vectorize = True
        if report_data is not None:
            update_data['report_data'] = report_data
            need_re_vectorize = True
            
        if update_data:
            query = cls.model.update(**update_data).where(cls.model.id == report_id)
            success = query.execute() > 0
            
            # Re-vectorize if content changed
            if success and need_re_vectorize:
                exists, kb_info = KnowledgebaseService.get_by_id(report.kb_id)
                if exists:
                    # Remove old vector and add new one
                    cls._remove_from_vector_store(report_id, kb_info)
                    # Get updated report
                    updated_report = cls.model.get_by_id(report_id)
                    cls._vectorize_and_store(updated_report, kb_info)
            
            return success
        return True
    
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
            
        query = cls.model.update(status=StatusEnum.INVALID.value).where(cls.model.id == report_id)
        return query.execute() > 0
    
    @classmethod
    def get_by_id(cls, report_id, user_id=None, group_id=None):
        """Get operational report by ID with access control.
        
        Args:
            report_id: Report ID
            user_id: User ID for access control
            group_id: Group ID for access control
            
        Returns:
            Report object or None
        """
        try:
            report = cls.model.get(
                (cls.model.id == report_id) & 
                (cls.model.status == StatusEnum.VALID.value)
            )
            
            # Check access control
            if user_id and group_id:
                if report.created_by != user_id and report.group_id != group_id:
                    return None
            elif user_id:
                if report.created_by != user_id:
                    return None
            elif group_id:
                if report.group_id != group_id:
                    return None
                    
            return report
        except cls.model.DoesNotExist:
            return None
    
    @classmethod
    def check_kb_access(cls, kb_id, user_id):
        """Check if user has access to the knowledge base.
        
        Args:
            kb_id: Knowledge base ID
            user_id: User ID
            
        Returns:
            Boolean indicating access permission
        """
        return KnowledgebaseService.accessible(kb_id, user_id)
    
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
            keywords: Search keywords
            
        Returns:
            Tuple of (report_list, total_count)
        """
        reports = cls.model.select().where(
            (cls.model.created_by == user_id) & 
            (cls.model.status == StatusEnum.VALID.value)
        )
        
        # Apply keyword search
        if keywords:
            reports = reports.where(
                fn.LOWER(cls.model.title).contains(keywords.lower())
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
    
    @classmethod
    def get_group_reports(cls, group_id, page_number=1, items_per_page=20, 
                         orderby="create_time", desc=True, keywords=""):
        """Get reports for a specific group.
        
        Args:
            group_id: Group ID
            page_number: Page number for pagination
            items_per_page: Number of items per page
            orderby: Field to order by
            desc: Boolean indicating descending order
            keywords: Search keywords
            
        Returns:
            Tuple of (report_list, total_count)
        """
        reports = cls.model.select().where(
            (cls.model.group_id == group_id) & 
            (cls.model.status == StatusEnum.VALID.value)
        )
        
        # Apply keyword search
        if keywords:
            reports = reports.where(
                fn.LOWER(cls.model.title).contains(keywords.lower())
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