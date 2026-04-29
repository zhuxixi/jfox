# 修复 Daemon 日志 Deprecation Warnings

> Issue: #164
> Date: 2026-04-26

## 背景

`jfox daemon start` 后 `~/.jfox_daemon.log` 中有两个 deprecation warning，不影响功能但产生日志噪音。

## 修改清单

### 1. FastAPI `on_event` → `lifespan` 模式

**文件:** `jfox/daemon/server.py`

将 `@app.on_event("startup")` 替换为 FastAPI 官方推荐的 `lifespan` context manager：

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    _load_model()
    yield

app = FastAPI(title="JFox Embedding Daemon", lifespan=lifespan)
```

`_load_model()` 函数体不变，仅去掉 `@app.on_event("startup")` 装饰器。

### 2. `get_sentence_embedding_dimension()` → `get_embedding_dimension()`

**文件:** `jfox/embedding_backend.py`

两处直接替换：

- 行 98 (`load` 方法内): `self.model.get_sentence_embedding_dimension()` → `self.model.get_embedding_dimension()`
- 行 138 (`dimension` property 内): 同上

### 3. `performance.py` fallback 路径改用 `backend.dimension`

**文件:** `jfox/performance.py`

行 144 改用 dimension property，不直接访问模型内部方法：

```python
dim = backend.dimension  # 替代 backend.model.get_sentence_embedding_dimension()
```

这样更统一，且与 daemon 模式兼容（daemon 模式下 `backend.model` 为 None）。

## 影响范围

- 纯 API 重命名/模式迁移，行为不变
- 无需改动测试（warning 不影响断言）
- 兼容当前 sentence-transformers 版本（新方法已可用）
