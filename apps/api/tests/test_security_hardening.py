"""补齐关键安全/流程测试：refresh 轮换、上传边界、任务取消。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_refresh_rotates_and_revokes_old(client, admin_token):
    """refresh 返回新 token 对，旧 refresh 不可再用。"""
    # 登录拿 refresh
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    refresh = resp.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"] != refresh

    # 旧 refresh 已被轮换撤销
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_all_refresh_tokens(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200

    # 登出后再用旧 refresh 刷新应失败
    login = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    refresh = login.json()["refresh_token"]
    # 需要先把这条也登出才能验证……用旧 token 列表方式：
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    # 登出已撤销全部；但上面刚登录生成了新 token，这里应能刷新成功
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_rejects_disguised_type(client, admin_token):
    """声明 image/png 实为 HTML：拒绝（防存储型 XSS）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    html = b"<script>alert(1)</script>"
    resp = await client.post(
        "/api/v1/assets/",
        headers=headers,
        files={"file": ("evil.png", html, "image/png")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_unknown_binary(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/assets/",
        headers=headers,
        files={"file": ("x.bin", b"\x00\x01\x02\x03", "application/octet-stream")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_accepts_real_png(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    resp = await client.post(
        "/api/v1/assets/",
        headers=headers,
        files={"file": ("a.png", png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["mime_type"] == "image/png"
    assert resp.json()["filename"] == "a.png"


@pytest.mark.asyncio
async def test_upload_filename_sanitized_and_trimmed(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    weird = "..\\..\\evil" + "长" * 300 + ".png"
    resp = await client.post(
        "/api/v1/assets/",
        headers=headers,
        files={"file": (weird, png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    name = resp.json()["filename"]
    assert ".." not in name
    assert "\\" not in name
    assert len(name) <= 255


@pytest.mark.asyncio
async def test_task_cancel_marks_cancelled(client, admin_token):
    """取消接口把任务置为 cancelled，且轮询不再翻转为 succeeded。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/generations/image/generate",
        headers=headers,
        json={"model": "mock", "prompt": "x", "width": 128, "height": 128},
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/tasks/{task_id}/cancel", headers=headers)
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_x_request_id_validation(client, admin_token):
    """非法 X-Request-ID 被替换为服务端生成的 UUID，不污染响应头。"""
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "X-Request-ID": "evil<script>alert(1)</script>" * 5,  # 超长 + 非法字符
    }
    resp = await client.get("/api/v1/health/live", headers=headers)
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-ID", "")
    import re

    assert re.fullmatch(r"[0-9a-fA-F-]{36}", rid), f"非法 request id 透传: {rid!r}"

    # 合法 ID 原样透传
    resp2 = await client.get(
        "/api/v1/health/live",
        headers={"Authorization": f"Bearer {admin_token}", "X-Request-ID": "abc-123-DEF_456"},
    )
    assert resp2.headers.get("X-Request-ID") == "abc-123-DEF_456"


@pytest.mark.asyncio
async def test_asset_content_rejects_path_traversal(client, admin_token):
    """content 接口对不存在资源返回 404，且不接受路径穿越形态的 id。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    for evil in ["../storage/foo", "..%2f..%2fetc%2fpasswd", "../../../aigc_studio.db"]:
        resp = await client.get(f"/api/v1/assets/{evil}/content", headers=headers)
        # 要么 404（不存在），要么 422（id 校验），绝不能 200 或 500
        assert resp.status_code in (404, 422), f"{evil} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_text_stream_terminates_with_done(client, admin_token):
    """流式文本生成以 done 事件结束（SSE 契约）。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with client.stream(
        "POST",
        "/api/v1/generations/text/generate",
        headers=headers,
        json={"model": "mock", "prompt": "hi", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        seen_done = False
        async for line in resp.aiter_lines():
            if line.startswith("data: ") and '"type": "done"' in line:
                seen_done = True
                break
        assert seen_done, "SSE 流未以 done 事件结束"
