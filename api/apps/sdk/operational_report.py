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
import os
from flask import request, jsonify

from api.db.services.operational_report_service import OperationalReportService
from api.apps.sdk.config_utils import get_noauth_config, validate_config

# 全局配置初始化(模块加载时执行一次)
try:
    CONFIG = get_noauth_config()
    if not validate_config(CONFIG):
        raise ValueError("免认证配置验证失败")
    logger = logging.getLogger(__name__)
    logger.info('成功加载运维报告免认证配置')
except Exception as e:
    logging.error(f"运维报告配置加载失败: {str(e)}")
    raise RuntimeError("运维报告系统配置初始化失败")


@manager.route("/operational-reports", methods=["POST"])  # noqa: F821
def create_report():
    """
    Create operational report
    ---
    tags:
      - Operational Reports
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            title:
              type: string
            report_data:
              type: object
            user_id:
              type: string
            group_id:
              type: string
          required:
            - title
            - report_data
            - user_id
    responses:
      200:
        description: Success
    """
    req = request.json
    
    try:
        title = req.get("title")
        report_data = req.get("report_data")
        user_id = req.get("user_id")
        group_id = req.get("group_id")
        
        # Validate required fields
        if not title:
            return jsonify({"error": "Title is required!"})
        if not report_data:
            return jsonify({"error": "Report data is required!"})
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        if not isinstance(report_data, dict):
            return jsonify({"error": "Report data must be a JSON object!"})
        
        # Get kb_id from config
        kb_id = CONFIG.get('operational_report_kb_id')
        if not kb_id:
            return jsonify({"error": "Operational report knowledge base not configured!"})
        
        # Create report
        report = OperationalReportService.create_report(
            kb_id=kb_id,
            title=title,
            report_data=report_data,
            created_by=user_id,
            group_id=group_id
        )
        
        return jsonify({
            "report_id": report.id,
            "title": report.title,
            "created_at": report.create_date
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/operational-reports/<report_id>", methods=["PUT"])  # noqa: F821
def update_report(report_id):
    """
    Update operational report
    ---
    tags:
      - Operational Reports
    parameters:
      - in: path
        name: report_id
        type: string
        required: true
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            title:
              type: string
            report_data:
              type: object
            user_id:
              type: string
          required:
            - user_id
    responses:
      200:
        description: Success
    """
    req = request.json
    
    try:
        user_id = req.get("user_id")
        title = req.get("title")
        report_data = req.get("report_data")
        
        # Validate required fields
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        if report_data is not None and not isinstance(report_data, dict):
            return jsonify({"error": "Report data must be a JSON object!"})
        
        # Update report
        success = OperationalReportService.update_report(
            report_id=report_id,
            title=title,
            report_data=report_data,
            user_id=user_id
        )
        
        if success:
            return jsonify({"message": "Report updated successfully!"})
        else:
            return jsonify({"error": "Failed to update report or access denied!"})
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/operational-reports/<report_id>", methods=["DELETE"])  # noqa: F821
def delete_report(report_id):
    """
    Delete operational report
    ---
    tags:
      - Operational Reports
    parameters:
      - in: path
        name: report_id
        type: string
        required: true
      - in: query
        name: user_id
        type: string
        required: true
    responses:
      200:
        description: Success
    """
    try:
        user_id = request.args.get("user_id")
        
        # Validate required fields
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        
        # Delete report
        success = OperationalReportService.delete_report(
            report_id=report_id,
            user_id=user_id
        )
        
        if success:
            return jsonify({"message": "Report deleted successfully!"})
        else:
            return jsonify({"error": "Failed to delete report or access denied!"})
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/operational-reports/<report_id>", methods=["GET"])  # noqa: F821
def get_report(report_id):
    """
    Get operational report
    ---
    tags:
      - Operational Reports
    parameters:
      - in: path
        name: report_id
        type: string
        required: true
      - in: query
        name: user_id
        type: string
        required: false
      - in: query
        name: group_id
        type: string
        required: false
    responses:
      200:
        description: Success
    """
    try:
        user_id = request.args.get("user_id")
        group_id = request.args.get("group_id")
        
        # Get report
        report = OperationalReportService.get_by_id(
            report_id=report_id,
            user_id=user_id,
            group_id=group_id
        )
        
        if report:
            return jsonify(report.to_dict())
        else:
            return jsonify({"error": "Report not found or access denied!"})
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/list-operational-reports", methods=["GET"])  # noqa: F821
def list_reports():
    """
    List operational reports
    ---
    tags:
      - Operational Reports
    parameters:
      - in: query
        name: user_id
        type: string
        required: true
      - in: query
        name: page
        type: integer
        default: 1
      - in: query
        name: page_size
        type: integer
        default: 20
      - in: query
        name: orderby
        type: string
        default: "create_time"
      - in: query
        name: desc
        type: boolean
        default: true
      - in: query
        name: keywords
        type: string
      - in: query
        name: group_id
        type: string
    responses:
      200:
        description: Success
    """
    try:
        user_id = request.args.get("user_id")
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))
        orderby = request.args.get("orderby", "create_time")
        desc = request.args.get("desc", "true").lower() == "true"
        keywords = request.args.get("keywords", "")
        group_id = request.args.get("group_id")
        
        # Validate required fields
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        
        # Get kb_id from config
        kb_id = CONFIG.get('operational_report_kb_id')
        if not kb_id:
            return jsonify({"error": "Operational report knowledge base not configured!"})
        
        # Get reports
        reports, total = OperationalReportService.get_by_kb_id(
            kb_id=kb_id,
            user_id=user_id,
            group_id=group_id,
            page_number=page,
            items_per_page=page_size,
            orderby=orderby,
            desc=desc,
            keywords=keywords
        )
        
        return jsonify({
            "reports": reports,
            "total": total,
            "page": page,
            "page_size": page_size
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/operational-reports/search", methods=["POST"])  # noqa: F821
def vector_search_reports():
    """
    Vector search operational reports
    ---
    tags:
      - Operational Reports
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            query:
              type: string
            user_id:
              type: string
            page:
              type: integer
              default: 1
            page_size:
              type: integer
              default: 20
            similarity_threshold:
              type: number
              default: 0.2
            vector_similarity_weight:
              type: number
              default: 0.3
            group_id:
              type: string
          required:
            - query
            - user_id
    responses:
      200:
        description: Success
    """
    req = request.json
    
    try:
        query = req.get("query")
        user_id = req.get("user_id")
        page = req.get("page", 1)
        page_size = req.get("page_size", 20)
        similarity_threshold = req.get("similarity_threshold", 0.2)
        vector_similarity_weight = req.get("vector_similarity_weight", 0.3)
        group_id = req.get("group_id")
        
        # Validate required fields
        if not query:
            return jsonify({"error": "Query is required!"})
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        
        # Get kb_id from config
        kb_id = CONFIG.get('operational_report_kb_id')
        if not kb_id:
            return jsonify({"error": "Operational report knowledge base not configured!"})
        
        # Perform vector search
        results = OperationalReportService.vector_search(
            query=query,
            kb_id=kb_id,
            user_id=user_id,
            group_id=group_id,
            page_number=page,
            items_per_page=page_size,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=vector_similarity_weight
        )
        
        return jsonify({
            "reports": results["reports"],
            "total": results["total"],
            "page": page,
            "page_size": page_size,
            "query": query,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/operational-reports/<report_id>/similar", methods=["GET"])  # noqa: F821
def find_similar_reports(report_id):
    """
    Find similar operational reports
    ---
    tags:
      - Operational Reports
    parameters:
      - in: path
        name: report_id
        type: string
        required: true
      - in: query
        name: user_id
        type: string
        required: true
      - in: query
        name: limit
        type: integer
        default: 10
      - in: query
        name: similarity_threshold
        type: number
        default: 0.3
      - in: query
        name: group_id
        type: string
    responses:
      200:
        description: Success
    """
    try:
        user_id = request.args.get("user_id")
        limit = int(request.args.get("limit", 10))
        similarity_threshold = float(request.args.get("similarity_threshold", 0.3))
        group_id = request.args.get("group_id")
        
        # Validate required fields
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        
        # Get kb_id from config
        kb_id = CONFIG.get('operational_report_kb_id')
        if not kb_id:
            return jsonify({"error": "Operational report knowledge base not configured!"})
        
        # Get the reference report
        report = OperationalReportService.get_by_id(
            report_id=report_id,
            user_id=user_id,
            group_id=group_id
        )
        
        if not report:
            return jsonify({"error": "Report not found or access denied!"})
        
        # 使用与create_report时相同的JSON序列化方式创建查询
        # 构建完整的报告JSON，与向量存储时的格式保持一致
        complete_report_json = {
            "title": report.title,
            "report_data": report.report_data
        }
        
        # 将完整报告转换为JSON字符串，与向量存储时的content_with_weight格式一致
        query = json.dumps(complete_report_json, ensure_ascii=False, indent=2)
        
        # Perform vector search to find similar reports
        results = OperationalReportService.vector_search(
            query=query,
            kb_id=kb_id,
            user_id=user_id,
            group_id=group_id,
            page_number=1,
            items_per_page=limit + 1,  # +1 to exclude the original report
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=0.7  # Higher weight for vector similarity
        )
        
        # Filter out the original report
        similar_reports = [
            r for r in results["reports"] 
            if r["report"]["id"] != report_id
        ][:limit]
        
        return jsonify({
            "similar_reports": similar_reports,
            "total": len(similar_reports),
            "reference_report": report.to_dict()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})


@manager.route("/operational-reports/batch", methods=["POST"])  # noqa: F821
def batch_import_reports():
    """
    Batch import operational reports
    ---
    tags:
      - Operational Reports
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            user_id:
              type: string
            reports:
              type: array
              items:
                type: object
                properties:
                  title:
                    type: string
                  report_data:
                    type: object
                required:
                  - title
                  - report_data
            group_id:
              type: string
          required:
            - user_id
            - reports
    responses:
      200:
        description: Success
    """
    req = request.json
    
    try:
        reports = req.get("reports", [])
        user_id = req.get("user_id")
        group_id = req.get("group_id")
        
        # Validate required fields
        if not user_id:
            return jsonify({"error": "User ID is required!"})
        if not isinstance(reports, list):
            return jsonify({"error": "Reports must be a list!"})
        
        # Get kb_id from config
        kb_id = CONFIG.get('operational_report_kb_id')
        if not kb_id:
            return jsonify({"error": "Operational report knowledge base not configured!"})
        
        created_reports = []
        failed_reports = []
        
        for i, report_data in enumerate(reports):
            try:
                if not isinstance(report_data, dict) or "title" not in report_data or "report_data" not in report_data:
                    failed_reports.append({"index": i, "error": "Invalid report format"})
                    continue
                
                # Create report
                report = OperationalReportService.create_report(
                    kb_id=kb_id,
                    title=report_data["title"],
                    report_data=report_data["report_data"],
                    created_by=user_id,
                    group_id=group_id
                )
                
                created_reports.append({
                    "index": i,
                    "report_id": report.id,
                    "title": report.title
                })
                
            except Exception as e:
                failed_reports.append({"index": i, "error": str(e)})
        
        return jsonify({
            "created_reports": created_reports,
            "failed_reports": failed_reports,
            "total_created": len(created_reports),
            "total_failed": len(failed_reports)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})
