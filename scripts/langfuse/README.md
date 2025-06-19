# Langfuse 工具集

本目录包含与 Langfuse 集成相关的实用工具和脚本。

## 目录结构

```
scripts/langfuse/
├── README.md           # 本文件
└── test_connection.py  # Langfuse 连接测试脚本
```

## 工具说明

### test_connection.py

Langfuse 连接测试脚本，用于诊断和验证 Langfuse 配置。

**功能特性：**
- ✅ 验证 Langfuse 库安装
- ✅ 测试网络连接
- ✅ 验证 API 密钥认证
- ✅ 测试 trace 和 generation 创建
- ✅ 提供详细的错误诊断信息

**使用方法：**

1. **直接运行（交互式）：**
   ```bash
   python scripts/langfuse/test_connection.py
   ```

2. **使用环境变量：**
   ```bash
   export LANGFUSE_PUBLIC_KEY="pk_..."
   export LANGFUSE_SECRET_KEY="sk_..."
   export LANGFUSE_HOST="http://localhost:3000"  # 自部署时使用
   python scripts/langfuse/test_connection.py
   ```

3. **从项目根目录运行：**
   ```bash
   cd /path/to/ragflow
   python scripts/langfuse/test_connection.py
   ```

**输出示例：**

成功情况：
```
=== RAGFlow Langfuse 连接测试 ===

2024-01-15 10:30:00,123 - INFO - ✓ Langfuse库导入成功
2024-01-15 10:30:00,234 - INFO - 正在测试连接到: https://cloud.langfuse.com
2024-01-15 10:30:00,345 - INFO - ✓ Langfuse客户端创建成功
2024-01-15 10:30:01,456 - INFO - ✓ Langfuse认证成功
2024-01-15 10:30:01,567 - INFO - ✓ 创建trace成功
2024-01-15 10:30:01,678 - INFO - ✓ 创建generation成功
2024-01-15 10:30:01,789 - INFO - ✓ 结束generation成功
2024-01-15 10:30:01,890 - INFO - ✓ 数据刷新成功

=== 测试结果 ===
✅ Langfuse连接测试成功！
详情: 成功连接到 https://cloud.langfuse.com，trace和generation创建正常

🎉 Langfuse配置正确！您现在应该能在Langfuse面板中看到测试trace了。
```

失败情况：
```
=== 测试结果 ===
❌ 认证检查时发生错误
详情: 错误: HTTP 401: Unauthorized

💡 解决建议:
1. 检查您的Langfuse配置是否正确
2. 确认网络连接正常
3. 验证API密钥是否有效
4. 查看系统日志获取更多信息
```

## 故障排除

如果遇到问题，请参考 [Langfuse 故障排除指南](../../docs/langfuse-troubleshooting.md)

## 贡献

如果您需要添加新的 Langfuse 相关工具，请：

1. 在本目录下创建新的脚本文件
2. 遵循现有代码的风格和结构
3. 添加适当的文档和错误处理
4. 更新本 README 文件 