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

# 基础依赖镜像配置
BASE_IMAGE_NAME="ragflow_deps"
BASE_IMAGE_TAG="latest"
SOURCE_REGISTRY="infiniflow"
SOURCE_IMAGE="${SOURCE_REGISTRY}/${BASE_IMAGE_NAME}:${BASE_IMAGE_TAG}"
TARGET_IMAGE="${REGISTRY}/${BASE_IMAGE_NAME}:${BASE_IMAGE_TAG}"

# 解析命令行参数
BUILD_TYPE="full"  # 默认构建完整版本
NO_CACHE=false     # 默认使用缓存
CLEAN_AFTER_PUSH=false  # 默认不清理本地镜像

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
        --clean-after-push)
            CLEAN_AFTER_PUSH=true
            shift
            ;;
        --help)
            echo "用法: $0 [--full|--light] [--no-cache] [--clean-after-push]"
            echo "  --full             构建完整版本（包含 GPU 依赖，默认）"
            echo "  --light            构建轻量级版本（不包含 GPU 依赖）"
            echo "  --no-cache         跳过缓存，强制重新构建"
            echo "  --clean-after-push 推送后清理本地镜像"
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

# 检查基础依赖镜像
check_base_image() {
    log_info "检查基础依赖镜像..."
    
    # 检查网络连接
    log_info "检查网络连接..."
    if ! ping -c 1 ${SOURCE_REGISTRY} >/dev/null 2>&1; then
        log_warn "无法连接到源仓库 ${SOURCE_REGISTRY}，尝试继续执行..."
    else
        log_success "网络连接正常"
    fi
    
    # 检查目标镜像是否存在
    if docker manifest inspect ${TARGET_IMAGE} >/dev/null 2>&1; then
        log_success "基础依赖镜像已存在: ${TARGET_IMAGE}"
        
        # 显示镜像大小信息
        log_info "获取镜像大小信息..."
        IMAGE_SIZE=$(docker images ${TARGET_IMAGE} --format "table {{.Size}}" | tail -n +2)
        if [ -n "$IMAGE_SIZE" ]; then
            log_info "镜像大小: ${IMAGE_SIZE}"
        fi
        
        return 0
    else
        log_warn "基础依赖镜像不存在: ${TARGET_IMAGE}"
        log_info "从源镜像拉取: ${SOURCE_IMAGE}"
        
        # 拉取源镜像
        if docker pull ${SOURCE_IMAGE}; then
            log_success "源镜像拉取成功"
            
            # 显示源镜像大小信息
            log_info "获取源镜像大小信息..."
            SOURCE_SIZE=$(docker images ${SOURCE_IMAGE} --format "table {{.Size}}" | tail -n +2)
            if [ -n "$SOURCE_SIZE" ]; then
                log_info "源镜像大小: ${SOURCE_SIZE}"
            fi
            
            # 重新标记镜像
            log_info "重新标记镜像..."
            if docker tag ${SOURCE_IMAGE} ${TARGET_IMAGE}; then
                log_success "镜像重新标记成功"
                
                # 推送到目标仓库
                log_info "推送镜像到目标仓库..."
                if docker push ${TARGET_IMAGE}; then
                    log_success "基础依赖镜像推送成功: ${TARGET_IMAGE}"
                    
                    # 显示推送后的镜像大小信息
                    log_info "获取推送后镜像大小信息..."
                    PUSHED_SIZE=$(docker images ${TARGET_IMAGE} --format "table {{.Size}}" | tail -n +2)
                    if [ -n "$PUSHED_SIZE" ]; then
                        log_info "推送后镜像大小: ${PUSHED_SIZE}"
                    fi
                    
                    # 如果启用清理选项，删除本地镜像
                    if [ "$CLEAN_AFTER_PUSH" = true ]; then
                        log_info "清理本地镜像..."
                        docker rmi ${SOURCE_IMAGE} ${TARGET_IMAGE} 2>/dev/null || true
                        log_success "本地镜像清理完成"
                    fi
                    
                    return 0
                else
                    log_error "基础依赖镜像推送失败"
                    return 1
                fi
            else
                log_error "镜像重新标记失败"
                return 1
            fi
        else
            log_error "源镜像拉取失败: ${SOURCE_IMAGE}"
            return 1
        fi
    fi
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
    check_base_image || {
        log_error "基础依赖镜像检查失败，退出构建"
        exit 1
    }
    build_image
    push_image
    test_image
    
    log_success "=== 构建完成 ==="
    log_info "镜像地址: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
    log_info "构建类型: ${BUILD_TYPE}"
    log_info "基础依赖镜像: ${TARGET_IMAGE}"
    if [ "$CLEAN_AFTER_PUSH" = true ]; then
        log_info "本地镜像清理: 已启用"
    else
        log_info "本地镜像清理: 未启用"
    fi
    log_info "现在可以在 Dockerfile 中使用此镜像来加速构建"
}

# 执行主函数
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi 