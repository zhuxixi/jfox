# Fix: daemon stop 无法停止 daemon

**Issue**: #180
**Date**: 2026-04-29

## 问题

`jfox daemon stop` 无法停止 daemon：PID 为 0 时跳过 taskkill，CLI 忽略返回值始终打印成功，超时后删除 PID 文件导致 daemon 失控。

## 根因

1. `stop_daemon()` 只从 PID 文件读 PID，读不到时 pid=0，`pid > 0` 判断为 False，taskkill 从不执行
2. `cli.py` 无条件打印 "Daemon 已停止"，忽略 `stop_daemon()` 的 False 返回
3. 超时路径调用 `_remove_pid_file()`，daemon 还活着却删了 PID 文件

## 方案：HTTP-first stop

### 改动 1：server.py 添加 /shutdown endpoint

在 `jfox/daemon/server.py` 中：

1. `main()` 改用手动创建 `uvicorn.Server(config)` 实例（替代 `uvicorn.run()`），存为全局变量 `_server`
2. 添加 `POST /shutdown` endpoint，调用 `_server.should_exit = True`
3. Daemon 收到请求后完成当前请求、退出 uvicorn event loop、进程自然退出

```python
_server = None

@app.post("/shutdown")
def shutdown():
    """请求 daemon 自行停止"""
    global _server
    if _server:
        _server.should_exit = True
    return {"status": "shutting_down"}

def main():
    global _server
    import uvicorn
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    _server = uvicorn.Server(config)
    _server.run()
```

### 改动 2：process.py 重写 stop_daemon()

新停止流程（HTTP-first）：

```
1. 读 PID 文件 → 获取 host/port（PID 作为备用）
2. health check 失败 → 清理 PID 文件 → return True
3. POST /shutdown → 等 3 秒
4. health check 失败 → 清理 PID 文件 → return True
5. 仍在运行 → 从 /health 获取真实 PID → taskkill/kill
6. 再等 5 秒
7. health check 失败 → 清理 PID 文件 → return True
8. 仍在运行 → 不删 PID 文件 → return False
```

关键变更点：
- `/shutdown` 是主要停止机制
- PID 为 0 时从 `/health` 获取真实 PID（复用 `get_daemon_status()` 已有的逻辑）
- 超时时**不删** PID 文件

### 改动 3：cli.py 检查返回值

```python
if stop_daemon():
    console.print("[green]✓ Daemon 已停止[/green]")
else:
    console.print("[red]✗ Daemon 停止失败，请手动终止进程[/red]")
    raise typer.Exit(1)
```

## 影响范围

- `jfox/daemon/server.py` — 添加 /shutdown endpoint，修改 main()
- `jfox/daemon/process.py` — 重写 stop_daemon()
- `jfox/cli.py` — daemon stop 命令检查返回值

## 测试

- 手动测试：`jfox daemon start` → 删 PID 文件 → `jfox daemon stop`（验证 health fallback）
- 手动测试：`jfox daemon start` → `jfox daemon stop`（验证 /shutdown 正常路径）
- 现有测试不受影响（stop_daemon 的接口签名不变，仍返回 bool）
