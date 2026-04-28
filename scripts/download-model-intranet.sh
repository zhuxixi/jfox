#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# JFox 内网模型下载脚本
# 当 huggingface_hub 无法工作时，使用 curl 手动下载模型
# =============================================================================

MODEL_NAME="${1:-sentence-transformers/all-MiniLM-L6-v2}"
HF_MIRROR="https://hf-mirror.com"

# 获取 HF 缓存目录
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
MODEL_CACHE="$HUB_CACHE/models--${MODEL_NAME//\//--}"

info()  { echo -e "\033[0;32m[INFO]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; }

# 检查 curl
if ! command -v curl > /dev/null 2>&1; then
    error "curl 未安装，请先安装 curl"
    exit 1
fi

info "目标模型: $MODEL_NAME"
info "缓存目录: $MODEL_CACHE"

# 生成伪 commit hash
COMMIT_HASH=$(echo -n "$MODEL_NAME" | sha256sum | cut -c1-12)
SNAPSHOT_DIR="$MODEL_CACHE/snapshots/$COMMIT_HASH"

mkdir -p "$SNAPSHOT_DIR"

# 下载文件列表
FILES=("model.safetensors" "config.json" "tokenizer.json" "tokenizer_config.json")

for fname in "${FILES[@]}"; do
    URL="$HF_MIRROR/$MODEL_NAME/resolve/main/$fname"
    DEST="$SNAPSHOT_DIR/$fname"

    if [ -f "$DEST" ] && [ -s "$DEST" ]; then
        info "$fname 已存在，跳过"
        continue
    fi

    info "下载 $fname..."
    if curl -L -f -s -S --connect-timeout 10 --max-time 120 \
         -o "$DEST" "$URL"; then
        info "$fname 下载完成"
    else
        warn "$fname 下载失败或不存在，跳过"
        rm -f "$DEST"
    fi
done

# 检查核心文件
if [ ! -f "$SNAPSHOT_DIR/model.safetensors" ]; then
    error "model.safetensors 下载失败"
    exit 1
fi

# 创建 refs
mkdir -p "$MODEL_CACHE/refs"
echo "$COMMIT_HASH" > "$MODEL_CACHE/refs/main"

info "模型下载完成: $MODEL_CACHE"
info "现在可以运行: jfox daemon start"
