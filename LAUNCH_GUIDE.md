# RAGFlow 服务启动指南

## 源代码启动
# 由于pyicu安装太麻烦，目前pptx解析存在问题，需要转成pdf
```bash
JEMALLOC_PATH=~/jemalloc/lib/libjemalloc.so
export PYTHONPATH=$(pwd)

#启动task_executor
LANG=zh_CN.UTF-8 LD_PRELOAD=$JEMALLOC_PATH  DOC_ENGINE=infinity python rag/svr/task_executor.py 1 --debug


#启动ragflow_server
LANG=zh_CN.UTF-8 LD_LIBRARY_PATH="$HOME/local/openssl/lib64:$LD_LIBRARY_PATH" DOC_ENGINE=infinity python api/ragflow_server.py --debug

#启动web
cd web
npm run dev

```

## 容器启动命令

```bash
# 进入docker目录
cd ragflow/docker

# 标准CPU启动（默认）
docker compose -f docker-compose.yml up -d

# GPU加速启动（需要NVIDIA驱动）
docker compose -f docker-compose-gpu.yml up -d
```

## 服务健康检查

```bash
# 查看ragflow-server日志
docker logs -f ragflow-server

# 检查服务状态
docker ps | grep 'ragflow\|minio\|mysql'
```

## 环境变量覆盖示例

```bash
# 修改服务端口为8080
export SVR_HTTP_PORT=8080

# 设置系统语言环境
export LANG=zh_CN.UTF-8

docker compose -f docker-compose.yml up -d
```

## 常用维护命令

```bash
# 停止所有服务
docker compose -f docker-compose.yml down

# 重建单个服务
docker compose -f docker-compose.yml up -d --no-deps --build ragflow-server

# 查看实时日志
docker compose logs -f
```

## 文件路径说明
- 配置文件：docker/.env
- 服务配置模板：docker/service_conf.yaml.template
- MySQL数据卷：docker/mysql_data
- MinIO数据卷：docker/minio_data