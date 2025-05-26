from flask import jsonify
from flask import request
from api import settings
from api.db import LLMType
from api.db.services.llm_service import LLMBundle
from api.utils.api_utils import get_json_result
import json
import logging



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
    tenant_id = 'a128a194190911f089ad85162265e498'
    embedding_model_name = 'BAAI/bge-large-zh-v1.5@BAAI'
    embed_mdl = LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name)
    kb_ids = ['d626afca24d111f0bce1a0369f72b8b4']


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
    # return get_json_result(data=chunks_res)


@manager.route('/knowledgegraph/retrieval', methods=['POST'])
def knowledegraph_retrieval():
    req = request.json
    query = req['query']
    tenant_id = 'a128a194190911f089ad85162265e498'
    embedding_model_name = 'BAAI/bge-large-zh-v1.5@BAAI'
    embed_mdl = LLMBundle(tenant_id, LLMType.EMBEDDING, embedding_model_name)
    kb_ids = ['d626afca24d111f0bce1a0369f72b8b4']
    chat_mdl = LLMBundle(tenant_id, LLMType.CHAT)
    kbinfos = settings.kg_retrievaler.structure_retrieval(
        query,
        tenant_id,
        kb_ids,
        embed_mdl,
        chat_mdl,
    )
    return jsonify(kbinfos)
    # return get_json_result(data=kbinfos)
