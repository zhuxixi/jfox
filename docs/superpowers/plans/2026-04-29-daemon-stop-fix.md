# Fix daemon stop 无法停止 daemon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `jfox daemon stop` so it reliably stops the daemon using HTTP `/shutdown` as primary mechanism, with taskkill/kill as fallback.

**Architecture:** Add a `POST /shutdown` endpoint to the daemon server that sets `uvicorn.Server.should_exit`. Rewrite `stop_daemon()` to call `/shutdown` first, then fall back to OS-level kill. Fix CLI to check the return value.

**Tech Stack:** Python, FastAPI, uvicorn, urllib

**Spec:** `docs/superpowers/specs/2026-04-29-daemon-stop-fix-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `jfox/daemon/server.py` | Modify | Add `/shutdown` endpoint, refactor `main()` to use `uvicorn.Server` directly |
| `jfox/daemon/process.py` | Modify | Rewrite `stop_daemon()` with HTTP-first flow, add `_http_shutdown()` helper |
| `jfox/cli.py` | Modify | Check `stop_daemon()` return value in daemon stop command |

---

### Task 1: Add /shutdown endpoint to server.py

**Files:**
- Modify: `jfox/daemon/server.py`

- [ ] **Step 1: Add global `_server` variable and `/shutdown` endpoint**

Add `_server = None` after the `_backend = None` line (line 20). Add the `/shutdown` endpoint after the `/health` endpoint (after line 98).

In `jfox/daemon/server.py`, the top of the file should have:

```python
# 全局 embedding 后端（模型加载后常驻内存）
_backend = None

# uvicorn Server 实例（用于 graceful shutdown）
_server = None
```

Add the `/shutdown` endpoint after the `/health` endpoint (after line 98):

```python
@app.post("/shutdown")
def shutdown():
    """请求 daemon 自行停止"""
    global _server
    if _server:
        _server.should_exit = True
    return {"status": "shutting_down"}
```

- [ ] **Step 2: Refactor `main()` to use `uvicorn.Server` directly**

Replace the existing `main()` function (lines 126-140) with:

```python
def main():
    from . import DEFAULT_HOST, DEFAULT_PORT

    parser = argparse.ArgumentParser(description="JFox Embedding Daemon")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    args = parser.parse_args()

    import uvicorn

    global _server
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    _server = uvicorn.Server(config)
    _server.run()
```

This replaces `uvicorn.run()` with manual `uvicorn.Server` + `_server.run()`, so the `/shutdown` endpoint can set `_server.should_exit = True`.

- [ ] **Step 3: Verify daemon starts correctly**

Run: `uv run python -c "from jfox.daemon.server import app; print('server module OK')"`

Expected: `server module OK` — confirms no import or syntax errors.

- [ ] **Step 4: Commit**

```bash
git add jfox/daemon/server.py
git commit -m "feat(daemon): add /shutdown endpoint for graceful stop"
```

---

### Task 2: Add _http_shutdown() helper and rewrite stop_daemon()

**Files:**
- Modify: `jfox/daemon/process.py`

- [ ] **Step 1: Add `_http_shutdown()` helper**

Add this function after `_http_health_check()` (after line 88) in `jfox/daemon/process.py`:

```python
def _http_shutdown(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """请求 daemon 通过 /shutdown endpoint 自行停止"""
    try:
        import urllib.request

        req = urllib.request.Request(
            f"http://{host}:{port}/shutdown", method="POST", data=b""
        )
        resp = urllib.request.urlopen(req, timeout=3)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("status") == "shutting_down"
    except (OSError, ValueError):
        return False
```

- [ ] **Step 2: Rewrite `stop_daemon()` with HTTP-first flow**

Replace the entire `stop_daemon()` function (lines 261-308) with:

```python
def stop_daemon() -> bool:
    """
    停止 daemon 进程

    Returns:
        True 表示停止成功
    """
    data = _read_pid_file()
    host = DEFAULT_HOST
    port = DEFAULT_PORT
    pid = 0

    if data is not None:
        pid = data.get("pid", 0)
        host = data.get("host", DEFAULT_HOST)
        port = data.get("port", DEFAULT_PORT)

    # 先检查是否真的在跑
    health = _http_health_check(host, port)
    if health is None:
        _remove_pid_file()
        return True

    # 1. 优先通过 HTTP /shutdown 让 daemon 自行退出
    logger.info("正在通过 /shutdown 请求 daemon 停止...")
    _http_shutdown(host, port)

    # 等待 daemon 自行退出（最多 3 秒）
    for _ in range(6):
        if _http_health_check(host, port) is None:
            _remove_pid_file()
            logger.info("Daemon 已通过 /shutdown 停止")
            return True
        time.sleep(0.5)

    # 2. /shutdown 失败，从 /health 获取真实 PID 后尝试 taskkill/kill
    if pid == 0:
        health = _http_health_check(host, port)
        if health:
            pid = health.get("pid", 0)

    if pid > 0:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.kill(pid, 15)  # SIGTERM
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"停止 daemon 失败: {e}")

    # 等待进程退出（最多 5 秒）
    for _ in range(10):
        if _http_health_check(host, port) is None:
            _remove_pid_file()
            logger.info(f"Daemon 已停止 (PID: {pid})")
            return True
        time.sleep(0.5)

    # 超时未退出 — 不删 PID 文件，保留追踪信息
    logger.warning(f"Daemon 停止超时 (PID: {pid})")
    return False
```

Key differences from the old version:
- `/shutdown` HTTP call is tried first (lines after "优先通过 HTTP")
- Health check loop after `/shutdown` waits up to 3 seconds
- If PID is 0, fetches real PID from `/health` response (the "Bug 1" fix)
- On timeout, does NOT remove PID file (the "Bug 3" fix)

- [ ] **Step 3: Verify module imports correctly**

Run: `uv run python -c "from jfox.daemon.process import stop_daemon; print('process module OK')"`

Expected: `process module OK`

- [ ] **Step 4: Commit**

```bash
git add jfox/daemon/process.py
git commit -m "fix(daemon): rewrite stop_daemon with HTTP-first shutdown"
```

---

### Task 3: Fix CLI to check stop_daemon() return value

**Files:**
- Modify: `jfox/cli.py:2657-2663`

- [ ] **Step 1: Update daemon stop branch to check return value**

In `jfox/cli.py`, replace lines 2657-2663:

```python
        elif action == "stop":
            if not is_daemon_running():
                console.print("[dim]Daemon 未运行[/dim]")
                return
            console.print("[yellow]正在停止 daemon...[/yellow]")
            stop_daemon()
            console.print("[green]✓ Daemon 已停止[/green]")
```

with:

```python
        elif action == "stop":
            if not is_daemon_running():
                console.print("[dim]Daemon 未运行[/dim]")
                return
            console.print("[yellow]正在停止 daemon...[/yellow]")
            if stop_daemon():
                console.print("[green]✓ Daemon 已停止[/green]")
            else:
                console.print("[red]✗ Daemon 停止失败，请手动终止进程[/red]")
                raise typer.Exit(1)
```

This fixes "Bug 2" — the CLI now reports failure when `stop_daemon()` returns `False`.

- [ ] **Step 2: Verify CLI module loads**

Run: `uv run python -c "from jfox.cli import app; print('cli module OK')"`

Expected: `cli module OK`

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "fix(cli): check stop_daemon return value in daemon stop command"
```

---

### Task 4: Manual integration test

This task requires a running daemon and manual verification. Do not automate — provide commands for the user.

**Files:** None (testing only)

- [ ] **Step 1: Test normal stop path**

```bash
uv run jfox daemon start
uv run jfox daemon stop
uv run jfox daemon status   # should show "Daemon 未运行"
```

Expected: stop succeeds, status shows not running.

- [ ] **Step 2: Test PID-file-missing fallback**

```bash
uv run jfox daemon start
# Delete PID file to simulate the bug scenario
rm ~/.jfox_daemon.pid
uv run jfox daemon stop     # should still succeed via /shutdown
uv run jfox daemon status   # should show "Daemon 未运行"
```

Expected: stop succeeds even without PID file, because `/shutdown` works without PID.

- [ ] **Step 3: Test stop when already stopped**

```bash
uv run jfox daemon stop     # daemon not running
```

Expected: shows "Daemon 未运行" immediately.

- [ ] **Step 4: Final commit if any adjustments needed**

If any issues were found and fixed during manual testing, commit the fixes:

```bash
git add -A
git commit -m "fix(daemon): adjustments from manual testing"
```
