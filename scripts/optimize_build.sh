#!/bin/bash

# RAGFlow 构建优化脚本
# 用于在 CI 环境中设置和优化构建缓存

set -e

echo "=== RAGFlow 构建优化脚本 ==="

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查并创建缓存目录
setup_cache_directories() {
    log_info "设置缓存目录..."
    
    local cache_dirs=(
        ".cache/docker"
        ".cache/uv"
        ".cache/npm"
        ".cache/apt"
        ".cache/pip"
        ".cache/cargo"
    )
    
    for dir in "${cache_dirs[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            log_info "创建缓存目录: $dir"
        else
            log_info "缓存目录已存在: $dir"
        fi
    done
}

# 设置 Docker BuildKit
setup_docker_buildkit() {
    log_info "设置 Docker BuildKit..."
    
    export DOCKER_BUILDKIT=1
    export BUILDKIT_PROGRESS=plain
    
    # 检查 Docker 版本
    local docker_version=$(docker version --format '{{.Server.Version}}')
    log_info "Docker 版本: $docker_version"
    
    # 创建或使用 buildx builder
    if ! docker buildx inspect cache-builder >/dev/null 2>&1; then
        log_info "创建 buildx builder: cache-builder"
        docker buildx create --name cache-builder --use
    else
        log_info "使用现有 buildx builder: cache-builder"
        docker buildx use cache-builder
    fi
    
    # 启动 builder
    docker buildx inspect --bootstrap
}

# 检查缓存状态
check_cache_status() {
    log_info "检查缓存状态..."
    
    local cache_dirs=(
        ".cache/docker"
        ".cache/uv"
        ".cache/npm"
        ".cache/apt"
        ".cache/pip"
        ".cache/cargo"
    )
    
    for dir in "${cache_dirs[@]}"; do
        if [ -d "$dir" ]; then
            local size=$(du -sh "$dir" 2>/dev/null | cut -f1 || echo "0B")
            log_info "缓存目录 $dir 大小: $size"
        else
            log_warn "缓存目录不存在: $dir"
        fi
    done
}

# 清理过期缓存
cleanup_old_cache() {
    log_info "清理过期缓存..."
    
    # 清理超过 7 天的缓存文件
    find .cache -type f -mtime +7 -delete 2>/dev/null || true
    find .cache -type d -empty -delete 2>/dev/null || true
    
    log_info "缓存清理完成"
}

# 优化系统设置
optimize_system_settings() {
    log_info "优化系统设置..."
    
    # 增加文件描述符限制
    ulimit -n 65536 2>/dev/null || log_warn "无法设置文件描述符限制"
    
    # 设置 Docker 守护进程配置（如果可能）
    if [ -w /etc/docker/daemon.json ]; then
        log_info "检查 Docker 守护进程配置..."
    fi
}

# 预拉取基础镜像
prepull_base_images() {
    log_info "预拉取基础镜像..."
    
    local base_images=(
        "ubuntu:22.04"
        "registry.tyqy.duckdns.org/ragflow_deps:latest"
    )
    
    for image in "${base_images[@]}"; do
        log_info "拉取镜像: $image"
        docker pull "$image" || log_warn "无法拉取镜像: $image"
    done
}

# 主函数
main() {
    log_info "开始构建优化..."
    
    # 检查是否在 CI 环境中
    if [ -n "$CI" ]; then
        log_info "检测到 CI 环境"
    else
        log_warn "未检测到 CI 环境，某些优化可能不适用"
    fi
    
    # 执行优化步骤
    setup_cache_directories
    setup_docker_buildkit
    optimize_system_settings
    prepull_base_images
    check_cache_status
    
    log_info "构建优化完成"
    
    # 显示最终状态
    echo ""
    log_info "=== 构建环境状态 ==="
    echo "Docker BuildKit: $DOCKER_BUILDKIT"
    echo "构建平台: ${PLATFORM:-linux/amd64}"
    echo "项目名称: ${PROJECT_NAME:-ragflow}"
    echo "Python 版本: ${PYTHON_VERSION:-3.10}"
}

# 如果脚本被直接执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi 