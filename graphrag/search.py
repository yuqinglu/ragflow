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
#  WITHOUT WARRANTIES OR CONDITION OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import json
import logging
from collections import defaultdict
from copy import deepcopy
import json_repair
import pandas as pd
import trio

from api.utils import get_uuid
from graphrag.query_analyze_prompt import PROMPTS
from graphrag.utils import get_entity_type2sampels, get_llm_cache, set_llm_cache, get_relation
from rag.utils import num_tokens_from_string, get_float
from rag.utils.doc_store_conn import OrderByExpr

from rag.nlp.search import Dealer, index_name


class KGSearch(Dealer):
    def _chat(self, llm_bdl, system, history, gen_conf):
        response = get_llm_cache(llm_bdl.llm_name, system, history, gen_conf)
        if response:
            return response
        response = llm_bdl.chat(system, history, gen_conf)
        if response.find("**ERROR**") >= 0:
            raise Exception(response)
        set_llm_cache(llm_bdl.llm_name, system, response, history, gen_conf)
        return response

    def query_rewrite(self, llm, question, idxnms, kb_ids):
        ty2ents = trio.run(lambda: get_entity_type2sampels(idxnms, kb_ids))
        hint_prompt = PROMPTS["minirag_query2kwd"].format(query=question,
                                                          TYPE_POOL=json.dumps(ty2ents, ensure_ascii=False, indent=2))
        logging.info("准备好图谱查询的提示词")
        result = self._chat(llm, hint_prompt, [{"role": "user", "content": "Output:"}], {"temperature": .5})
        logging.info("完成图谱查询关键字准备")
        logging.info(f"result is {result}")
        try:
            keywords_data = json_repair.loads(result)
            type_keywords = keywords_data.get("answer_type_keywords", [])
            entities_from_query = keywords_data.get("entities_from_query", [])[:5]
            return type_keywords, entities_from_query
        except json_repair.JSONDecodeError:
            try:
                result = result.replace(hint_prompt[:-1], '').replace('user', '').replace('model', '').strip()
                result = '{' + result.split('{')[1].split('}')[0] + '}'
                keywords_data = json_repair.loads(result)
                type_keywords = keywords_data.get("answer_type_keywords", [])
                entities_from_query = keywords_data.get("entities_from_query", [])[:5]
                return type_keywords, entities_from_query
            # Handle parsing error
            except Exception as e:
                logging.exception(f"JSON parsing error: {result} -> {e}")
                raise e

    def _ent_info_from_(self, es_res, sim_thr=0.3):
        res = {}
        flds = ["content_with_weight", "_score", "SIMILARITY", "SCORE","entity_kwd", "rank_flt", "n_hop_with_weight"]
        es_res = self.dataStore.getFields(es_res, flds)
        for _, ent in es_res.items():
            for f in flds:
                if f in ent and ent[f] is None:
                    del ent[f]
            #FIXME: 返回的字段根本没有_score这个字段，这里需要确认infinity的查询逻辑，并进行修复
            if get_float(ent.get("_score", 0)) < sim_thr and get_float(ent.get("SIMILARITY", 0)) < sim_thr\
                    and get_float(ent.get("SCORE", 0)) < sim_thr:
                continue
            if not ent.get("entity_kwd", None):
                continue
            if isinstance(ent["entity_kwd"], list):
                ent["entity_kwd"] = ent["entity_kwd"][0]
            content_with_weight = ent.get("content_with_weight", "{}")
            res[ent["entity_kwd"]] = {
                "sim": get_float(ent.get("_score", 0)) + get_float(ent.get("SIMILARITY", 0)) + get_float(ent.get("SCORE", 0)),
                "pagerank": get_float(json.loads(content_with_weight).get("pagerank", 0)),
                "n_hop_ents": json.loads(ent.get("n_hop_with_weight", "[]")),
                "description": content_with_weight
            }
        return res

    def _relation_info_from_(self, es_res, sim_thr=0.3):
        res = {}
        es_res = self.dataStore.getFields(es_res, ["content_with_weight", "_score", "SIMILARITY", "SCORE", "from_entity_kwd", "to_entity_kwd",
                                                   "weight_int"])
        for _, ent in es_res.items():
            if get_float(ent.get("_score", 0)) < sim_thr and get_float(ent.get("SIMILARITY", 0)) < sim_thr \
                    and get_float(ent.get("SCORE",0)) < sim_thr:
                continue
            if not ent.get("from_entity_kwd", None):
                continue
            if not ent.get("to_entity_kwd", None):
                continue
            f, t = sorted([ent["from_entity_kwd"], ent["to_entity_kwd"]])
            if isinstance(f, list):
                f = f[0]
            if isinstance(t, list):
                t = t[0]
            res[(f, t)] = {
                "sim": max(get_float(ent.get("_score", 0)), get_float(ent.get("SIMILARITY", 0)), get_float(ent.get("SCORE",0))),
                "pagerank": get_float(ent.get("weight_int", 0)),
                "description": ent["content_with_weight"]
            }
        return res

    def get_relevant_ents_by_keywords(self, keywords, filters, idxnms, kb_ids, emb_mdl, sim_thr=0.3, N=56):
        if not keywords:
            return {}
        filters = deepcopy(filters)
        filters["knowledge_graph_kwd"] = "entity"
        matchDense = self.get_vector(", ".join(keywords), emb_mdl, 1024, sim_thr)
        es_res = self.dataStore.search(["content_with_weight", "entity_kwd", "rank_flt"], [], filters, [matchDense],
                                       OrderByExpr(), 0, N,
                                       idxnms, kb_ids)
        return self._ent_info_from_(es_res, sim_thr)

    def get_relevant_relations_by_txt(self, txt, filters, idxnms, kb_ids, emb_mdl, sim_thr=0.3, N=56):
        if not txt:
            return {}
        filters = deepcopy(filters)
        filters["knowledge_graph_kwd"] = "relation"
        matchDense = self.get_vector(txt, emb_mdl, 1024, sim_thr)
        es_res = self.dataStore.search(
            ["content_with_weight", "_score", "from_entity_kwd", "to_entity_kwd", "weight_int"],
            [], filters, [matchDense], OrderByExpr(), 0, N, idxnms, kb_ids)

        return self._relation_info_from_(es_res, sim_thr)

    def get_relevant_ents_by_types(self, types, filters, idxnms, kb_ids, N=56):
        if not types:
            return {}
        filters = deepcopy(filters)
        filters["knowledge_graph_kwd"] = "entity"
        filters["entity_type_kwd"] = types
        ordr = OrderByExpr()
        ordr.desc("rank_flt")
        es_res = self.dataStore.search(["entity_kwd", "rank_flt"], [], filters, [], ordr, 0, N,
                                       idxnms, kb_ids)
        return self._ent_info_from_(es_res, 0)

    def retrieval(self, question: str,
               tenant_ids: str | list[str],
               kb_ids: list[str],
               emb_mdl,
               llm,
               max_token: int = 8196,
               ent_topn: int = 6,
               rel_topn: int = 6,
               comm_topn: int = 1,
               ent_sim_threshold: float = 0.3,
               rel_sim_threshold: float = 0.3,
                  **kwargs
               ):
        logging.info(f"开始进行图谱检索查询")
        qst = question
        filters = self.get_filters({"kb_ids": kb_ids})
        if isinstance(tenant_ids, str):
            tenant_ids = tenant_ids.split(",")
        idxnms = [index_name(tid) for tid in tenant_ids]
        ty_kwds = []
        logging.info("开始调用大模型获取图谱中需要查询的类型和实体关键字")
        try:
            ty_kwds, ents = self.query_rewrite(llm, qst, [index_name(tid) for tid in tenant_ids], kb_ids)
            logging.info(f"Q: {qst}, Types: {ty_kwds}, Entities: {ents}")
        except Exception as e:
            logging.exception(e)
            ents = [qst]
            pass

        logging.info(f"通过大模型获取到需要再图谱中查询的类型和实体关键字")
        ents_from_query = self.get_relevant_ents_by_keywords(ents, filters, idxnms, kb_ids, emb_mdl, ent_sim_threshold)
        ents_from_types = self.get_relevant_ents_by_types(ty_kwds, filters, idxnms, kb_ids, 10000)
        rels_from_txt = self.get_relevant_relations_by_txt(qst, filters, idxnms, kb_ids, emb_mdl, rel_sim_threshold)
        nhop_pathes = defaultdict(dict)
        for _, ent in ents_from_query.items():
            nhops = ent.get("n_hop_ents", [])
            if not isinstance(nhops, list):
                logging.warning(f"Abnormal n_hop_ents: {nhops}")
                continue
            for nbr in nhops:
                path = nbr["path"]
                wts = nbr["weights"]
                for i in range(len(path) - 1):
                    f, t = path[i], path[i + 1]
                    if (f, t) in nhop_pathes:
                        nhop_pathes[(f, t)]["sim"] += ent["sim"] / (2 + i)
                    else:
                        nhop_pathes[(f, t)]["sim"] = ent["sim"] / (2 + i)
                    nhop_pathes[(f, t)]["pagerank"] = wts[i]


        # P(E|Q) => P(E) * P(Q|E) => pagerank * sim
        for ent in ents_from_types.keys():
            if ent not in ents_from_query:
                continue
            ents_from_query[ent]["sim"] *= 2

        for (f, t) in rels_from_txt.keys():
            pair = tuple(sorted([f, t]))
            s = 0
            if pair in nhop_pathes:
                s += nhop_pathes[pair]["sim"]
                del nhop_pathes[pair]
            if f in ents_from_types:
                s += 1
            if t in ents_from_types:
                s += 1
            rels_from_txt[(f, t)]["sim"] *= s + 1

        # This is for the relations from n-hop but not by query search
        for (f, t) in nhop_pathes.keys():
            s = 0
            if f in ents_from_types:
                s += 1
            if t in ents_from_types:
                s += 1
            rels_from_txt[(f, t)] = {
                "sim": nhop_pathes[(f, t)]["sim"] * (s + 1),
                "pagerank": nhop_pathes[(f, t)]["pagerank"]
            }

        ents_from_query = sorted(ents_from_query.items(), key=lambda x: x[1]["sim"] * x[1]["pagerank"], reverse=True)[
                          :ent_topn]
        rels_from_txt = sorted(rels_from_txt.items(), key=lambda x: x[1]["sim"] * x[1]["pagerank"], reverse=True)[
                        :rel_topn]

        ents = []
        relas = []
        for n, ent in ents_from_query:
            ents.append({
                "Entity": n,
                "Score": "%.2f" % (ent["sim"] * ent["pagerank"]),
                "Description": json.loads(ent["description"]).get("description", "") if ent["description"] else ""
            })
            max_token -= num_tokens_from_string(str(ents[-1]))
            if max_token <= 0:
                ents = ents[:-1]
                break

        for (f, t), rel in rels_from_txt:
            if not rel.get("description"):
                for tid in tenant_ids:
                    rela = get_relation(tid, kb_ids, f, t)
                    if rela:
                        break
                else:
                    continue
                rel["description"] = rela["description"]
            desc = rel["description"]
            try:
                desc = json.loads(desc).get("description", "")
            except Exception:
                pass
            relas.append({
                "From Entity": f,
                "To Entity": t,
                "Score": "%.2f" % (rel["sim"] * rel["pagerank"]),
                "Description": desc
            })
            max_token -= num_tokens_from_string(str(relas[-1]))
            if max_token <= 0:
                relas = relas[:-1]
                break

        if ents:
            ents = "\n---- Entities ----\n{}".format(pd.DataFrame(ents).to_csv())
        else:
            ents = ""
        if relas:
            relas = "\n---- Relations ----\n{}".format(pd.DataFrame(relas).to_csv())
        else:
            relas = ""

        return {
                "chunk_id": get_uuid(),
                "content_ltks": "",
                "content_with_weight": ents + relas + self._community_retrival_([n for n, _ in ents_from_query], filters, kb_ids, idxnms,
                                                        comm_topn, max_token),
                "doc_id": "",
                "docnm_kwd": "Related content in Knowledge Graph",
                "kb_id": kb_ids,
                "important_kwd": [],
                "image_id": "",
                "similarity": 1.,
                "vector_similarity": 1.,
                "term_similarity": 0,
                "vector": [],
                "positions": [],
            }


    def structure_retrieval(self, question: str,
                            tenant_ids: str | list[str],
                            kb_ids: list[str],
                            emb_mdl,
                            llm,
                            max_token: int = 8196,
                            ent_topn: int = 10,
                            rel_topn: int = 10,
                            ent_sim_threshold: float = 0.3,
                            rel_sim_threshold: float = 0.3,
                            main_trace=None,
                            **kwargs
                            ):
        def _create_trace_span(main_trace, name, input_data=None, output_data=None):
            """创建trace span的通用函数"""
            if not main_trace:
                return
            try:
                from api.utils.langfuse_utils import LangfuseUtils
                LangfuseUtils.create_span(main_trace, name, input_data, output_data)
            except Exception as e:
                logging.warning(f"Failed to create trace span {name}: {e}")
        
        logging.info(f"开始进行图谱检索查询")
        qst = question
        filters = self.get_filters({"kb_ids": kb_ids})
        if isinstance(tenant_ids, str):
            tenant_ids = tenant_ids.split(",")
        idxnms = [index_name(tid) for tid in tenant_ids]
        ty_kwds = []
        
        logging.info("开始调用大模型获取图谱中需要查询的类型和实体关键字")
        try:
            ty_kwds, ents = self.query_rewrite(llm, qst, [index_name(tid) for tid in tenant_ids], kb_ids)
            logging.info(f"Q: {qst}, Types: {ty_kwds}, Entities: {ents}")
        except Exception as e:
            logging.exception(e)
            ents = [qst]
            pass

        # 跟踪查询重写
        _create_trace_span(
            main_trace, "query_rewrite",
            input_data={
                "original_question": qst,
                "question_length": len(qst),
                "tenant_ids": tenant_ids,
                "kb_ids": kb_ids
            },
            output_data={
                "extracted_types": ty_kwds,
                "extracted_entities": ents,
                "types_count": len(ty_kwds),
                "entities_count": len(ents),
                "rewrite_successful": len(ty_kwds) > 0 or len(ents) > 1
            }
        )

        logging.info(f"通过大模型获取到需要再图谱中查询的类型和实体关键字")
        
        ents_from_query = self.get_relevant_ents_by_keywords(ents, filters, idxnms, kb_ids, emb_mdl, ent_sim_threshold)
        ents_from_types = self.get_relevant_ents_by_types(ty_kwds, filters, idxnms, kb_ids, 10000)

        # 跟踪实体检索
        _create_trace_span(
            main_trace, "entity_retrieval",
            input_data={
                "entities_to_search": ents,
                "types_to_search": ty_kwds,
                "ent_sim_threshold": ent_sim_threshold
            },
            output_data={
                "entities_from_query_count": len(ents_from_query),
                "entities_from_types_count": len(ents_from_types),
                "entities_from_query": list(ents_from_query.keys()),
                "entities_from_types": list(ents_from_types.keys())
            }
        )
        
        rels_from_txt = self.get_relevant_relations_by_txt(qst, filters, idxnms, kb_ids, emb_mdl, rel_sim_threshold)
        nhop_pathes = defaultdict(dict)
        for _, ent in ents_from_query.items():
            nhops = ent.get("n_hop_ents", [])
            if not isinstance(nhops, list):
                logging.warning(f"Abnormal n_hop_ents: {nhops}")
                continue
            for nbr in nhops:
                path = nbr["path"]
                wts = nbr["weights"]
                for i in range(len(path) - 1):
                    f, t = path[i], path[i + 1]
                    if (f, t) in nhop_pathes:
                        nhop_pathes[(f, t)]["sim"] += ent["sim"] / (2 + i)
                    else:
                        nhop_pathes[(f, t)]["sim"] = ent["sim"] / (2 + i)
                    nhop_pathes[(f, t)]["pagerank"] = wts[i]

        # 跟踪关系检索
        _create_trace_span(
            main_trace, "relation_retrieval",
            input_data={
                "question": qst,
                "rel_sim_threshold": rel_sim_threshold,
                "rel_topn": rel_topn
            },
            output_data={
                "relations_from_text_count": len(rels_from_txt),
                "nhop_paths_count": len(nhop_pathes),
                "relations_from_text": list(rels_from_txt.keys()),
                "nhop_paths": list(nhop_pathes.keys())
            }
        )
        
        # P(E|Q) => P(E) * P(Q|E) => pagerank * sim
        for ent in ents_from_types.keys():
            if ent not in ents_from_query:
                continue
            ents_from_query[ent]["sim"] *= 2

        for (f, t) in rels_from_txt.keys():
            pair = tuple(sorted([f, t]))
            s = 0
            if pair in nhop_pathes:
                s += nhop_pathes[pair]["sim"]
                del nhop_pathes[pair]
            if f in ents_from_types:
                s += 1
            if t in ents_from_types:
                s += 1
            rels_from_txt[(f, t)]["sim"] *= s + 1

        # This is for the relations from n-hop but not by query search
        for (f, t) in nhop_pathes.keys():
            s = 0
            if f in ents_from_types:
                s += 1
            if t in ents_from_types:
                s += 1
            rels_from_txt[(f, t)] = {
                "sim": nhop_pathes[(f, t)]["sim"] * (s + 1),
                "pagerank": nhop_pathes[(f, t)]["pagerank"]
            }
        
        # 改进排序算法：使用加权组合而非简单乘积
        def calculate_entity_score(ent_name, ent_info):
            sim = ent_info["sim"]
            pagerank = ent_info["pagerank"]
            return 0.6 * sim + 0.4 * pagerank
        
        # 使用新的排序算法
        ents_from_query = sorted(ents_from_query.items(), 
                                key=lambda x: calculate_entity_score(x[0], x[1]), 
                                reverse=True)[:ent_topn]
        
        # 关系排序也使用加权组合算法
        rels_from_txt = sorted(rels_from_txt.items(), 
                              key=lambda x: 0.6 * x[1]["sim"] + 0.4 * x[1]["pagerank"], 
                              reverse=True)[:rel_topn]

        # 跟踪排序
        _create_trace_span(
            main_trace, "ranking",
            input_data={
                "entities_to_rank": len(ents_from_query),
                "relations_to_rank": len(rels_from_txt),
                "ent_topn": ent_topn,
                "rel_topn": rel_topn
            },
            output_data={
                "final_entities_selected": len(ents_from_query),
                "final_relations_selected": len(rels_from_txt),
                "top_entities": [{"name": n, "score": calculate_entity_score(n, ent)} for n, ent in ents_from_query],
                "top_relations": [{"from": f, "to": t, "score": 0.6 * rel["sim"] + 0.4 * rel["pagerank"]} for (f, t), rel in rels_from_txt]
            }
        )

        ents = []
        relas = []

        for n, ent in ents_from_query:
            dsc_json = json.loads(ent["description"])
            actual_score = 0.6 * ent["sim"] + 0.4 * ent["pagerank"]
            
            ents.append({
                "Entity": n,
                "Score": "%.4f" % actual_score,
                "Description": dsc_json.get("description", "") if ent["description"] else "",
                "Type": "Normal"  # 添加类型标记
            })
            # 如果实体是微课，从description中提取微课难度字段
            if 'micro_course_id' in dsc_json:
                ents[-1]['micro_course_difficulty'] = dsc_json.get('micro_course_difficulty', 0)
            courses_key_type_map = {'micro_course_id': 'micro_course',
                                    'course_id': "course",
                                    'package_id': "course_package"
                                    }
            for k in courses_key_type_map.keys():
                if k in dsc_json:
                    ents[-1][k] = dsc_json.get(k, "")
                    ents[-1]["Type"] = courses_key_type_map[k]
            max_token -= num_tokens_from_string(str(ents[-1]))
            if max_token <= 0:
                ents = ents[:-1]
                break

        for (f, t), rel in rels_from_txt:
            if not rel.get("description"):
                for tid in tenant_ids:
                    rela = get_relation(tid, kb_ids, f, t)
                    if rela:
                        break
                else:
                    continue
                rel["description"] = rela["description"]
            desc = rel["description"]
            try:
                desc = json.loads(desc).get("description", "")
            except Exception:
                pass
            # 关系也使用新的评分算法
            rel_score = 0.6 * rel["sim"] + 0.4 * rel["pagerank"]
            relas.append({
                "From Entity": f,
                "To Entity": t,
                "Score": "%.4f" % rel_score,
                "Description": desc
            })
            max_token -= num_tokens_from_string(str(relas[-1]))
            if max_token <= 0:
                relas = relas[:-1]
                break

        graph = {"nodes": ents, "edges": relas}
        graph_res = {"graph": graph}
        
        return graph_res

    def _community_retrival_(self, entities, condition, kb_ids, idxnms, topn, max_token):
        ## Community retrieval
        fields = ["docnm_kwd", "content_with_weight"]
        odr = OrderByExpr()
        odr.desc("weight_flt")
        fltr = deepcopy(condition)
        fltr["knowledge_graph_kwd"] = "community_report"
        fltr["entities_kwd"] = entities
        comm_res = self.dataStore.search(fields, [], fltr, [],
                                         OrderByExpr(), 0, topn, idxnms, kb_ids)
        comm_res_fields = self.dataStore.getFields(comm_res, fields)
        txts = []
        for ii, (_, row) in enumerate(comm_res_fields.items()):
            obj = json.loads(row["content_with_weight"])
            txts.append("# {}. {}\n## Content\n{}\n## Evidences\n{}\n".format(
                ii + 1, row["docnm_kwd"], obj["report"], obj["evidences"]))
            max_token -= num_tokens_from_string(str(txts[-1]))

        if not txts:
            return ""
        return "\n---- Community Report ----\n" + "\n".join(txts)


if __name__ == "__main__":
    from api import settings
    import argparse
    from api.db import LLMType
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from api.db.services.user_service import TenantService
    from rag.nlp import search

    settings.init_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--tenant_id', default=False, help="Tenant ID", action='store', required=True)
    parser.add_argument('-d', '--kb_id', default=False, help="Knowledge base ID", action='store', required=True)
    parser.add_argument('-q', '--question', default=False, help="Question", action='store', required=True)
    args = parser.parse_args()

    kb_id = args.kb_id
    _, tenant = TenantService.get_by_id(args.tenant_id)
    llm_bdl = LLMBundle(args.tenant_id, LLMType.CHAT, tenant.llm_id)
    _, kb = KnowledgebaseService.get_by_id(kb_id)
    embed_bdl = LLMBundle(args.tenant_id, LLMType.EMBEDDING, kb.embd_id)

    kg = KGSearch(settings.docStoreConn)
    print(kg.retrieval({"question": args.question, "kb_ids": [kb_id]},
                    search.index_name(kb.tenant_id), [kb_id], embed_bdl, llm_bdl))
