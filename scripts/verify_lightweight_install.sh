#!/usr/bin/env bash
# A8 (#519): 核心包轻量安装验证——零 nvidia-*、无 torch、CRUD/BM25 smoke。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> [1/5] uv build"
cd "$ROOT"
uv build --out-dir "$WORK/dist" >/dev/null

echo "==> [2/5] 独立 venv 安装 wheel"
uv venv "$WORK/venv" >/dev/null
uv pip install --python "$WORK/venv/bin/python" "$WORK"/dist/jfox_cli-*.whl >/dev/null

echo "==> [3/5] 断言零 nvidia-* / 无 torch / 无 sentence-transformers"
BAD="$(uv pip list --python "$WORK/venv/bin/python" 2>/dev/null \
  | grep -iE '^(nvidia-|torch |sentence-transformers)' || true)"
if [ -n "$BAD" ]; then
  echo "FAIL: 轻量安装包含重依赖："
  echo "$BAD"
  exit 1
fi

echo "==> [4/5] jfox --version"
"$WORK/venv/bin/jfox" --version

echo "==> [5/5] 隔离 HOME smoke：init / add / keyword search"
SMOKE_HOME="$WORK/home"
mkdir -p "$SMOKE_HOME"
HOME="$SMOKE_HOME" "$WORK/venv/bin/jfox" init --name smoke >/dev/null
HOME="$SMOKE_HOME" "$WORK/venv/bin/jfox" add "轻量安装冒烟测试内容" --title smoke >/dev/null
HOME="$SMOKE_HOME" "$WORK/venv/bin/jfox" search "冒烟" --mode keyword --json | grep -q '"total"'

echo "PASS: 轻量安装验证通过（零 nvidia-* / 无 torch / smoke OK）"
