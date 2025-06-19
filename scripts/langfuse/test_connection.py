#!/usr/bin/env python3
"""
Langfuse 连接测试脚本
用于诊断和解决 Langfuse 集成问题
"""

import os
import sys
import logging
from typing import Dict, Any

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_langfuse_connection(public_key: str, secret_key: str, host: str) -> Dict[str, Any]:
    """
    测试Langfuse连接
    
    Args:
        public_key: Langfuse公钥
        secret_key: Langfuse私钥  
        host: Langfuse主机地址
        
    Returns:
        测试结果字典
    """
    try:
        # 导入langfuse
        try:
            from langfuse import Langfuse
            logger.info("✓ Langfuse库导入成功")
        except ImportError as e:
            return {
                "success": False,
                "error": "Langfuse库未安装",
                "details": f"请安装langfuse: pip install langfuse\n错误: {e}"
            }
        
        # 验证参数
        if not all([public_key, secret_key, host]):
            return {
                "success": False,
                "error": "缺少必要参数",
                "details": "请提供public_key, secret_key和host"
            }
        
        logger.info(f"正在测试连接到: {host}")
        logger.info(f"使用公钥: {public_key[:10]}...")
        
        # 创建Langfuse客户端
        try:
            langfuse = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host
            )
            logger.info("✓ Langfuse客户端创建成功")
        except Exception as e:
            return {
                "success": False,
                "error": "无法创建Langfuse客户端",
                "details": f"错误: {e}"
            }
        
        # 测试认证
        try:
            auth_result = langfuse.auth_check()
            if auth_result:
                logger.info("✓ Langfuse认证成功")
            else:
                return {
                    "success": False,
                    "error": "Langfuse认证失败",
                    "details": "请检查您的公钥、私钥和主机配置是否正确"
                }
        except Exception as e:
            return {
                "success": False,
                "error": "认证检查时发生错误",
                "details": f"错误: {e}"
            }
        
        # 测试创建trace
        try:
            test_trace = langfuse.trace(name="ragflow-connection-test")
            logger.info("✓ 创建trace成功")
            
            # 测试创建generation
            test_generation = test_trace.generation(
                name="test-generation",
                model="test-model",
                input={"message": "connection test"}
            )
            logger.info("✓ 创建generation成功")
            
            # 结束generation
            test_generation.end(output={"result": "connection successful"})
            logger.info("✓ 结束generation成功")
            
            # 刷新数据（确保数据发送到Langfuse）
            langfuse.flush()
            logger.info("✓ 数据刷新成功")
            
        except Exception as e:
            return {
                "success": False,
                "error": "创建trace/generation时发生错误",
                "details": f"错误: {e}"
            }
        
        return {
            "success": True,
            "message": "Langfuse连接测试成功！",
            "details": f"成功连接到 {host}，trace和generation创建正常"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": "未预期的错误",
            "details": f"错误: {e}"
        }

def main():
    """主函数"""
    print("=== RAGFlow Langfuse 连接测试 ===\n")
    
    # 从环境变量或命令行参数获取配置
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-f6561f4d-e2b6-447c-99d2-cb6532418cb3")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-1bf05ce9-df80-4201-8e97-d160347adc13")
    host = os.getenv("LANGFUSE_HOST", "http://10.1.115.38:3000")
    
    # 如果没有环境变量，提示用户输入
    if not public_key:
        public_key = input("请输入Langfuse公钥 (LANGFUSE_PUBLIC_KEY): ").strip()
    if not secret_key:
        secret_key = input("请输入Langfuse私钥 (LANGFUSE_SECRET_KEY): ").strip()
    if not host:
        host = input("请输入Langfuse主机地址 (默认: https://cloud.langfuse.com): ").strip()
        if not host:
            host = "https://cloud.langfuse.com"
    
    # 执行测试
    result = test_langfuse_connection(public_key, secret_key, host)
    
    # 显示结果
    print("\n=== 测试结果 ===")
    if result["success"]:
        print(f"✅ {result['message']}")
        print(f"详情: {result['details']}")
        print("\n🎉 Langfuse配置正确！您现在应该能在Langfuse面板中看到测试trace了。")
    else:
        print(f"❌ {result['error']}")
        print(f"详情: {result['details']}")
        print("\n💡 解决建议:")
        print("1. 检查您的Langfuse配置是否正确")
        print("2. 确认网络连接正常")
        print("3. 验证API密钥是否有效")
        print("4. 查看系统日志获取更多信息")

if __name__ == "__main__":
    main() 