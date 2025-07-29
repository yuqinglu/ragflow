# RAGFlow 服务启动指南

> 本文档提供了 RAGFlow 服务的完整启动指南，包括开发环境、生产环境和 CI/CD 部署流程。

## 📋 目录

- [环境准备](#环境准备)
- [开发环境启动](#开发环境启动)
- [Docker 容器启动](#docker-容器启动)
- [CI/CD 部署流程](#cicd-部署流程)

## 🔧 环境准备

### 依赖管理
```bash
# 升级 uv.lock 配置文件
uv lock --upgrade
```

### 系统要求
- **操作系统**: Linux/macOS/Windows
- **Docker**: 20.10+ (容器部署)
- **Node.js**: 18+ (前端开发)
- **Python**: 3.8+ (后端开发)
- **内存**: 最低 4GB，推荐 8GB+
- **存储**: 最低 10GB 可用空间

## 🚀 开发环境启动

### 前端服务启动
```bash
# 启动前端开发服务器
npx pm2 start ragflow-web

# 查看前端服务状态
npx pm2 status

# 查看前端日志
npx pm2 logs ragflow-web
```

### 后端服务启动
```bash
# 1. 启动依赖服务
docker compose -f docker-compose-base.yml up -d

# 2. 启动任务处理服务
sh run_task

# 3. 启动主服务器
sh run_server
```

### 开发环境验证
```bash
# 检查服务状态
curl http://localhost:9380/health

# 检查前端访问
curl http://localhost:3000
```

## 🐳 Docker 容器启动

### 进入 Docker 目录
```bash
cd ragflow/docker
```

提前构建python环境镜像
```bash
./scripts/build_python_env.sh --full
```

### CPU 版本启动（推荐用于开发/测试）
```bash
# 标准 CPU 启动（默认配置）
docker compose -f docker-compose.yml up -d

# 查看容器状态
docker compose -f docker-compose.yml ps

# 查看服务日志
docker compose -f docker-compose.yml logs -f
```

### GPU 版本启动（推荐用于生产环境）
```bash
# GPU 加速启动（需要 NVIDIA 驱动和 Docker GPU 支持）
docker compose -f docker-compose-gpu.yml up -d

# 验证 GPU 支持
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

### Docker 环境管理
```bash
# 停止服务
docker compose -f docker-compose.yml down

# 重启服务
docker compose -f docker-compose.yml restart

# 清理数据（谨慎使用）
docker compose -f docker-compose.yml down -v

# 更新镜像并重启
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
```

## 🔄 CI/CD 部署流程

### 1. 代码管理
```bash
# 在其他分支上进行研发
git checkout feature/new-feature
# ... 开发工作 ...

# 合并到开发分支
git checkout dev
git merge feature/new-feature

# 合并到生产分支
git checkout production
git merge dev
```

### 2. 自动部署触发
- 推送到 `dev` 分支触发开发环境部署
- 推送到 `production` 分支触发生产环境部署

### 3. 阿里云部署平台配置

#### 环境参数配置
```yaml
# 数据库配置
DB_HOST: your-db-host
DB_PORT: 3306
DB_NAME: ragflow
DB_USER: ragflow_user
DB_PASSWORD: your-password

# Redis 配置
REDIS_HOST: your-redis-host
REDIS_PORT: 6379
REDIS_PASSWORD: your-redis-password

# 对象存储配置
OSS_ACCESS_KEY: your-access-key
OSS_SECRET_KEY: your-secret-key
OSS_BUCKET: ragflow-bucket
OSS_ENDPOINT: your-oss-endpoint

# 其他配置
NODE_ENV: production
LOG_LEVEL: info
```

#### Docker 运行命令
```bash
# 生产环境启动命令
docker run -d \
  --name ragflow-production \
  -p 9380:9380 \
  -e DB_HOST=$DB_HOST \
  -e DB_PORT=$DB_PORT \
  -e DB_NAME=$DB_NAME \
  -e DB_USER=$DB_USER \
  -e DB_PASSWORD=$DB_PASSWORD \
  -e REDIS_HOST=$REDIS_HOST \
  -e REDIS_PORT=$REDIS_PORT \
  -e REDIS_PASSWORD=$REDIS_PASSWORD \
  -e OSS_ACCESS_KEY=$OSS_ACCESS_KEY \
  -e OSS_SECRET_KEY=$OSS_SECRET_KEY \
  -e OSS_BUCKET=$OSS_BUCKET \
  -e OSS_ENDPOINT=$OSS_ENDPOINT \
  -e NODE_ENV=production \
  -e LOG_LEVEL=info \
  ragflow/ragflow:latest
```

### 4. 部署后检查
```bash
# 检查容器状态
docker ps | grep ragflow

# 检查服务健康状态
curl http://your-domain:9380/health

# 检查后台日志
docker logs ragflow-production -f

# 检查资源使用情况
docker stats ragflow-production
```