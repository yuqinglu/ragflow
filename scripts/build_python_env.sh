#!/bin/bash

# Python 虚拟环境预构建脚本
# 用于构建包含预安装 Python 依赖的镜像

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 配置变量
REGISTRY="registry.tyqy.duckdns.org"
IMAGE_NAME="ragflow_python_env"
IMAGE_TAG="latest"
PLATFORM="linux/amd64"

# 解析命令行参数
BUILD_TYPE="full"  # 默认构建完整版本
NO_CACHE=false     # 默认使用缓存

while [[ $# -gt 0 ]]; do
    case $1 in
        --full)
            BUILD_TYPE="full"
            shift
            ;;
        --light)
            BUILD_TYPE="light"
            shift
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --help)
            echo "用法: $0 [--full|--light] [--no-cache]"
            echo "  --full      构建完整版本（包含 GPU 依赖，默认）"
            echo "  --light     构建轻量级版本（不包含 GPU 依赖）"
            echo "  --no-cache  跳过缓存，强制重新构建"
            exit 0
            ;;
        *)
            log_error "未知参数: $1"
            exit 1
            ;;
    esac
done

# 检查必要文件
check_files() {
    log_info "检查必要文件..."
    
    if [ ! -f "pyproject.toml" ]; then
        log_error "pyproject.toml 文件不存在"
        exit 1
    fi
    
    if [ ! -f "uv.lock" ]; then
        log_error "uv.lock 文件不存在"
        exit 1
    fi
    
    if [ "$BUILD_TYPE" = "light" ]; then
        if [ ! -f "Dockerfile.python-env-light" ]; then
            log_error "Dockerfile.python-env-light 文件不存在"
            exit 1
        fi
        DOCKERFILE="Dockerfile.python-env-light"
        IMAGE_TAG="light"
    else
        if [ ! -f "Dockerfile.python-env" ]; then
            log_error "Dockerfile.python-env 文件不存在"
            exit 1
        fi
        DOCKERFILE="Dockerfile.python-env"
        IMAGE_TAG="latest"
    fi
    
    log_success "所有必要文件检查通过"
    log_info "构建类型: $BUILD_TYPE"
    log_info "使用 Dockerfile: $DOCKERFILE"
}

# 构建镜像
build_image() {
    log_info "开始构建 Python 环境镜像..."
    log_info "镜像名称: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
    log_info "目标平台: ${PLATFORM}"
    log_info "构建类型: ${BUILD_TYPE}"
    if [ "$NO_CACHE" = true ]; then
        log_info "跳过缓存: 强制重新构建"
        CACHE_FLAG="--no-cache"
    else
        log_info "使用缓存: 复用已构建的层"
        CACHE_FLAG=""
    fi
    
    # 构建镜像
    docker buildx build \
        --platform ${PLATFORM} \
        --file ./${DOCKERFILE} \
        --tag ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} \
        --progress=plain \
        ${CACHE_FLAG} \
        .
    
    log_success "镜像构建完成"
}

# 推送镜像
push_image() {
    log_info "推送镜像到仓库..."
    
    docker push ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
    
    log_success "镜像推送完成"
}

# 测试镜像
test_image() {
    log_info "测试镜像..."
    
    # 运行容器并检查虚拟环境
    docker run --rm ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} \
        ls -la /python-env/.venv/bin/python
    
    log_success "镜像测试通过"
}

# 主函数
main() {
    log_info "=== Python 虚拟环境预构建脚本 ==="
    
    check_files
    build_image
    push_image
    test_image
    
    log_success "=== 构建完成 ==="
    log_info "镜像地址: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
    log_info "构建类型: ${BUILD_TYPE}"
    log_info "现在可以在 Dockerfile 中使用此镜像来加速构建"
}

# 执行主函数
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi 