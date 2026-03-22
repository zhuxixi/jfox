## 背景

来自 Issue #9 (Obsidian CLI & Omnisearch 调研)。

Omnisearch 提供可选的 HTTP Server，允许外部工具（浏览器插件、手机 App、其他服务）查询搜索索引。

当前 ZK CLI 仅提供 MCP Server (STDIO 模式)，不适合外部 HTTP 客户端访问。

## 目标

添加 HTTP API 模式，使外部工具可以通过 REST API 访问知识库。

## 应用场景

1. **浏览器插件** - 在浏览器中快速搜索笔记
2. **手机 App** - 移动端访问知识库
3. **Webhook 集成** - 接收外部事件创建笔记
4. **第三方工具** - Alfred、Raycast、uTools 等启动器

## API 设计

### 基础配置

```bash
# 启动 HTTP 服务
zk server --port 8080 --host 0.0.0.0

# 后台运行
zk server --daemon

# 指定知识库
zk server --kb work --port 8080
```

### API 端点

#### 1. 搜索

```http
GET /api/search?q={query}&top_k=5&kb={kb_name}

Response:
{
  "query": "机器学习",
  "total": 5,
  "results": [
    {
      "id": "20260321011528",
      "title": "机器学习概述",
      "content_preview": "机器学习是...",
      "score": 0.92,
      "type": "permanent"
    }
  ]
}
```

#### 2. 笔记操作

```http
# 列出笔记
GET /api/notes?type=permanent&limit=10

# 获取笔记详情
GET /api/notes/{note_id}

# 创建笔记
POST /api/notes
Content-Type: application/json

{
  "content": "笔记内容",
  "title": "笔记标题",
  "type": "fleeting",
  "tags": ["tag1", "tag2"]
}

# 更新笔记
PUT /api/notes/{note_id}

# 删除笔记
DELETE /api/notes/{note_id}
```

#### 3. 知识库管理

```http
# 列出知识库
GET /api/kbs

# 获取当前知识库
GET /api/kb/current

# 切换知识库
POST /api/kb/switch
{
  "name": "work"
}
```

#### 4. 图谱查询

```http
# 获取图谱统计
GET /api/graph/stats

# 获取笔记关联
GET /api/graph/related/{note_id}?depth=2

# 获取孤立笔记
GET /api/graph/orphans
```

#### 5. 健康检查

```http
GET /api/health

Response:
{
  "status": "ok",
  "version": "1.0.0",
  "kb": "work",
  "total_notes": 42
}
```

## 实现方案

使用 FastAPI：

```python
# zk/http_server.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List

app = FastAPI(title="ZK HTTP API")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/search")
async def search(
    q: str,
    top_k: int = Query(5, ge=1, le=50),
    kb: Optional[str] = None
):
    """搜索笔记"""
    # 实现搜索逻辑
    pass

@app.get("/api/notes")
async def list_notes(
    type: Optional[str] = None,
    limit: int = Query(10, ge=1, le=100)
):
    """列出笔记"""
    pass

@app.post("/api/notes")
async def create_note(note: NoteCreate):
    """创建笔记"""
    pass

# 更多端点...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

## 安全考虑

1. **本地绑定默认** - 仅监听 localhost
2. **可选认证** - API Key 或 Token
3. **访问控制** - 只读或读写模式

```bash
# 只读模式
zk server --readonly

# 带认证
zk server --api-key YOUR_SECRET_KEY
```

## CLI 接口

```bash
# 启动服务器
zk server

# 自定义端口
zk server --port 8888

# 后台运行
zk server --daemon

# 停止服务器
zk server stop
```

## 新增依赖

```txt
fastapi>=0.104.0
uvicorn>=0.24.0
```

## 验收标准

- [ ] FastAPI 应用框架
- [ ] 搜索 API (`/api/search`)
- [ ] 笔记 CRUD API
- [ ] 知识库管理 API
- [ ] 图谱查询 API
- [ ] CORS 支持
- [ ] 可选认证
- [ ] API 文档 (自动生成的 Swagger UI)

## 优先级

**中** - 扩展使用场景，便于外部集成

## 依赖

- Issue #9 (Obsidian CLI 调研)
