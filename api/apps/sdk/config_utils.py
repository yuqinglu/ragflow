import json
import logging
import os
from typing import List, Dict, Any
from api.utils import read_config

logger = logging.getLogger(__name__)

def get_noauth_config() -> Dict[str, Any]:
    """
    从service_conf.yaml读取免认证配置
    
    Returns:
        Dict[str, Any]: 免认证配置字典
    """
    try:
        # 读取全局配置
        configs = read_config()
        
        # 获取免认证配置
        noauth_config = configs.get('noauth_api', {})
        
        if not noauth_config:
            logger.warning("未找到noauth_api配置，使用默认配置")
            return _get_default_config()
        
        # 处理kb_ids，如果是字符串则解析为列表
        kb_ids = noauth_config.get('kb_ids', [])
        logger.info(f"原始kb_ids值: {kb_ids} (类型: {type(kb_ids)})")
        
        if isinstance(kb_ids, str):
            # 清理字符串，去除可能的引号和空白字符
            kb_ids_clean = kb_ids.strip().strip('"').strip("'")
            
            # 如果是YAML格式的键值对，提取值部分
            if ':' in kb_ids_clean:
                parts = kb_ids_clean.split(':', 1)
                if len(parts) == 2:
                    kb_ids_clean = parts[1].strip()
                    logger.info(f"提取的值部分: {kb_ids_clean}")
            
            # 尝试修复常见的JSON格式问题
            original_kb_ids_clean = kb_ids_clean
            
            # 问题1: 数组元素缺少双引号，如 [item1, item2] -> ["item1", "item2"]
            if kb_ids_clean.startswith('[') and kb_ids_clean.endswith(']'):
                # 检查是否所有元素都有双引号
                if '"' not in kb_ids_clean:
                    logger.info("检测到数组元素缺少双引号，尝试修复...")
                    # 提取数组内容
                    content = kb_ids_clean[1:-1]  # 去掉 [ 和 ]
                    if content.strip():
                        # 分割元素并添加双引号
                        items = [item.strip() for item in content.split(',') if item.strip()]
                        kb_ids_clean = '[' + ','.join(f'"{item}"' for item in items) + ']'
                        logger.info(f"修复后的格式: {kb_ids_clean}")
            
            try:
                kb_ids = json.loads(kb_ids_clean)
                logger.info(f"JSON解析成功: {kb_ids}")
            except json.JSONDecodeError as e:
                logger.error(f"解析kb_ids失败: {e}")
                logger.error(f"原始值: '{original_kb_ids_clean}'")
                logger.error(f"修复后值: '{kb_ids_clean}'")
                logger.error(f"值长度: {len(kb_ids_clean)}")
                logger.error(f"值字节: {repr(kb_ids_clean)}")
                kb_ids = []
        
        # 构建配置字典
        config = {
            'tenant_id': noauth_config.get('tenant_id', ''),
            'embedding_model': noauth_config.get('embedding_model', ''),
            'kb_ids': kb_ids if isinstance(kb_ids, list) else [],
            'llm_id': noauth_config.get('llm_id', ''),
            'operational_report_kb_id': noauth_config.get('operational_report_kb_id', '')
        }
        
        # 验证必要配置
        if not config['tenant_id']:
            logger.error("未配置tenant_id")
            raise ValueError("tenant_id配置缺失")
        
        if not config['embedding_model']:
            logger.error("未配置embedding_model")
            raise ValueError("embedding_model配置缺失")
        
        if not config['kb_ids']:
            logger.error("未配置kb_ids或配置格式错误")
            raise ValueError("kb_ids配置缺失或格式错误")
        
        if not config['llm_id']:
            logger.error("未配置llm_id")
            raise ValueError("llm_id配置缺失")
        
        if not config['operational_report_kb_id']:
            logger.error("未配置operational_report_kb_id")
            raise ValueError("operational_report_kb_id配置缺失")
        
        logger.info(f"成功加载免认证配置: tenant_id={config['tenant_id']}, kb_ids={config['kb_ids']}")
        return config
        
    except Exception as e:
        logger.error(f"加载免认证配置失败: {str(e)}")
        # 返回默认配置
        return _get_default_config()

def _get_default_config() -> Dict[str, Any]:
    """
    获取默认配置（兼容旧的JSON文件方式）
    
    Returns:
        Dict[str, Any]: 默认配置字典
    """
    # 尝试从旧的JSON文件读取
    config_path = os.path.join(os.path.dirname(__file__), 'noauth_config.json')
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info("从旧版JSON文件加载配置")
                return config
    except Exception as e:
        logger.warning(f"读取旧版JSON配置文件失败: {str(e)}")
    
    # 返回硬编码的默认值
    logger.warning("使用硬编码默认配置")
    return {
        'tenant_id': 'a128a194190911f089ad85162265e498',
        'embedding_model': 'BAAI/bge-large-zh-v1.5@BAAI',
        'kb_ids': ['d626afca24d111f0bce1a0369f72b8b4'],
        'llm_id': 'qwen-plus-latest@Tongyi-Qianwen',
        'operational_report_kb_id': '7d0234325dfc11f0b60da0369f72b8b4'
    }

def validate_config(config: Dict[str, Any]) -> bool:
    """
    验证配置的完整性
    
    Args:
        config: 配置字典
        
    Returns:
        bool: 配置是否有效
    """
    required_fields = ['tenant_id', 'embedding_model', 'kb_ids', 'llm_id', 'operational_report_kb_id']
    
    for field in required_fields:
        if field not in config or not config[field]:
            logger.error(f"配置缺失: {field}")
            return False
    
    if not isinstance(config['kb_ids'], list) or len(config['kb_ids']) == 0:
        logger.error("kb_ids必须是非空列表")
        return False
    
    return True 