"""register_batch 挂起检测与跨 run 累计逻辑测试。

用 httpx.MockTransport 模拟注册机 API（不依赖真实容器）：
- 挂起检测：计数 25 分钟无变化（测试中缩短）→ stop + 重启剩余
- 跨 run 累计：status 的 success/failed 是当前 run 的，多轮 run 后累计达成目标
- 完成判定：run 结束且累计 >= run_count
"""


import httpx
import pytest
from app.tasks import register_batch


def _status(
    phase: str, run_id: str, success: int = 0, failed: int = 0, total: int = 0
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "phase": phase,
            "runId": run_id,
            "current": 1,
            "total": total,
            "success": success,
            "failed": failed,
            "planASuccess": success,
            "errorMessage": None,
        },
    )


def _start_ok(run_id: str) -> httpx.Response:
    return httpx.Response(200, json={"runId": run_id})


class FakeRegister:
    """有状态模拟：依次回放脚本，记录 start/stop 调用。"""

    def __init__(self, script: list[httpx.Response]) -> None:
        self.script = list(script)
        self.starts: list[int] = []
        self.stops: list[int] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start"):
            self.starts.append(1)
            return self.script.pop(0)
        if request.url.path.endswith("/stop"):
            self.stops.append(1)
            return httpx.Response(200, json={"ok": True})
        if request.url.path.endswith("/status"):
            return self.script.pop(0)
        return httpx.Response(404, json={})


@pytest.fixture
def fast_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """缩短轮询间隔与挂起判定，让测试秒级完成。"""
    monkeypatch.setattr(register_batch, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(register_batch, "STALL_SECONDS", 0.005)
    monkeypatch.setattr(register_batch, "MAX_WAIT", 30)
    monkeypatch.setattr(register_batch, "_internal_key", lambda: "test-key")


async def _run_with(script: list[httpx.Response], run_count: int = 2) -> dict[str, object]:
    fake = FakeRegister(script)
    transport = httpx.MockTransport(fake.handler)
    original = register_batch.httpx.AsyncClient

    class _FakeClient(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    register_batch.httpx.AsyncClient = _FakeClient  # type: ignore[attr-defined]
    try:
        return await register_batch._run_batch(run_count)
    finally:
        register_batch.httpx.AsyncClient = original


@pytest.mark.asyncio
async def test_normal_completion(fast_batch: None) -> None:
    """单 run 正常完成：running → 推进 → idle → 成功返回。"""
    script = [
        _start_ok("run-1"),
        _status("running", "run-1", success=1, total=2),
        _status("running", "run-1", success=2, total=2),
        _status("idle", "run-1", success=2, total=2),
    ]
    r = await _run_with(script, run_count=2)
    assert r["ok"] is True
    assert r["success"] == 2
    assert r["restart_count"] == 0


@pytest.mark.asyncio
async def test_stall_detection_restarts(fast_batch: None) -> None:
    """挂起检测：计数长时间无变化 → stop → 重启剩余 → 最终完成。"""
    script = [
        _start_ok("run-1"),
        _status("running", "run-1", success=1, total=3),
        _status("running", "run-1", success=1, total=3),  # 计数不变 → 触发挂起
        _start_ok("run-2"),
        _status("running", "run-2", success=0, total=2),  # 新 run 从 0 开始（跨 run 累计）
        _status("running", "run-2", success=2, total=2),
        _status("idle", "run-2", success=2, total=2),
    ]
    r = await _run_with(script, run_count=3)
    assert r["ok"] is True
    # 跨 run 累计：run-1 的 1 + run-2 的 2 = 3
    assert r["success"] == 3
    assert r["restart_count"] == 1


@pytest.mark.asyncio
async def test_killed_run_restarts_remaining(fast_batch: None) -> None:
    """异常终止（killed）且未完成 → 自动重启剩余数量。"""
    script = [
        _start_ok("run-1"),
        _status("running", "run-1", success=1, total=2),
        _status("killed", "run-1", success=1, total=2),  # 异常终止
        _start_ok("run-2"),
        _status("running", "run-2", success=1, total=1),
        _status("idle", "run-2", success=1, total=1),
    ]
    r = await _run_with(script, run_count=2)
    assert r["ok"] is True
    assert r["success"] == 2
    assert r["restart_count"] == 1


@pytest.mark.asyncio
async def test_missing_key_returns_error(fast_batch: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(register_batch, "_internal_key", lambda: "")
    r = await register_batch._run_batch(2)
    assert r["ok"] is False
    assert "key" in str(r.get("error", ""))


@pytest.mark.asyncio
async def test_start_failure_returns_error(
    fast_batch: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(register_batch, "_internal_key", lambda: "k")
    fake = FakeRegister([httpx.Response(500, json={"error": "boom"})])
    transport = httpx.MockTransport(fake.handler)
    original = register_batch.httpx.AsyncClient

    class _FakeClient(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    register_batch.httpx.AsyncClient = _FakeClient  # type: ignore[attr-defined]
    try:
        r = await register_batch._run_batch(2)
    finally:
        register_batch.httpx.AsyncClient = original
    assert r["ok"] is False
    assert "500" in str(r.get("error", ""))
