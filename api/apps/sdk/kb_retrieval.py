from flask import jsonify
from flask import request
from api import settings
from api.db import LLMType
from api.db.services.llm_service import LLMBundle
from api.db.services.figure_service import FigureService
from api.utils.api_utils import get_json_result
from rag.prompts import full_question
from rag.nlp import search
from rag.utils.doc_store_conn import OrderByExpr
from rag.utils.storage_factory import STORAGE_IMPL
from datetime import timedelta
import json
import logging
import os
import pandas as pd

# 全局配置初始化(模块加载时执行一次)
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'noauth_config.json')
try:
    with open(_CONFIG_PATH, 'r') as f:
        CONFIG = json.load(f)
    logger = logging.getLogger(__name__)
    logger.info('成功加载免认证配置')
except Exception as e:
    logging.error(f"配置加载失败: {str(e)}")
    raise RuntimeError("系统配置初始化失败")

def _create_trace_span(main_trace, name, input_data=None, output_data=None):
    """通用的trace span创建函数"""
    if not main_trace:
        return None
    try:
        from api.utils.langfuse_utils import create_span_with_langfuse
        return create_span_with_langfuse(main_trace, name, input_data, output_data)
    except Exception as e:
        logging.warning(f"Failed to create span {name}: {e}")
        return None

def process_image_urls(chunks):
    """处理chunks中的图片URL，为包含image的chunk生成带有时效性的访问URL"""
    for chunk in chunks:
        if 'doc_type_kwd' in chunk and 'image' in chunk['doc_type_kwd'] and 'image_id' in chunk:
            try:
                # img_id格式为[bucket]_[file_name]
                bucket, filename = chunk['image_id'].split('-', 1)
                # 如果有image_name，使用它作为下载文件名
                response_headers = None
                if 'image_name' in chunk:
                    response_headers = {
                        'response-content-disposition': f'attachment; filename="{chunk["image_name"]}"'
                    }
                # 生成24小时有效的预签名URL
                presigned_url = STORAGE_IMPL.get_presigned_url(bucket, filename, timedelta(hours=24), response_headers=response_headers)
                if presigned_url:
                    chunk['image_url'] = presigned_url
            except Exception as e:
                logging.error(f"生成图片URL失败: {str(e)}")
    return chunks

@manager.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "message": "server is up and running",
        "version": "1.0.0"
    })

@manager.route('/chunks/retrieval', methods=['POST'])
def chunks_retrieval():
    req = request.json
    top_k = req['top_k']
    vector_similarity_weight = req['vector_similarity_weight']
    similarity_threshold = req['similarity_threshold']
    query = req['query']
    tenant_id = CONFIG['tenant_id']
    embedding_model_name = CONFIG['embedding_model']
    kb_ids = CONFIG['kb_ids']
    
    # 使用with语句自动管理LLMBundle资源
    with LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name) as embed_mdl:
        # 初始化langfuse trace
        main_trace = None
        try:
            from api.utils.langfuse_utils import LangfuseUtils
            langfuse_client = LangfuseUtils.get_client(tenant_id)
            main_trace = LangfuseUtils.create_trace(
                langfuse_client,
                name="document_search",
                input_data={
                    "query": query,
                    "kb_ids": kb_ids,
                    "tenant_id": tenant_id,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                    "vector_similarity_weight": vector_similarity_weight,
                    "embedding_model": embedding_model_name
                },
                metadata={
                    "type": "document_search", 
                    "kb_count": len(kb_ids),
                    "endpoint": "/chunks/retrieval"
                }
            )
        except Exception as e:
            logging.warning(f"Failed to create main trace: {e}")

        chunks_res = settings.retrievaler.retrieval(
            query,
            embed_mdl,
            tenant_id,
            kb_ids,
            1,
            top_k,
            similarity_threshold,
            vector_similarity_weight,
            1024,
            main_trace=main_trace
        )

        # 完成trace记录
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "search_complete": True,
                    "final_results": {
                        "total": chunks_res.get("total", 0),
                        "returned_chunks": len(chunks_res.get("chunks", [])),
                        "doc_aggs_count": len(chunks_res.get("doc_aggs", [])),
                        "has_results": len(chunks_res.get("chunks", [])) > 0
                    }
                })
            except Exception as e:
                logging.warning(f"Failed to finalize trace: {e}")

        remove_keys = ['positions', 'vector', 'content_ltks']
        for c in chunks_res["chunks"]:
            for key in remove_keys:
                c.pop(key, None)
        
        # 处理图片URL
        chunks_res["chunks"] = process_image_urls(chunks_res["chunks"])
        
        # 将最终返回的 chunks 结果添加到 main_trace 中
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "final_chunks_data": {
                        "chunks": chunks_res.get("chunks", [])[:10],  # 前10个chunks
                        "total_chunks_count": len(chunks_res.get("chunks", []))  # 总数
                    }
                })
            except Exception as e:
                logging.warning(f"Failed to add chunks data to trace: {e}")
        
        return jsonify(chunks_res)

@manager.route('/knowledgegraph/retrieval', methods=['POST'])
def knowledegraph_retrieval():
    req = request.json
    query = req['query']
    tenant_id = CONFIG['tenant_id']
    embedding_model_name = CONFIG['embedding_model']
    kb_ids = CONFIG['kb_ids']
    
    # 使用with语句自动管理LLMBundle资源
    with LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name) as embed_mdl, \
         LLMBundle(tenant_id, LLMType.CHAT) as chat_mdl:
        
        # 初始化langfuse trace
        main_trace = None
        try:
            from api.utils.langfuse_utils import LangfuseUtils
            langfuse_client = LangfuseUtils.get_client(tenant_id)
            main_trace = LangfuseUtils.create_trace(
                langfuse_client,
                name="knowledge_graph_retrieval",
                input_data={
                    "query": query,
                    "kb_ids": kb_ids,
                    "tenant_id": tenant_id,
                    "embedding_model": embedding_model_name
                },
                metadata={
                    "type": "knowledge_graph_retrieval", 
                    "kb_count": len(kb_ids),
                    "endpoint": "/knowledgegraph/retrieval"
                }
            )
        except Exception as e:
            logging.warning(f"Failed to create main trace: {e}")
        
        # 跟踪知识图谱检索开始
        _create_trace_span(
            main_trace, "kg_retrieval_start",
            input_data={
                "query": query,
                "query_length": len(query),
                "kb_ids": kb_ids,
                "embedding_model": embedding_model_name
            }
        )
        
        kbinfos = settings.kg_retrievaler.structure_retrieval(
            query,
            tenant_id,
            kb_ids,
            embed_mdl,
            chat_mdl,
            main_trace=main_trace
        )
        
        # 跟踪知识图谱检索完成
        _create_trace_span(
            main_trace, "kg_retrieval_complete",
            input_data={
                "query": query
            },
            output_data={
                "entities_count": len(kbinfos.get("entities", [])) if kbinfos else 0,
                "relations_count": len(kbinfos.get("relations", [])) if kbinfos else 0,
                "chunks_count": len(kbinfos.get("chunks", [])) if kbinfos else 0,
                "has_results": bool(kbinfos and (kbinfos.get("entities") or kbinfos.get("relations") or kbinfos.get("chunks")))
            }
        )
        
        # 完成trace记录
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "kg_retrieval_complete": True,
                    "final_results": {
                        "entities_count": len(kbinfos.get("entities", [])) if kbinfos else 0,
                        "relations_count": len(kbinfos.get("relations", [])) if kbinfos else 0,
                        "chunks_count": len(kbinfos.get("chunks", [])) if kbinfos else 0,
                        "has_results": bool(kbinfos and (kbinfos.get("entities") or kbinfos.get("relations") or kbinfos.get("chunks")))
                    }
                })
            except Exception as e:
                logging.warning(f"Failed to finalize trace: {e}")
        
        return jsonify(kbinfos)

@manager.route('/multiturn/chunks/retrieval', methods=['POST'])
def multiturn_chunks_retrieval():
    req = request.json
    refine_multiturn = req.get("refine_multiturn", False)
    history = req['history']
    top_k = req['top_k']
    vector_similarity_weight = req['vector_similarity_weight']
    similarity_threshold = req['similarity_threshold']
    tenant_id = CONFIG['tenant_id']
    embedding_model_name = CONFIG['embedding_model']
    llm_id = CONFIG['llm_id']
    kb_ids = CONFIG['kb_ids']
    assert history[-1]["role"] == "user", "The last content of this conversation is not from user."
    
    # 使用with语句自动管理LLMBundle资源
    with LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name) as embed_mdl, \
         LLMBundle(tenant_id, LLMType.CHAT) as chat_mdl:
        
        # 初始化langfuse trace
        main_trace = None
        try:
            from api.utils.langfuse_utils import LangfuseUtils
            langfuse_client = LangfuseUtils.get_client(tenant_id)
            main_trace = LangfuseUtils.create_trace(
                langfuse_client,
                name="multiturn_document_search",
                input_data={
                    "original_history": history,
                    "refine_multiturn": refine_multiturn,
                    "kb_ids": kb_ids,
                    "tenant_id": tenant_id,
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                    "vector_similarity_weight": vector_similarity_weight,
                    "embedding_model": embedding_model_name
                },
                metadata={
                    "type": "multiturn_document_search", 
                    "kb_count": len(kb_ids),
                    "endpoint": "/multiturn/chunks/retrieval",
                    "history_length": len(history)
                }
            )
        except Exception as e:
            logging.warning(f"Failed to create main trace: {e}")
        
        # 跟踪问题提取过程
        questions = [m["content"] for m in history if m["role"] == "user"][-3:]
        original_questions = questions.copy()
        
        _create_trace_span(
            main_trace, "extract_user_questions",
            input_data={
                "history_length": len(history),
                "total_user_messages": len([m for m in history if m["role"] == "user"]),
                "extracted_questions": original_questions,
                "questions_count": len(original_questions)
            }
        )
        
        # 跟踪问题精炼过程
        if len(questions) > 1 and refine_multiturn:
            _create_trace_span(
                main_trace, "question_refinement_start",
                input_data={
                    "refine_multiturn": refine_multiturn,
                    "original_questions": original_questions,
                    "will_use_llm": True,
                    "llm_id": llm_id
                }
            )
            
            questions = [full_question(tenant_id, llm_id, history)]
            
            _create_trace_span(
                main_trace, "question_refinement_complete",
                input_data={
                    "original_questions": original_questions,
                    "refined_question": questions[0]
                },
                output_data={
                    "refinement_applied": True,
                    "original_question_count": len(original_questions),
                    "final_question": questions[0],
                    "question_length_change": len(questions[0]) - sum(len(q) for q in original_questions)
                }
            )
        else:
            questions = questions[-1:]
            _create_trace_span(
                main_trace, "question_refinement_complete",
                input_data={
                    "refine_multiturn": refine_multiturn,
                    "original_questions": original_questions,
                    "will_use_llm": False
                },
                output_data={
                    "refinement_applied": False,
                    "final_question": questions[0],
                    "reason": "single_question_or_refinement_disabled"
                }
            )
        
        refined_question = questions[-1]
        logging.info(f"Refine question is : {refined_question}")

        # 更新trace中的refined_question
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "refined_question": refined_question
                })
            except Exception as e:
                logging.warning(f"Failed to update trace with refined question: {e}")

        chunks_res = settings.retrievaler.retrieval(
            refined_question,
            embed_mdl,
            tenant_id,
            kb_ids,
            1,
            top_k,
            similarity_threshold,
            vector_similarity_weight,
            1024,
            main_trace=main_trace
        )

        # 完成trace记录
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "search_complete": True,
                    "final_results": {
                        "total": chunks_res.get("total", 0),
                        "returned_chunks": len(chunks_res.get("chunks", [])),
                        "doc_aggs_count": len(chunks_res.get("doc_aggs", [])),
                        "has_results": len(chunks_res.get("chunks", [])) > 0
                    }
                })
            except Exception as e:
                logging.warning(f"Failed to finalize trace: {e}")

        remove_keys = ['positions', 'vector', 'content_ltks']
        for c in chunks_res["chunks"]:
            for key in remove_keys:
                c.pop(key, None)
        
        # 处理图片URL
        chunks_res["chunks"] = process_image_urls(chunks_res["chunks"])
        
        # 将最终返回的 chunks 结果添加到 main_trace 中
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "final_chunks_data": {
                        "chunks": chunks_res.get("chunks", [])[:10],  # 前10个chunks
                        "total_chunks_count": len(chunks_res.get("chunks", []))  # 总数
                    }
                })
            except Exception as e:
                logging.warning(f"Failed to add chunks data to trace: {e}")
        
        return jsonify(chunks_res)

@manager.route('/multiturn/kg/retrieval', methods=['POST'])
def multiturn_kg_retrieval():
    req = request.json
    refine_multiturn = req.get("refine_multiturn", False)
    history = req['history']
    tenant_id = CONFIG['tenant_id']
    embedding_model_name = CONFIG['embedding_model']
    llm_id = CONFIG['llm_id']
    kb_ids = CONFIG['kb_ids']
    assert history[-1]["role"] == "user", "The last content of this conversation is not from user."
    
    # 使用with语句自动管理LLMBundle资源
    with LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name) as embed_mdl, \
         LLMBundle(tenant_id, LLMType.CHAT) as chat_mdl:
        
        # 初始化langfuse trace
        main_trace = None
        try:
            from api.utils.langfuse_utils import LangfuseUtils
            langfuse_client = LangfuseUtils.get_client(tenant_id)
            main_trace = LangfuseUtils.create_trace(
                langfuse_client,
                name="multiturn_knowledge_graph_retrieval",
                input_data={
                    "original_history": history,
                    "refine_multiturn": refine_multiturn,
                    "kb_ids": kb_ids,
                    "tenant_id": tenant_id,
                    "embedding_model": embedding_model_name
                },
                metadata={
                    "type": "multiturn_knowledge_graph_retrieval", 
                    "kb_count": len(kb_ids),
                    "endpoint": "/multiturn/kg/retrieval",
                    "history_length": len(history)
                }
            )
        except Exception as e:
            logging.warning(f"Failed to create main trace: {e}")
        
        # 跟踪问题提取过程
        questions = [m["content"] for m in history if m["role"] == "user"][-3:]
        original_questions = questions.copy()
        
        _create_trace_span(
            main_trace, "extract_user_questions",
            input_data={
                "history_length": len(history),
                "total_user_messages": len([m for m in history if m["role"] == "user"]),
                "extracted_questions": original_questions,
                "questions_count": len(original_questions)
            }
        )
        
        # 跟踪问题精炼过程
        if len(questions) > 1 and refine_multiturn:
            _create_trace_span(
                main_trace, "question_refinement_start",
                input_data={
                    "refine_multiturn": refine_multiturn,
                    "original_questions": original_questions,
                    "will_use_llm": True,
                    "llm_id": llm_id
                }
            )
            
            questions = [full_question(tenant_id, llm_id, history)]
            
            _create_trace_span(
                main_trace, "question_refinement_complete",
                input_data={
                    "original_questions": original_questions,
                    "refined_question": questions[0]
                },
                output_data={
                    "refinement_applied": True,
                    "original_question_count": len(original_questions),
                    "final_question": questions[0],
                    "question_length_change": len(questions[0]) - sum(len(q) for q in original_questions)
                }
            )
        else:
            questions = questions[-1:]
            _create_trace_span(
                main_trace, "question_refinement_complete",
                input_data={
                    "refine_multiturn": refine_multiturn,
                    "original_questions": original_questions,
                    "will_use_llm": False
                },
                output_data={
                    "refinement_applied": False,
                    "final_question": questions[0],
                    "reason": "single_question_or_refinement_disabled"
                }
            )
        
        refined_question = questions[-1]
        logging.info(f"Refine question is : {refined_question}")
        
        # 更新trace中的refined_question
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "refined_question": refined_question
                })
            except Exception as e:
                logging.warning(f"Failed to update trace with refined question: {e}")
        
        # 跟踪知识图谱检索开始
        _create_trace_span(
            main_trace, "kg_retrieval_start",
            input_data={
                "refined_question": refined_question,
                "query_length": len(refined_question),
                "kb_ids": kb_ids,
                "embedding_model": embedding_model_name
            }
        )
        
        kbinfos = settings.kg_retrievaler.structure_retrieval(
            refined_question,
            tenant_id,
            kb_ids,
            embed_mdl,
            chat_mdl,
            main_trace=main_trace
        )
        
        # 跟踪知识图谱检索完成
        _create_trace_span(
            main_trace, "kg_retrieval_complete",
            input_data={
                "refined_question": refined_question
            },
            output_data={
                "entities_count": len(kbinfos.get("entities", [])) if kbinfos else 0,
                "relations_count": len(kbinfos.get("relations", [])) if kbinfos else 0,
                "chunks_count": len(kbinfos.get("chunks", [])) if kbinfos else 0,
                "has_results": bool(kbinfos and (kbinfos.get("entities") or kbinfos.get("relations") or kbinfos.get("chunks")))
            }
        )
        
        # 完成trace记录
        if main_trace:
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.update_trace(main_trace, {
                    "kg_retrieval_complete": True,
                    "final_results": {
                        "entities_count": len(kbinfos.get("entities", [])) if kbinfos else 0,
                        "relations_count": len(kbinfos.get("relations", [])) if kbinfos else 0,
                        "chunks_count": len(kbinfos.get("chunks", [])) if kbinfos else 0,
                        "has_results": bool(kbinfos and (kbinfos.get("entities") or kbinfos.get("relations") or kbinfos.get("chunks")))
                    }
                })
            except Exception as e:
                logging.warning(f"Failed to finalize trace: {e}")
        
        return jsonify(kbinfos)

@manager.route('/figures', methods=['GET'])
@manager.route('/figures/page/<int:page>', methods=['GET'])
@manager.route('/figures/page/<int:page>/size/<int:page_size>', methods=['GET'])
def get_figures(page=1, page_size=20):
    """
    查询figure表中的图片数据
    路径参数:
    - page: 页码，默认为1
    - page_size: 每页数量，默认为20
    
    支持的路径格式:
    - /figures - 查询所有，使用默认分页
    - /figures/page/2 - 指定页码
    - /figures/page/2/size/10 - 指定页码和每页数量
    """
    try:
        # 从配置获取kb_ids
        kb_ids = CONFIG['kb_ids']
        
        # 计算偏移量
        offset = (page - 1) * page_size
        
        # 构建查询条件
        query_conditions = [FigureService.model.kb_id.in_(kb_ids)]
        
        # 执行查询
        figures_query = FigureService.model.select().where(*query_conditions)
            
        # 获取总数
        total = figures_query.count()
        
        # 分页查询
        figures = figures_query.order_by(FigureService.model.create_time.desc()).offset(offset).limit(page_size)
        
        # 转换为字典并生成预签名URL
        figure_list = []
        for figure in figures:
            figure_dict = figure.to_dict()
            
            # 生成预签名URL - 使用现有的逻辑
            if figure_dict.get('img_id'):
                try:
                    bucket, filename = figure_dict['img_id'].split('-', 1)
                    response_headers = None
                    response_headers = {
                        'response-content-disposition': f'attachment; filename="{filename}.jpg"'
                    }
                    presigned_url = STORAGE_IMPL.get_presigned_url(bucket, filename, timedelta(hours=24), response_headers=response_headers)
                    if presigned_url:
                        figure_dict['image_url'] = presigned_url
                except Exception as e:
                    logging.error(f"生成图片URL失败: {str(e)}")
            
            # 移除不需要的字段
            remove_keys = ['doc_id', 'kb_id', 'metadata', 'page_num', 'update_time', 'update_date']
            for key in remove_keys:
                figure_dict.pop(key, None)
            
            figure_list.append(figure_dict)
        
        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "figures": figure_list,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
        })
        
    except Exception as e:
        logging.error(f"查询figures失败: {str(e)}")
        return jsonify({
            "code": 500,
            "message": f"查询figures失败: {str(e)}",
            "data": None
        })

@manager.route('/figures/<figure_id>', methods=['GET'])
def get_figure_by_id(figure_id):
    """
    根据ID查询单个figure
    """
    try:
        # 从配置获取kb_ids
        kb_ids = CONFIG['kb_ids']
        
        figure = FigureService.get_by_id(figure_id)
        if not figure[0]:
            return jsonify({
                "code": 404,
                "message": "Figure not found",
                "data": None
            })
        
        figure_dict = figure[1].to_dict()
        
        # 检查figure是否属于配置的知识库
        if figure_dict.get('kb_id') not in kb_ids:
            return jsonify({
                "code": 403,
                "message": "Access denied: Figure not in configured knowledge bases",
                "data": None
            })
        
        # 生成预签名URL - 使用现有的逻辑
        if figure_dict.get('img_id'):
            try:
                bucket, filename = figure_dict['img_id'].split('-', 1)
                response_headers = None
                response_headers = {
                        'response-content-disposition': f'attachment; filename="{filename}.jpg"'
                    }
                presigned_url = STORAGE_IMPL.get_presigned_url(bucket, filename, timedelta(hours=24), response_headers=response_headers)
                if presigned_url:
                    figure_dict['image_url'] = presigned_url
            except Exception as e:
                logging.error(f"生成图片URL失败: {str(e)}")
        
        # 移除不需要的字段
        remove_keys = ['doc_id', 'kb_id', 'metadata', 'page_num', 'update_time', 'update_date']
        for key in remove_keys:
            figure_dict.pop(key, None)
        
        return jsonify({
            "code": 0,
            "message": "success",
            "data": figure_dict
        })
        
    except Exception as e:
        logging.error(f"查询figure失败: {str(e)}")
        return jsonify({
            "code": 500,
            "message": f"查询figure失败: {str(e)}",
            "data": None
        })

@manager.route('/chunks/debug', methods=['POST'])
def chunks_debug():
    req = request.json
    doc_id = req.get('doc_id')
    kb_id = req.get('kb_id')
    tenant_id = req.get('tenant_id')
    
    if not doc_id or not kb_id or not tenant_id:
        return jsonify({
            "code": 400,
            "message": "doc_id, kb_id and tenant_id are required",
            "data": None
        })
    
    try:
        # 创建OrderByExpr实例
        order_by = OrderByExpr()
        order_by.asc("page_num_int")  # 按页码升序排序
        
        # 使用文档引擎查询指定doc_id的所有chunk
        chunks_df, total = settings.docStoreConn.search(
            selectFields=["*"],  # 选择所有字段
            highlightFields=[],  # 不需要高亮
            condition={"doc_id": doc_id},  # 按doc_id过滤
            matchExprs=[],  # 不需要匹配表达式
            orderBy=order_by,  # 使用OrderByExpr实例
            offset=0,
            limit=1000,  # 设置一个较大的限制
            indexNames=search.index_name(tenant_id),  # 使用正确的索引名称
            knowledgebaseIds=[kb_id]  # 指定知识库ID
        )
        
        # 使用getFields方法处理返回结果
        chunks = settings.docStoreConn.getFields(chunks_df, chunks_df.columns.tolist())
        chunks = list(chunks.values())  # 转换为列表
        
        # 移除不需要的字段
        remove_keys = ['positions', 'vector', 'content_ltks', 'q_1024_vec']
        for chunk in chunks:
            for key in remove_keys:
                if key in chunk:
                    del chunk[key]
        
        return jsonify({
            "code": 0,
            "message": "success",
            "data": {
                "total": total,
                "chunks": chunks
            }
        })
        
    except Exception as e:
        logging.error(f"Error querying chunks: {str(e)}")
        return jsonify({
            "code": 500,
            "message": f"Error querying chunks: {str(e)}",
            "data": None
        })