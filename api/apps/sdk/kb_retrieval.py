from flask import jsonify
from flask import request
from api import settings
from api.db import LLMType
from api.db.services.llm_service import LLMBundle
from api.utils.api_utils import get_json_result
from rag.prompts import full_question
import json
import logging
import os

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
    embed_mdl = LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name)

    chunks_res =settings.retrievaler.retrieval(
        query,
        embed_mdl,
        tenant_id,
        kb_ids,
        1,
        top_k,
        similarity_threshold,
        vector_similarity_weight,
        1024
    )

    remove_keys = ['positions', 'vector', 'content_ltks']
    for c in chunks_res["chunks"]:
        for key in remove_keys:
            c.pop(key, None)
    return jsonify(chunks_res)


@manager.route('/knowledgegraph/retrieval', methods=['POST'])
def knowledegraph_retrieval():
    req = request.json
    query = req['query']
    tenant_id = CONFIG['tenant_id']
    embedding_model_name = CONFIG['embedding_model']
    kb_ids = CONFIG['kb_ids']
    embed_mdl = LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name)
    chat_mdl = LLMBundle(tenant_id, LLMType.CHAT)
    kbinfos = settings.kg_retrievaler.structure_retrieval(
        query,
        tenant_id,
        kb_ids,
        embed_mdl,
        chat_mdl,
    )
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
    embed_mdl = LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name)
    kb_ids = CONFIG['kb_ids']
    chat_mdl = LLMBundle(tenant_id, LLMType.CHAT)
    assert history[-1]["role"] == "user", "The last content of this conversation is not from user."
    questions = [m["content"] for m in history if m["role"] == "user"][-3:]
    if len(questions) > 1 and refine_multiturn:
        questions = [full_question(tenant_id, llm_id, history)]
    else:
        questions = questions[-1:]
    refined_question = questions[-1]
    logging.info(f"Refine question is : {refined_question}")
    chunks_res =settings.retrievaler.retrieval(
        refined_question,
        embed_mdl,
        tenant_id,
        kb_ids,
        1,
        top_k,
        similarity_threshold,
        vector_similarity_weight,
        1024
    )
    remove_keys = ['positions', 'vector', 'content_ltks']
    for c in chunks_res["chunks"]:
        for key in remove_keys:
            c.pop(key, None)
    return jsonify(chunks_res)

@manager.route('/multiturn/kg/retrieval', methods=['POST'])
def multiturn_kg_retrieval():
    req = request.json
    refine_multiturn = req.get("refine_multiturn", False)
    history = req['history']
    tenant_id = CONFIG['tenant_id']
    embedding_model_name = CONFIG['embedding_model']
    embed_mdl = LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name)
    llm_id = CONFIG['llm_id']
    chat_mdl = LLMBundle(tenant_id, LLMType.CHAT)
    kb_ids = CONFIG['kb_ids']
    assert history[-1]["role"] == "user", "The last content of this conversation is not from user."
    questions = [m["content"] for m in history if m["role"] == "user"][-3:]
    if len(questions) > 1 and refine_multiturn:
        questions = [full_question(tenant_id, llm_id, history)]
    else:
        questions = questions[-1:]
    refined_question = questions[-1]
    logging.info(f"Refine question is : {refined_question}")
    kbinfos = settings.kg_retrievaler.structure_retrieval(
        refined_question,
        tenant_id,
        kb_ids,
        embed_mdl,
        chat_mdl,
    )
    return jsonify(kbinfos)