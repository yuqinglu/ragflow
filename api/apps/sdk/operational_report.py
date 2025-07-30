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
from functools import wraps

from api.db.services.operational_report_service import OperationalReportService
from api.apps.sdk.config_utils import get_noauth_config, validate_config
from api.db.services.llm_service import LLMBundle, LLMType
from api import settings

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


def get_kb_id():
    """获取知识库ID，如果未配置则抛出异常"""
    kb_id = CONFIG.get('operational_report_kb_id')
    if not kb_id:
        raise ValueError("Operational report knowledge base not configured!")
    return kb_id


def validate_required_fields(data, required_fields):
    """验证必需字段"""
    missing_fields = []
    for field in required_fields:
        if not data.get(field):
            missing_fields.append(field)
    
    if missing_fields:
        return False, f"Missing required fields: {', '.join(missing_fields)}"
    return True, None


def convert_user_id_to_string(user_id):
    """将用户ID转换为字符串类型，兼容bigint和string类型"""
    if user_id is None:
        return None
    return str(user_id)


def convert_user_id_to_int(user_id):
    """将用户ID转换为整数类型，用于输出时兼容bigint类型"""
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (ValueError, TypeError):
        # 如果无法转换为整数，返回原始值
        return user_id


def convert_created_by_to_user_id(report_dict):
    """将报告字典中的created_by字段转换为user_id字段，并确保类型为整数"""
    if "created_by" in report_dict:
        user_id = convert_user_id_to_int(report_dict["created_by"])
        report_dict["user_id"] = user_id
        del report_dict["created_by"]
    return report_dict


def validate_report_id(report_id):
    """验证report_id是否为有效的整数"""
    if not isinstance(report_id, int):
        return False, "Report ID must be an integer"
    if report_id <= 0:
        return False, "Report ID must be a positive integer"
    return True, None


def api_error_handler(f):
    """API错误处理装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            logger.error(f"API error in {f.__name__}: {str(e)}")
            return jsonify({"error": "Internal server error"}), 500
    return decorated_function


@manager.route("/operational-reports", methods=["POST"])  # noqa: F821
@api_error_handler
def upsert_report():
    """
    Create or update operational report
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
            report_id:
              type: integer
              description: "Report ID (must be a positive integer)"
            report_data:
              type: object
            user_id:
              type: string
            report_status:
              type: string
          required:
            - report_id
            - report_data
            - user_id
            - report_status
    responses:
      200:
        description: Success
    """
    req = request.json
    
    # Validate required fields
    is_valid, error_msg = validate_required_fields(req, ["report_id", "report_data", "user_id", "report_status"])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    # Validate report_id type
    is_valid, error_msg = validate_report_id(req["report_id"])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    report_id = req["report_id"]
    
    # Validate report_data type
    if not isinstance(req["report_data"], dict):
        return jsonify({"error": "Report data must be a JSON object!"}), 400
    
    # 转换用户ID为字符串类型，兼容bigint输入
    created_by = convert_user_id_to_string(req["user_id"])
    
    # Create or update report
    report, action = OperationalReportService.upsert_report(
        report_id=report_id,
        kb_id=get_kb_id(),
        report_data=req["report_data"],
        created_by=created_by,
        report_status=req["report_status"]
    )
    
    return jsonify({
        "report_id": report.id,
        "created_at": report.create_date,
        "action": action
    })


@manager.route("/operational-reports/batch-status", methods=["POST"])  # noqa: F821
@api_error_handler
def batch_update_status():
    """
    Batch update operational report statuses
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
            status_updates:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                    description: "Report ID (must be a positive integer)"
                  report_status:
                    type: string
                required:
                  - id
                  - report_status
          required:
            - status_updates
    responses:
      200:
        description: Success
    """
    req = request.json
    
    # Validate required fields
    if not isinstance(req.get("status_updates"), list):
        return jsonify({"error": "Status updates must be a list!"}), 400
    
    if not req.get("status_updates"):
        return jsonify({"error": "Status updates list cannot be empty!"}), 400
    
    # Validate each update
    for update in req["status_updates"]:
        if not isinstance(update, dict) or "id" not in update or "report_status" not in update:
            return jsonify({"error": "Each status update must have 'id' and 'report_status' fields!"}), 400
        
        # Validate report_id type for each update
        is_valid, error_msg = validate_report_id(update["id"])
        if not is_valid:
            return jsonify({"error": f"Invalid report ID in update: {error_msg}"}), 400
    
    # Perform batch update
    result = OperationalReportService.batch_update_status(req["status_updates"])
    
    return jsonify(result)


@manager.route("/operational-reports/delete", methods=["POST"])  # noqa: F821
@api_error_handler
def delete_report():
    """
    Delete operational report
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
            report_id:
              type: integer
              description: "Report ID (must be a positive integer)"
            user_id:
              type: string
          required:
            - report_id
            - user_id
    responses:
      200:
        description: Success
    """
    req = request.json
    
    # Validate required fields
    is_valid, error_msg = validate_required_fields(req, ["report_id", "user_id"])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    # Validate report_id type
    is_valid, error_msg = validate_report_id(req["report_id"])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    report_id = req["report_id"]
    
    # 转换用户ID为字符串类型，兼容bigint输入
    user_id = convert_user_id_to_string(req["user_id"])
    
    # Delete report
    success = OperationalReportService.delete_report(
        report_id=report_id,
        user_id=user_id
    )
    
    if success:
        return jsonify({"message": "Report deleted successfully!"})
    else:
        return jsonify({"error": "Failed to delete report or access denied!"}), 400


@manager.route("/operational-reports/<report_id>", methods=["GET"])  # noqa: F821
@api_error_handler
def get_report(report_id):
    """
    Get operational report
    ---
    tags:
      - Operational Reports
    parameters:
      - in: path
        name: report_id
        type: integer
        required: true
        description: "Report ID (must be a positive integer)"
      - in: query
        name: user_id
        type: string
        required: false
    responses:
      200:
        description: Success
    """
    user_id = request.args.get("user_id")
    
    # Convert report_id from string to int for validation
    try:
        report_id_int = int(report_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Report ID must be a valid integer"}), 400
    
    # Validate report_id type
    is_valid, error_msg = validate_report_id(report_id_int)
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    # Get report
    report = OperationalReportService.get_by_id(
        report_id=report_id_int,
        user_id=convert_user_id_to_string(user_id)
    )
    
    if report:
        # 转换输出数据，将created_by转换为user_id并确保类型为整数
        report_dict = report.to_dict()
        report_dict = convert_created_by_to_user_id(report_dict)
        return jsonify(report_dict)
    else:
        return jsonify({"error": "Report not found or access denied!"}), 400


@manager.route("/list-operational-reports", methods=["GET"])  # noqa: F821
@api_error_handler
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
    responses:
      200:
        description: Success
    """
    user_id = request.args.get("user_id")
    
    # Validate required fields
    if not user_id:
        return jsonify({"error": "User ID is required!"}), 400
    
    # Parse query parameters
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    orderby = request.args.get("orderby", "create_time")
    desc = request.args.get("desc", "true").lower() == "true"
    
    # Get reports
    reports, total = OperationalReportService.get_by_kb_id(
        kb_id=get_kb_id(),
        user_id=convert_user_id_to_string(user_id),
        page_number=page,
        items_per_page=page_size,
        orderby=orderby,
        desc=desc
    )
    
    # 转换输出数据，将每个报告的created_by转换为user_id并确保类型为整数
    if reports:
        for report in reports:
            report = convert_created_by_to_user_id(report)
    
    return jsonify({
        "reports": reports,
        "total": total,
        "page": page,
        "page_size": page_size
    })


@manager.route("/operational-reports/search", methods=["POST"])  # noqa: F821
@api_error_handler
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
              default: 0.4
            vector_similarity_weight:
              type: number
              default: 0.7
          required:
            - query
            - user_id
    responses:
      200:
        description: Success
    """
    req = request.json
    
    # Validate required fields
    is_valid, error_msg = validate_required_fields(req, ["query", "user_id"])
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    # Get search parameters with defaults
    page = req.get("page", 1)
    page_size = req.get("page_size", 20)
    similarity_threshold = req.get("similarity_threshold", 0.4)
    vector_similarity_weight = req.get("vector_similarity_weight", 0.7)

    # Perform vector search
    results = OperationalReportService.vector_search(
        query=req["query"],
        kb_id=get_kb_id(),
        user_id=convert_user_id_to_string(req["user_id"]),
        page_number=page,
        items_per_page=page_size,
        similarity_threshold=similarity_threshold,
        vector_similarity_weight=vector_similarity_weight
    )

    # 转换输出数据，将每个报告的created_by转换为user_id并确保类型为整数
    if results.get("reports"):
        for report_item in results["reports"]:
            if "report" in report_item:
                report_item["report"] = convert_created_by_to_user_id(report_item["report"])
    
    return jsonify({
        "reports": results["reports"],
        "total": results["total"],
        "page": page,
        "page_size": page_size,
        "query": req["query"],
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight
    })


@manager.route("/operational-reports/<report_id>/similar", methods=["GET"])  # noqa: F821
@api_error_handler
def find_similar_reports(report_id):
    """
    Find similar operational reports
    ---
    tags:
      - Operational Reports
    parameters:
      - in: path
        name: report_id
        type: integer
        required: true
        description: "Report ID (must be a positive integer)"
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
    responses:
      200:
        description: Success
    """
    user_id = request.args.get("user_id")
    
    # Validate required fields
    if not user_id:
        return jsonify({"error": "User ID is required!"}), 400
    
    # Get query parameters
    limit = int(request.args.get("limit", 10))
    similarity_threshold = float(request.args.get("similarity_threshold", 0.3))
    
    # Convert report_id from string to int for validation
    try:
        report_id_int = int(report_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Report ID must be a valid integer"}), 400
    
    # Validate report_id type
    is_valid, error_msg = validate_report_id(report_id_int)
    if not is_valid:
        return jsonify({"error": error_msg}), 400
    
    # Get the reference report
    report = OperationalReportService.get_by_id(
        report_id=report_id_int,
        user_id=convert_user_id_to_string(user_id)
    )
    
    if not report:
        return jsonify({"error": "Report not found or access denied!"}), 400
    
    # Build query JSON for vector search
    query = json.dumps({"report_data": report.report_data}, ensure_ascii=False, indent=2)
    
    # Perform vector search to find similar reports
    results = OperationalReportService.vector_search(
        query=query,
        kb_id=get_kb_id(),
        user_id=convert_user_id_to_string(user_id),
        page_number=1,
        items_per_page=limit + 1,  # +1 to exclude the original report
        similarity_threshold=similarity_threshold,
        vector_similarity_weight=0.7  # Higher weight for vector similarity
    )
    
    # Filter out the original report
    similar_reports = [
        r for r in results["reports"] 
        if r["report"]["id"] != report_id_int
    ][:limit]
    
    # 转换输出数据，将每个报告的created_by转换为user_id并确保类型为整数
    for similar_report in similar_reports:
        if "report" in similar_report:
            similar_report["report"] = convert_created_by_to_user_id(similar_report["report"])
    
    # 转换参考报告的created_by
    reference_report_dict = report.to_dict()
    reference_report_dict = convert_created_by_to_user_id(reference_report_dict)
    
    return jsonify({
        "similar_reports": similar_reports,
        "total": len(similar_reports),
        "reference_report": reference_report_dict
    })


