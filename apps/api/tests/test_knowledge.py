"""知识库：文档 CRUD、上传边界、检索打分、问答端点。"""

from __future__ import annotations

import io

import pytest
from app.services.knowledge_retrieval import chunk_text, retrieve, tokenize

# ---------- 检索单元 ----------


def test_tokenize_mixed_language():
    assert tokenize("Hello 世界 world") == ["hello", "世", "界", "world"]


def test_chunk_text_small_and_large():
    assert chunk_text("短文") == ["短文"]
    text = "甲" * 1500  # 长度超过 size+step，必然多块
    chunks = chunk_text(text, size=700, overlap=100)
    assert len(chunks) >= 2
    assert all(len(c) <= 700 for c in chunks)


def test_retrieve_ranks_relevant_first():
    chunks = [
        ("d1", "部署文档", "安装 nginx 并配置反向代理"),
        ("d2", "菜单", "今天食堂供应红烧肉和西红柿炒蛋"),
        ("d3", "细节", "nginx worker_processes 建议按 CPU 核数设置"),
    ]
    hits = retrieve(chunks, "nginx 反向代理怎么配置", top_k=3)
    assert hits, "应检索到命中"
    assert hits[0][0] == "d1"
    assert hits[0][3] >= 1


def test_retrieve_empty_query():
    assert retrieve([("d1", "t", "内容")], "   ") == []


def test_retrieve_no_match_returns_empty():
    hits = retrieve([("d1", "t", "纯中文内容与问题无关")], "quantum entanglement", min_score=1)
    assert hits == []


# ---------- 文档 CRUD ----------


@pytest.mark.asyncio
async def test_document_crud_lifecycle(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "部署手册", "content": "第一步安装依赖。\n第二步启动服务。"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["id"]
    assert resp.json()["char_count"] > 0

    # 列表包含
    resp = await client.get("/api/v1/knowledge/documents", headers=headers)
    assert resp.status_code == 200
    assert any(d["id"] == doc_id for d in resp.json())

    # 详情带内容
    resp = await client.get(f"/api/v1/knowledge/documents/{doc_id}", headers=headers)
    assert resp.status_code == 200
    assert "安装依赖" in resp.json()["content"]

    # 删除后 404
    resp = await client.delete(f"/api/v1/knowledge/documents/{doc_id}", headers=headers)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/knowledge/documents/{doc_id}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_document_requires_auth(client):
    resp = await client.get("/api/v1/knowledge/documents")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_document_owner_isolation(client, admin_token, user_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "私密", "content": "只有管理员能看到的内容"},
        headers=headers,
    )
    doc_id = resp.json()["id"]

    # 普通用户看不到也删不掉
    other = {"Authorization": f"Bearer {user_token}"}
    resp = await client.get(f"/api/v1/knowledge/documents/{doc_id}", headers=other)
    assert resp.status_code == 404
    resp = await client.delete(f"/api/v1/knowledge/documents/{doc_id}", headers=other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_txt_md_and_rejects_other(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("note.md", io.BytesIO("# 标题\n正文内容".encode()), "text/markdown")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "note"

    # 不支持的扩展名
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_too_large(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    big = io.BytesIO(b"x" * (500 * 1024 + 1))
    resp = await client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("big.txt", big, "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 400


# ---------- 问答 ----------


@pytest.mark.asyncio
async def test_ask_answers_with_sources(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "部署手册", "content": "部署前需要安装 Python 3.12 与 Node 20。"},
        headers=headers,
    )
    resp = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "部署前需要安装什么？", "model": "mock"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["answer"]
    assert len(data["sources"]) >= 1
    assert data["sources"][0]["title"] == "部署手册"


@pytest.mark.asyncio
async def test_ask_without_docs_still_answers(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "随便问问", "model": "mock"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["sources"] == []


# ---------- RAG 接入文本生成 ----------


@pytest.mark.asyncio
async def test_text_generate_with_knowledge_context(client, admin_token):
    """文本生成带 knowledge_doc_ids：检索命中并注入提示词，done 带来源。"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "部署手册", "content": "部署前需要安装 Python 3.14 与 Node 24。"},
        headers=headers,
    )
    doc_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/generations/text/generate",
        json={
            "model": "mock",
            "prompt": "部署前需要安装什么？",
            "stream": False,
            "knowledge_doc_ids": [doc_id],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # Mock 会回显 prompt：注入的资料应出现在内容里
    assert "部署手册" in data["content"]
    assert data["knowledge_sources"][0]["doc_id"] == doc_id


@pytest.mark.asyncio
async def test_text_generate_ignores_foreign_doc_ids(client, admin_token, user_token):
    """他人文档 id 被过滤：不注入上下文、不泄露来源。"""
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        "/api/v1/knowledge/documents",
        json={"title": "私密", "content": "只有管理员知道的内容"},
        headers=admin_headers,
    )
    foreign_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/generations/text/generate",
        json={
            "model": "mock",
            "prompt": "内容是什么？",
            "stream": False,
            "knowledge_doc_ids": [foreign_id],
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["knowledge_sources"] == []
    assert "只有管理员知道的内容" not in data["content"]
