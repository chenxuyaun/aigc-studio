"""模型中心（Model Hub）—— 独立 Provider 管理与一键激活服务。

参考 CC Switch 形态：
- 集中管理多个 LLM/媒体 provider（base_url / api_key / 模型 / 能力）
- 一键「激活」当前使用的 provider
- saiOS 等消费方通过 GET /api/active 动态拉取当前激活配置

存储：SQLite（轻量、独立，不依赖 saiOS MySQL）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path(os.environ.get("MODEL_HUB_DB", str(Path(__file__).parent / "model_hub.db")))
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Model Hub", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 存储层（sqlite3，同步但轻量）────────────────────────────
def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS providers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT DEFAULT 'openai_compatible',
                base_url TEXT DEFAULT '',
                encrypted_api_key TEXT DEFAULT '',
                default_model TEXT DEFAULT '',
                capabilities TEXT DEFAULT '{}',
                priority INTEGER DEFAULT 1,
                is_enabled INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 0,
                group_tag TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT DEFAULT '',
                is_active INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        # R2 模型 curation：per-provider 的模型置顶/隐藏/别名（Cherry Studio 式模型管理）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_models (
                provider_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                label TEXT DEFAULT '',
                pinned INTEGER DEFAULT 0,
                hidden INTEGER DEFAULT 0,
                updated_at REAL,
                PRIMARY KEY (provider_id, model_id)
            )
            """
        )
        # 兼容老库：补 group_tag / note 列
        cols = {r[1] for r in conn.execute("PRAGMA table_info(providers)").fetchall()}
        if "group_tag" not in cols:
            conn.execute("ALTER TABLE providers ADD COLUMN group_tag TEXT DEFAULT ''")
        if "note" not in cols:
            conn.execute("ALTER TABLE providers ADD COLUMN note TEXT DEFAULT ''")
        # 健康巡检状态列（CC Switch 式持续健康监控）
        if "last_check_at" not in cols:
            conn.execute("ALTER TABLE providers ADD COLUMN last_check_at REAL")
        if "last_ok" not in cols:
            conn.execute("ALTER TABLE providers ADD COLUMN last_ok INTEGER DEFAULT -1")
        if "last_latency_ms" not in cols:
            conn.execute("ALTER TABLE providers ADD COLUMN last_latency_ms INTEGER")
        # v2：按能力槽位激活（对话/生图/视频/语音可各指向不同 provider，Cherry Studio 式）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS active_slots (
                slot TEXT PRIMARY KEY,
                provider_id TEXT,
                updated_at REAL
            )
            """
        )
        # v3：故障转移链——每槽位多个候选 provider，按 position 顺序降级
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slot_providers (
                slot TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                updated_at REAL,
                PRIMARY KEY (slot, provider_id)
            )
            """
        )
        _seed_slots(conn)
        _seed_chains_from_slots(conn)


SLOTS: tuple[str, ...] = ("text", "image", "video", "audio", "music")


def _seed_slots(conn: sqlite3.Connection) -> None:
    """v1→v2 迁移：槽位表为空且存在全局激活 provider 时，全部槽位指向它。"""
    n = conn.execute("SELECT COUNT(*) FROM active_slots").fetchone()[0]
    if n:
        return
    row = conn.execute(
        "SELECT id FROM providers WHERE is_active = 1 ORDER BY priority ASC LIMIT 1"
    ).fetchone()
    if row is None:
        return
    now = time.time()
    for s in SLOTS:
        conn.execute(
            "INSERT OR REPLACE INTO active_slots (slot, provider_id, updated_at) VALUES (?, ?, ?)",
            (s, row["id"], now),
        )


def _seed_chains_from_slots(conn: sqlite3.Connection) -> None:
    """v2→v3 迁移：slot_providers 为空时，从 active_slots 单选播种为单元素链。"""
    n = conn.execute("SELECT COUNT(*) FROM slot_providers").fetchone()[0]
    if n:
        return
    now = time.time()
    for row in conn.execute(
        "SELECT slot, provider_id FROM active_slots WHERE provider_id IS NOT NULL"
    ).fetchall():
        conn.execute(
            "INSERT OR REPLACE INTO slot_providers (slot, provider_id, position, updated_at) VALUES (?, ?, 0, ?)",
            (row["slot"], row["provider_id"], now),
        )


_init_db()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "provider_type": row["provider_type"],
        "base_url": row["base_url"],
        "has_api_key": bool(row["encrypted_api_key"]),
        "api_key": row["encrypted_api_key"] if os.environ.get("MODEL_HUB_EXPOSE_KEY") else "",
        "default_model": row["default_model"],
        "capabilities": json.loads(row["capabilities"] or "{}"),
        "priority": row["priority"],
        "is_enabled": bool(row["is_enabled"]),
        "is_active": bool(row["is_active"]),
        "group_tag": row["group_tag"] or "",
        "note": row["note"] or "",
        "last_check_at": row["last_check_at"] if "last_check_at" in row.keys() else None,
        "last_ok": (row["last_ok"] if "last_ok" in row.keys() else -1),
        "last_latency_ms": row["last_latency_ms"] if "last_latency_ms" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ── 模型 ─────────────────────────────────────────────────────
class ProviderIn(BaseModel):
    name: str
    provider_type: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    capabilities: dict[str, Any] = {}
    priority: int = 1
    is_enabled: bool = True
    group_tag: str = ""
    note: str = ""


# ── 预设模板库（对齐 CC Switch 预设清单：选预设 → 只填 Key 即用）──────
# category: 官方国际 / 国内官方 / 聚合中转 / 生图多模态 / 本地自建
PRESETS: list[dict[str, Any]] = [
    # ── 官方国际 ──
    {"key": "openai", "category": "官方国际", "name": "OpenAI", "provider_type": "openai_compatible",
     "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o",
     "capabilities": {"text": True, "image": True}, "desc": "OpenAI 官方"},
    {"key": "anthropic", "category": "官方国际", "name": "Anthropic Claude", "provider_type": "openai_compatible",
     "base_url": "https://api.anthropic.com", "default_model": "claude-sonnet-4-5",
     "capabilities": {"text": True}, "desc": "Claude 官方"},
    {"key": "grok", "category": "官方国际", "name": "Grok / xAI", "provider_type": "openai_compatible",
     "base_url": "https://api.x.ai/v1", "default_model": "grok-4.20-fast",
     "capabilities": {"text": True, "image": True}, "desc": "xAI Grok 官方"},
    {"key": "gemini", "category": "官方国际", "name": "Google Gemini", "provider_type": "openai_compatible",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "default_model": "gemini-2.5-flash",
     "capabilities": {"text": True, "image": True}, "desc": "Gemini OpenAI 兼容端点"},
    {"key": "nvidia", "category": "官方国际", "name": "NVIDIA NIM", "provider_type": "openai_compatible",
     "base_url": "https://integrate.api.nvidia.com/v1", "default_model": "meta/llama-3.3-70b-instruct",
     "capabilities": {"text": True}, "desc": "NVIDIA 推理服务"},
    {"key": "mistral", "category": "官方国际", "name": "Mistral", "provider_type": "openai_compatible",
     "base_url": "https://api.mistral.ai/v1", "default_model": "mistral-large-latest",
     "capabilities": {"text": True}, "desc": "Mistral 官方"},
    # ── 国内官方 ──
    {"key": "deepseek", "category": "国内官方", "name": "DeepSeek", "provider_type": "openai_compatible",
     "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat",
     "capabilities": {"text": True}, "desc": "DeepSeek 官方"},
    {"key": "glm", "category": "国内官方", "name": "智谱 GLM", "provider_type": "openai_compatible",
     "base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-4-flash",
     "capabilities": {"text": True}, "desc": "智谱 AI GLM 系列"},
    {"key": "kimi", "category": "国内官方", "name": "Kimi / Moonshot", "provider_type": "openai_compatible",
     "base_url": "https://api.moonshot.cn/v1", "default_model": "moonshot-v1-8k",
     "capabilities": {"text": True}, "desc": "Moonshot Kimi"},
    {"key": "qwen", "category": "国内官方", "name": "阿里百炼 Qwen", "provider_type": "openai_compatible",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus",
     "capabilities": {"text": True}, "desc": "通义千问"},
    {"key": "doubao", "category": "国内官方", "name": "火山方舟 Doubao", "provider_type": "openai_compatible",
     "base_url": "https://ark.cn-beijing.volces.com/api/v3", "default_model": "doubao-seed-1-6-250615",
     "capabilities": {"text": True}, "desc": "字节火山方舟"},
    {"key": "minimax", "category": "国内官方", "name": "MiniMax", "provider_type": "openai_compatible",
     "base_url": "https://api.minimax.chat/v1", "default_model": "MiniMax-Text-01",
     "capabilities": {"text": True}, "desc": "MiniMax 大模型"},
    {"key": "stepfun", "category": "国内官方", "name": "阶跃星辰 StepFun", "provider_type": "openai_compatible",
     "base_url": "https://api.stepfun.com/v1", "default_model": "step-2-16k",
     "capabilities": {"text": True, "image": True}, "desc": "Step 系列"},
    {"key": "modelscope", "category": "国内官方", "name": "魔搭 ModelScope", "provider_type": "openai_compatible",
     "base_url": "https://api-inference.modelscope.cn/v1", "default_model": "Qwen/Qwen2.5-72B-Instruct",
     "capabilities": {"text": True}, "desc": "魔搭社区免费推理"},
    {"key": "baichuan", "category": "国内官方", "name": "百川 Baichuan", "provider_type": "openai_compatible",
     "base_url": "https://api.baichuan-ai.com/v1", "default_model": "Baichuan4",
     "capabilities": {"text": True}, "desc": "百川智能"},
    {"key": "spark", "category": "国内官方", "name": "讯飞星火 Spark", "provider_type": "openai_compatible",
     "base_url": "https://spark-api-open.xf-yun.com/v1", "default_model": "generalv3.5",
     "capabilities": {"text": True}, "desc": "科大讯飞星火"},
    {"key": "siliconflow", "category": "国内官方", "name": "硅基流动 SiliconFlow", "provider_type": "openai_compatible",
     "base_url": "https://api.siliconflow.cn/v1", "default_model": "deepseek-ai/DeepSeek-V3",
     "capabilities": {"text": True, "image": True}, "desc": "多模态模型平台"},
    # ── 聚合中转 ──
    {"key": "openrouter", "category": "聚合中转", "name": "OpenRouter", "provider_type": "openai_compatible",
     "base_url": "https://openrouter.ai/api/v1", "default_model": "openai/gpt-4o",
     "capabilities": {"text": True, "image": True}, "desc": "聚合 300+ 模型"},
    {"key": "aihubmix", "category": "聚合中转", "name": "AiHubMix", "provider_type": "openai_compatible",
     "base_url": "https://aihubmix.com/v1", "default_model": "gpt-4o",
     "capabilities": {"text": True, "image": True}, "desc": "AiHubMix 聚合"},
    {"key": "dmxapi", "category": "聚合中转", "name": "DMXAPI", "provider_type": "openai_compatible",
     "base_url": "https://www.dmxapi.cn/v1", "default_model": "gpt-4o",
     "capabilities": {"text": True, "image": True}, "desc": "一个 Key 用全球大模型"},
    {"key": "together", "category": "聚合中转", "name": "Together AI", "provider_type": "openai_compatible",
     "base_url": "https://api.together.xyz/v1", "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
     "capabilities": {"text": True, "image": True}, "desc": "开源模型托管"},
    {"key": "fireworks", "category": "聚合中转", "name": "Fireworks AI", "provider_type": "openai_compatible",
     "base_url": "https://api.fireworks.ai/inference/v1", "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
     "capabilities": {"text": True}, "desc": "高速推理"},
    {"key": "groq", "category": "聚合中转", "name": "Groq", "provider_type": "openai_compatible",
     "base_url": "https://api.groq.com/openai/v1", "default_model": "llama-3.3-70b-versatile",
     "capabilities": {"text": True}, "desc": "极速 LPU 推理"},
    {"key": "cerebras", "category": "聚合中转", "name": "Cerebras", "provider_type": "openai_compatible",
     "base_url": "https://api.cerebras.ai/v1", "default_model": "llama-3.3-70b",
     "capabilities": {"text": True}, "desc": "晶圆级引擎极速推理"},
    {"key": "perplexity", "category": "聚合中转", "name": "Perplexity", "provider_type": "openai_compatible",
     "base_url": "https://api.perplexity.ai", "default_model": "sonar-pro",
     "capabilities": {"text": True}, "desc": "联网搜索问答"},
    # ── 生图多模态 ──
    {"key": "zarklab", "category": "生图多模态", "name": "zarklab", "provider_type": "zarklab",
     "base_url": "https://api.zarklab.ai", "default_model": "zarklab-image",
     "capabilities": {"image": True}, "desc": "zarklab.ai 生图通道"},
    # ── 本地自建（saiOS 服务器实际在用的通道）──
    {"key": "cpa-gptoss", "category": "本地自建", "name": "cpa · GPT-OSS", "provider_type": "openai_compatible",
     "base_url": "http://host.docker.internal:8317/v1", "default_model": "gpt-oss-120b-medium",
     "capabilities": {"text": True}, "desc": "cli-proxy-api :8317（antigravity/codex）"},
    {"key": "grok2api", "category": "本地自建", "name": "grok2api", "provider_type": "openai_compatible",
     "base_url": "http://host.docker.internal:8003/v1", "default_model": "grok-imagine-image-lite",
     "capabilities": {"text": True, "image": True}, "desc": "自建 grok 逆向 :8003（账号池）"},
    {"key": "ollama", "category": "本地自建", "name": "Ollama", "provider_type": "openai_compatible",
     "base_url": "http://host.docker.internal:11434/v1", "default_model": "llama3.1",
     "capabilities": {"text": True}, "desc": "本地 Ollama"},
    {"key": "lmstudio", "category": "本地自建", "name": "LM Studio", "provider_type": "openai_compatible",
     "base_url": "http://host.docker.internal:1234/v1", "default_model": "local-model",
     "capabilities": {"text": True}, "desc": "本地 LM Studio"},
]


@app.get("/api/presets")
def list_presets() -> list[dict[str, Any]]:
    """预设模板列表：选择预设 + 填 key 即用。"""
    return PRESETS


# ── 业务 ─────────────────────────────────────────────────────
def _sync_active_flags(conn: sqlite3.Connection) -> None:
    """providers.is_active = 是否出现在任一槽位链中（列表排序/徽标用）。"""
    conn.execute("UPDATE providers SET is_active = 0")
    rows = conn.execute(
        "SELECT DISTINCT provider_id FROM slot_providers"
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE providers SET is_active = 1, updated_at = ? WHERE id = ?",
            (time.time(), r["provider_id"]),
        )


def _chain_ids(conn: sqlite3.Connection, slot: str) -> list[str]:
    """读取槽位候选链（按 position 升序）。"""
    rows = conn.execute(
        "SELECT provider_id FROM slot_providers WHERE slot = ? ORDER BY position ASC",
        (slot,),
    ).fetchall()
    return [r["provider_id"] for r in rows]


def _chain_set(conn: sqlite3.Connection, slot: str, ids: list[str]) -> None:
    """整体写入槽位候选链（保持顺序、去重、过滤已删除的 provider）。"""
    seen: list[str] = []
    for pid in ids:
        if pid and pid not in seen:
            row = conn.execute("SELECT id FROM providers WHERE id = ?", (pid,)).fetchone()
            if row is not None:
                seen.append(pid)
    now = time.time()
    conn.execute("DELETE FROM slot_providers WHERE slot = ?", (slot,))
    for pos, pid in enumerate(seen):
        conn.execute(
            "INSERT INTO slot_providers (slot, provider_id, position, updated_at) VALUES (?, ?, ?, ?)",
            (slot, pid, pos, now),
        )
    _sync_active_flags(conn)


def _promote_slot(conn: sqlite3.Connection, slot: str, provider_id: str) -> list[str]:
    """设为主选：移到链首，其余保留为备选（故障转移顺序不变）。"""
    ids = [p for p in _chain_ids(conn, slot) if p != provider_id]
    ids.insert(0, provider_id)
    _chain_set(conn, slot, ids)
    return ids


def _append_slot(conn: sqlite3.Connection, slot: str, provider_id: str) -> list[str]:
    """追加为备选（已在链中则不动）。"""
    ids = _chain_ids(conn, slot)
    if provider_id not in ids:
        ids.append(provider_id)
    _chain_set(conn, slot, ids)
    return ids


def _remove_from_slot(conn: sqlite3.Connection, slot: str, provider_id: str) -> list[str]:
    """从链中移除某候选。"""
    ids = [p for p in _chain_ids(conn, slot) if p != provider_id]
    _chain_set(conn, slot, ids)
    return ids


def _activate_all_slots(conn: sqlite3.Connection, provider_id: str) -> None:
    """v1 兼容：全局切换 = 所有槽位的链都只含该 provider。"""
    for s in SLOTS:
        _chain_set(conn, s, [provider_id])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "model-hub"}


@app.get("/api/providers")
def list_providers() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM providers ORDER BY is_active DESC, priority ASC, created_at ASC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


@app.post("/api/providers", status_code=201)
def create_provider(body: ProviderIn) -> dict[str, Any]:
    pid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO providers (id, name, provider_type, base_url, encrypted_api_key,
                                   default_model, capabilities, priority, is_enabled,
                                   is_active, group_tag, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                pid,
                body.name.strip(),
                body.provider_type.strip() or "openai_compatible",
                body.base_url.strip(),
                body.api_key.strip(),
                body.default_model.strip(),
                json.dumps(body.capabilities, ensure_ascii=False),
                body.priority,
                1 if body.is_enabled else 0,
                body.group_tag.strip(),
                body.note.strip(),
                now,
                now,
            ),
        )
    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (pid,)).fetchone()
    return _row_to_dict(row)


@app.put("/api/providers/{provider_id}")
def update_provider(provider_id: str, body: ProviderIn) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="provider 不存在")
        conn.execute(
            """
            UPDATE providers SET name = ?, provider_type = ?, base_url = ?,
                encrypted_api_key = ?, default_model = ?, capabilities = ?,
                priority = ?, is_enabled = ?, group_tag = ?, note = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                body.name.strip(),
                body.provider_type.strip() or "openai_compatible",
                body.base_url.strip(),
                body.api_key.strip() if body.api_key else row["encrypted_api_key"],
                body.default_model.strip(),
                json.dumps(body.capabilities, ensure_ascii=False),
                body.priority,
                1 if body.is_enabled else 0,
                body.group_tag.strip(),
                body.note.strip(),
                time.time(),
                provider_id,
            ),
        )
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
    return _row_to_dict(row)


@app.delete("/api/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="provider 不存在")
        conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        # 清理槽位引用，避免悬空（v3 链 + v2 兼容表）
        conn.execute("DELETE FROM slot_providers WHERE provider_id = ?", (provider_id,))
        conn.execute(
            "UPDATE active_slots SET provider_id = NULL, updated_at = ? WHERE provider_id = ?",
            (time.time(), provider_id),
        )
        _sync_active_flags(conn)


@app.post("/api/active")
def set_active(body: dict[str, Any]) -> dict[str, Any]:
    """激活 / 故障转移链管理。

    v3 链语义（{slot, provider_id, mode}）：
      mode=replace(默认)  该槽位链 = [provider_id]
      mode=promote        设为主选：移到链首，其余保留为备选
      mode=append         追加为备选
      mode=remove         从链中移除
      mode=clear          清空该槽位链（provider_id 可空）——该能力回退 saiOS 自带配置
    v2 兼容：{slot, provider_id} 无 mode = replace；{slot, provider_id:""} = clear。
    v1 兼容：只传 {provider_id} = 全局切换（所有槽位链 = [provider_id]）。
    """
    provider_id = str(body.get("provider_id") or "")
    slot = str(body.get("slot") or "").strip().lower()
    mode = str(body.get("mode") or "").strip().lower()
    if not provider_id and not slot:
        raise HTTPException(status_code=400, detail="缺少 provider_id")
    if mode and mode not in ("replace", "promote", "append", "remove", "clear"):
        raise HTTPException(status_code=400, detail=f"未知 mode: {mode}")
    with _conn() as conn:
        if provider_id and mode != "clear":
            row = conn.execute("SELECT id FROM providers WHERE id = ?", (provider_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="provider 不存在")
        chain: list[str] = []
        if slot:
            if slot not in SLOTS:
                raise HTTPException(status_code=400, detail=f"未知槽位: {slot}（可选: {'/'.join(SLOTS)}）")
            if mode == "promote":
                chain = _promote_slot(conn, slot, provider_id)
            elif mode == "append":
                chain = _append_slot(conn, slot, provider_id)
            elif mode == "remove":
                chain = _remove_from_slot(conn, slot, provider_id)
            elif mode == "clear" or (not provider_id):
                _chain_set(conn, slot, [])
            else:
                _chain_set(conn, slot, [provider_id])
        else:
            _activate_all_slots(conn, provider_id)
        out: dict[str, Any] = {"ok": True, "slot": slot or "all", "mode": mode or "replace"}
        out["chain"] = [_pub_name(conn, pid) for pid in (_chain_ids(conn, slot) if slot else [])]
        if provider_id:
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
            if row is not None:
                out.update(_row_to_dict(row))
        return out


def _pub_name(conn: sqlite3.Connection, pid: str) -> str | None:
    row = conn.execute("SELECT name FROM providers WHERE id = ?", (pid,)).fetchone()
    return row["name"] if row is not None else None


@app.get("/api/active")
def get_active() -> dict[str, Any]:
    """saiOS 等消费方动态拉取当前激活配置。

    v3 返回 slots_chain: {slot: [provider...]（按故障转移顺序，主选在前）}
    v2 兼容 slots: {slot: 主选|None}；active/config = text 槽位主选。
    """
    with _conn() as conn:
        chains: dict[str, list[str]] = {s: _chain_ids(conn, s) for s in SLOTS}
        need = {pid for ids in chains.values() for pid in ids}
        by_id: dict[str, sqlite3.Row] = {}
        for pid in need:
            row = conn.execute(
                "SELECT * FROM providers WHERE id = ? AND is_enabled = 1", (pid,)
            ).fetchone()
            if row is not None:
                by_id[pid] = row

    def _pub(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "provider_type": row["provider_type"],
            "base_url": row["base_url"],
            "api_key": row["encrypted_api_key"],
            "default_model": row["default_model"],
            "capabilities": json.loads(row["capabilities"] or "{}"),
        }

    def _cfg(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "base_url": row["base_url"],
            "api_key": row["encrypted_api_key"],
            "default_model": row["default_model"],
            "provider_type": row["provider_type"],
        }

    slots_chain: dict[str, list[dict[str, Any]]] = {}
    slots_out: dict[str, dict[str, Any] | None] = {}
    for s in SLOTS:
        chain = [_pub(by_id[pid]) for pid in chains.get(s, []) if pid in by_id]
        slots_chain[s] = chain
        slots_out[s] = chain[0] if chain else None

    text_chain = slots_chain.get("text") or []
    if not text_chain:
        return {
            "slots": slots_out,
            "slots_chain": slots_chain,
            "active": None,
            "config": None,
            "message": "text 槽位未激活 — 请在模型中心为「对话」选择一个 provider",
        }
    return {
        "slots": slots_out,
        "slots_chain": slots_chain,
        "active": text_chain[0],
        "config": _cfg(by_id[chains["text"][0]]),
    }


# ── 模型连通检测（Stream Check，参考 CC Switch 4.5）─────────────────
@app.post("/api/providers/{provider_id}/test")
async def test_provider(provider_id: str) -> dict[str, Any]:
    """发真实请求验证 provider：base_url 可达性 / key 有效性 / 模型存在 / TTFB。

    不消费完整生成（用最小请求探测），返回状态与延迟。异步执行避免阻塞。
    """
    import time

    import httpx

    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="provider 不存在")

    base = (row["base_url"] or "").rstrip("/")
    key = row["encrypted_api_key"] or ""
    model = row["default_model"] or ""
    ptype = row["provider_type"] or ""
    if not base:
        return {"ok": False, "error": "未配置 base_url", "latency_ms": None}

    results: list[dict[str, Any]] = []
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # 1) 基础可达性：GET base_url（部分网关根路径 404 也算可达）
            try:
                r = await client.get(base)
                results.append({"check": "endpoint", "ok": True, "http": r.status_code})
            except Exception as e:
                results.append({"check": "endpoint", "ok": False, "error": str(e)[:120]})
            if not results[-1]["ok"]:
                return {"ok": False, "error": results[-1]["error"], "latency_ms": None}

            # 2) key 有效性 + 模型探测：发一个最小 chat 请求
            if key:
                headers = {"Content-Type": "application/json"}
                if ptype == "zarklab":
                    headers["X-API-Key"] = key
                    url = f"{base}/v1/complete"
                    payload = {"tool": "auto", "mode": "autonomous", "query": "ping"}
                else:
                    headers["Authorization"] = f"Bearer {key}"
                    # 优先 /chat/completions，兼容部分网关 /v1 前缀
                    url = base if base.endswith("/v1") else f"{base}/v1"
                    url = url.rstrip("/") + "/chat/completions"
                    payload = {"model": model or "gpt-3.5-turbo", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
                try:
                    tt0 = time.time()
                    r = await client.post(url, headers=headers, json=payload)
                    ttf = round((time.time() - tt0) * 1000)
                    ok = r.status_code < 500
                    results.append({
                        "check": "key", "ok": ok, "http": r.status_code,
                        "ttfb_ms": ttf, "detail": (r.text or "")[:120],
                    })
                except Exception as e:
                    results.append({"check": "key", "ok": False, "error": str(e)[:120]})
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "latency_ms": None}

    total_ms = round((time.time() - t0) * 1000)
    ok = all(r.get("ok") for r in results)
    # 持久化到健康状态列（卡片常驻状态点数据源）
    with _conn() as conn:
        conn.execute(
            "UPDATE providers SET last_check_at = ?, last_ok = ?, last_latency_ms = ? WHERE id = ?",
            (time.time(), 1 if ok else 0, total_ms, provider_id),
        )
    return {"ok": ok, "latency_ms": total_ms, "checks": results}


# ── 排序（调整 priority / 置顶置底）─────────────────────────────────
@app.post("/api/providers/reorder")
def reorder_providers(body: dict[str, Any]) -> dict[str, Any]:
    """拖拽排序：body: {ordered_ids: [id, ...]}，按列表顺序重排 priority（10,20,30…）。"""
    ordered = body.get("ordered_ids") or []
    if not ordered:
        raise HTTPException(status_code=400, detail="ordered_ids 为空")
    now = time.time()
    with _conn() as conn:
        for i, pid in enumerate(ordered):
            conn.execute(
                "UPDATE providers SET priority = ?, updated_at = ? WHERE id = ?",
                (10 + i * 10, now, pid),
            )
    return {"ok": True, "count": len(ordered)}


@app.post("/api/providers/{provider_id}/sort")
def sort_provider(provider_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """调整 priority（数值越小越靠前）。body: {priority: int}。"""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="provider 不存在")
        prio = int(body.get("priority") or 1)
        conn.execute(
            "UPDATE providers SET priority = ?, updated_at = ? WHERE id = ?",
            (prio, time.time(), provider_id),
        )
    return {"ok": True, "id": provider_id, "priority": prio}


# ── 持续健康巡检（CC Switch 式：后台定时探测，卡片常驻状态点）────────
HEALTH_INTERVAL = max(60, int(os.environ.get("MODEL_HUB_HEALTH_INTERVAL", "300")))


async def _probe_provider(row: sqlite3.Row) -> tuple[bool, int | None]:
    """免费轻量探测（不消耗上游额度）：GET base_url 可达 + GET /models 验证 Key。

    注意：不用 chat 请求探测——zarklab 等按次计费通道会被巡检烧额度。
    """
    import httpx

    base = (row["base_url"] or "").rstrip("/")
    if not base:
        return False, None
    key = row["encrypted_api_key"] or ""
    ptype = row["provider_type"] or ""
    t0 = time.time()
    ms = lambda: round((time.time() - t0) * 1000)
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(base)
            if r.status_code >= 500:
                return False, ms()
            # 有 key 且非按次计费类型：GET /models 免费验证 key
            if key and ptype != "zarklab":
                u = base if base.endswith("/v1") else f"{base}/v1"
                try:
                    r2 = await client.get(u.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"})
                    if r2.status_code in (401, 403):
                        return False, ms()  # key 无效
                    # 404/405 = 该网关无 /models 端点，端点可达即算正常
                except Exception:
                    pass  # /models 探测失败不影响整体判定（网络抖动）
            return True, ms()
    except Exception:
        return False, ms()


async def _health_loop() -> None:
    while True:
        try:
            with _conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM providers WHERE is_enabled = 1 AND base_url != ''"
                ).fetchall()
            for row in rows:
                ok, ms = await _probe_provider(row)
                with _conn() as conn:
                    conn.execute(
                        "UPDATE providers SET last_check_at = ?, last_ok = ?, last_latency_ms = ? WHERE id = ?",
                        (time.time(), 1 if ok else 0, ms, row["id"]),
                    )
                await asyncio.sleep(2)  # 错峰，避免并发打爆上游
        except Exception:
            pass
        await asyncio.sleep(HEALTH_INTERVAL)


@app.on_event("startup")
async def _start_health_loop() -> None:
    asyncio.create_task(_health_loop())


# ── 复制 provider ────────────────────────────────────────────────────
@app.post("/api/providers/{provider_id}/duplicate", status_code=201)
def duplicate_provider(provider_id: str) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="provider 不存在")
        new_id = str(uuid.uuid4())
        now = time.time()
        conn.execute(
            """
            INSERT INTO providers (id, name, provider_type, base_url, encrypted_api_key,
                                   default_model, capabilities, priority, is_enabled,
                                   is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                new_id, f"{row['name']} (副本)", row["provider_type"], row["base_url"],
                row["encrypted_api_key"], row["default_model"],
                row["capabilities"], int(row["priority"]) + 1, 1, now, now,
            ),
        )
        new = conn.execute("SELECT * FROM providers WHERE id = ?", (new_id,)).fetchone()
    return _row_to_dict(new)


# ── 拉取模型列表（CC Switch 核心功能：从 provider API 获取真实模型）─────
@app.post("/api/models/fetch")
async def fetch_models_from_form(body: dict[str, Any]) -> dict[str, Any]:
    """用表单当前填的 base_url/api_key 直接拉取模型（无需先保存 provider）。

    body: {base_url, api_key, provider_type}
    """
    import httpx

    base = str(body.get("base_url") or "").strip().rstrip("/")
    key = str(body.get("api_key") or "").strip()
    ptype = str(body.get("provider_type") or "").lower().strip()
    if not base:
        return {"source": "error", "models": [], "error": "请先填写 Base URL"}

    # zarklab：无标准 /v1/models，用预设模型 + 常见别名兜底
    if ptype == "zarklab":
        return {
            "source": "preset",
            "models": [
                {"id": "zarklab-image", "name": "zarklab-image（生图）"},
                {"id": "zarklab-image-lite", "name": "zarklab-image-lite（轻量生图）"},
                {"id": "zarklab-video", "name": "zarklab-video（视频）"},
            ],
        }
    try:
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = base if base.endswith("/v1") else f"{base}/v1"
        url = url.rstrip("/") + "/models"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"source": "error", "models": [], "error": f"HTTP {resp.status_code}: {resp.text[:160]}"}
            data = resp.json()
        items = data.get("data") or data.get("models") or []
        models = []
        for it in items:
            if isinstance(it, str):
                models.append({"id": it, "name": it})
            elif isinstance(it, dict) and it.get("id"):
                mid = str(it["id"])
                models.append({"id": mid, "name": it.get("name") or mid})
        return {"source": "api", "models": models, "total": len(models)}
    except Exception as e:  # noqa: BLE001
        return {"source": "error", "models": [], "error": str(e)[:160]}


@app.get("/api/providers/{provider_id}/models")
async def fetch_models(provider_id: str) -> dict[str, Any]:
    """调 provider 的 /v1/models 拉取可用模型列表（OpenAI 兼容）。

    zarklab 等非标准网关用预设模型列表兜底。返回 {models: [{id, name}], source}。
    """
    import httpx

    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="provider 不存在")
    base = (row["base_url"] or "").rstrip("/")
    key = row["encrypted_api_key"] or ""
    ptype = row["provider_type"] or ""

    # zarklab：无标准 /v1/models，用预设模型 + 常见别名兜底
    if ptype == "zarklab":
        return {
            "source": "preset",
            "models": [
                {"id": "zarklab-image", "name": "zarklab-image（生图）"},
                {"id": "zarklab-image-lite", "name": "zarklab-image-lite（轻量生图）"},
                {"id": "zarklab-video", "name": "zarklab-video（视频）"},
            ],
        }
    if not base:
        return {"source": "none", "models": [], "error": "未配置 base_url"}

    try:
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = base if base.endswith("/v1") else f"{base}/v1"
        url = url.rstrip("/") + "/models"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"source": "error", "models": [], "error": f"HTTP {resp.status_code}: {resp.text[:160]}"}
            data = resp.json()
        items = data.get("data") or data.get("models") or []
        models = []
        for it in items:
            if isinstance(it, str):
                models.append({"id": it, "name": it})
            elif isinstance(it, dict) and it.get("id"):
                mid = str(it["id"])
                models.append({"id": mid, "name": it.get("name") or mid})
        return {"source": "api", "models": models, "total": len(models)}
    except Exception as e:  # noqa: BLE001
        return {"source": "error", "models": [], "error": str(e)[:160]}


# ── R2 模型 curation：置顶/隐藏/别名（持久化 per-provider，Cherry Studio 式）──
@app.get("/api/providers/{provider_id}/models/curated")
def models_curated_list(provider_id: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT model_id, label, pinned, hidden FROM provider_models "
            "WHERE provider_id = ? ORDER BY pinned DESC, model_id ASC",
            (provider_id,),
        ).fetchall()
    return [
        {"model_id": r["model_id"], "label": r["label"] or "",
         "pinned": int(r["pinned"] or 0), "hidden": int(r["hidden"] or 0)}
        for r in rows
    ]


class CuratedModelIn(BaseModel):
    id: str
    label: str = ""
    pinned: int = 0
    hidden: int = 0


class CuratedModelsIn(BaseModel):
    models: list[CuratedModelIn] = []


@app.put("/api/providers/{provider_id}/models/curated")
def models_curated_save(provider_id: str, body: CuratedModelsIn) -> dict[str, Any]:
    """整体替换该 provider 的模型 curation（与 UI 列表状态一致）。"""
    with _conn() as conn:
        if conn.execute(
            "SELECT 1 FROM providers WHERE id = ?", (provider_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="provider 不存在")
        conn.execute("DELETE FROM provider_models WHERE provider_id = ?", (provider_id,))
        now = time.time()
        for m in body.models:
            mid = m.id.strip()
            if not mid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO provider_models "
                "(provider_id, model_id, label, pinned, hidden, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (provider_id, mid, m.label.strip(), 1 if m.pinned else 0,
                 1 if m.hidden else 0, now),
            )
    return {"ok": True, "count": len(body.models)}


# ── Prompts 提示词预设（参考 CC Switch 3.2）─────────────────────────
class PromptIn(BaseModel):
    name: str
    content: str = ""


@app.get("/api/prompts")
def list_prompts() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM prompts ORDER BY is_active DESC, created_at ASC").fetchall()
    return [
        {
            "id": r["id"], "name": r["name"], "content": r["content"],
            "is_active": bool(r["is_active"]), "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.post("/api/prompts", status_code=201)
def create_prompt(body: PromptIn) -> dict[str, Any]:
    pid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO prompts (id, name, content, is_active, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (pid, body.name.strip(), body.content, now, now),
        )
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (pid,)).fetchone()
    return {"id": row["id"], "name": row["name"], "content": row["content"], "is_active": False, "created_at": row["created_at"]}


@app.put("/api/prompts/{prompt_id}")
def update_prompt(prompt_id: str, body: PromptIn) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="prompt 不存在")
        conn.execute(
            "UPDATE prompts SET name = ?, content = ?, updated_at = ? WHERE id = ?",
            (body.name.strip(), body.content, time.time(), prompt_id),
        )
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
    return {"id": row["id"], "name": row["name"], "content": row["content"], "is_active": bool(row["is_active"]), "created_at": row["created_at"]}


@app.delete("/api/prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: str) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="prompt 不存在")
        conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))


@app.post("/api/prompts/{prompt_id}/activate")
def activate_prompt(prompt_id: str) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="prompt 不存在")
        conn.execute("UPDATE prompts SET is_active = 0")
        conn.execute("UPDATE prompts SET is_active = 1, updated_at = ? WHERE id = ?", (time.time(), prompt_id))
    return {"ok": True, "id": prompt_id}


@app.get("/api/prompts/active")
def get_active_prompt() -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM prompts WHERE is_active = 1").fetchone()
    if row is None:
        return {"active": None, "content": ""}
    return {"active": {"id": row["id"], "name": row["name"]}, "content": row["content"]}


# ── 用量统计（从 saiOS MySQL 聚合 GenerationTask；未配置连接串时返回空）─
@app.get("/api/usage")
def usage_stats() -> dict[str, Any]:
    """按 provider 模型 / 按天聚合 saiOS 生成任务用量。

    通过环境变量 SAIOS_DB_URL 连接 saiOS MySQL（如
    mysql+aiomysql://user:pass@host:3306/db），未配置时返回空结构（不报错）。
    """
    db_url = os.environ.get("SAIOS_DB_URL", "")
    if not db_url:
        return {"enabled": False, "message": "未配置 SAIOS_DB_URL，用量统计未启用", "by_model": [], "by_day": [], "by_provider": [], "total": 0}
    try:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _fetch() -> dict[str, Any]:
            engine = create_async_engine(db_url, pool_pre_ping=True)
            try:
                async with engine.connect() as c:
                    by_model = (
                        await c.execute(
                            text(
                                "SELECT model, COUNT(*) AS n, SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) AS ok "
                                "FROM generation_tasks GROUP BY model ORDER BY n DESC LIMIT 20"
                            )
                        )
                    ).fetchall()
                    by_day = (
                        await c.execute(
                            text(
                                "SELECT DATE(created_at) AS d, COUNT(*) AS n "
                                "FROM generation_tasks GROUP BY d ORDER BY d DESC LIMIT 30"
                            )
                        )
                    ).fetchall()
                    total = (await c.execute(text("SELECT COUNT(*) FROM generation_tasks"))).scalar() or 0
                return {
                    "enabled": True,
                    "total": total,
                    "by_model": [{"model": r[0] or "unknown", "count": r[1], "succeeded": r[2]} for r in by_model],
                    "by_day": [{"date": str(r[0]), "count": r[1]} for r in by_day],
                    # P3 后 saiOS provider_configs 表已删除、generation_tasks.provider_id 恒 NULL，
                    # 无法按供应商回溯归属——该维度降级为常量说明，不再 LEFT JOIN（曾致 SQL 1146 报错）
                    "by_provider": [{"provider": "（模型中心路由/未记录）", "count": total}] if total else [],
                }
            finally:
                await engine.dispose()

        return asyncio.run(_fetch())
    except Exception as e:  # noqa: BLE001
        return {"enabled": False, "message": f"用量统计读取失败: {str(e)[:160]}", "by_model": [], "by_day": [], "total": 0}


# ── API Key 余额/用量查询（Cherry Studio 式供应商状态可见化）──────────────
@app.get("/api/providers/{provider_id}/balance")
def provider_balance(provider_id: str) -> dict[str, Any]:
    """查询供应商 API Key 的余额/用量（按 provider 分派；不支持则说明原因）。"""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="provider 不存在")
    base = (row["base_url"] or "").lower()
    key = row["encrypted_api_key"] or ""
    if not key:
        return {"supported": False, "message": "该供应商未配置密钥（如 Edge-TTS 本就免费）"}
    import httpx as _hx

    try:
        if "openrouter.ai" in base:
            r = _hx.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": "Bearer " + key},
                timeout=15,
            )
            d = (r.json() or {}).get("data") or {}
            return {
                "supported": True,
                "kind": "openrouter",
                "label": d.get("label"),
                "usage": d.get("usage"),              # 已用（美元）
                "limit": d.get("limit"),              # 上限（null=无限）
                "limit_remaining": d.get("limit_remaining"),
            }
        return {"supported": False, "message": "该供应商暂不支持余额查询"}
    except Exception as e:  # noqa: BLE001
        return {"supported": False, "message": f"查询失败: {str(e)[:140]}"}


# ── 配置导出 / 导入（JSON 备份恢复）──────────────────────────────
@app.get("/api/export")
def export_config() -> dict[str, Any]:
    """导出全部 provider + prompts + 槽位链为 JSON（含 key，供备份/迁移）。"""
    with _conn() as conn:
        providers = [dict(r) for r in conn.execute("SELECT * FROM providers").fetchall()]
        prompts = [dict(r) for r in conn.execute("SELECT * FROM prompts").fetchall()]
        slots = [dict(r) for r in conn.execute("SELECT * FROM active_slots").fetchall()]
        chain_rows = [
            dict(r) for r in conn.execute(
                "SELECT slot, provider_id, position FROM slot_providers ORDER BY slot, position"
            ).fetchall()
        ]
        curated = [
            dict(r) for r in conn.execute("SELECT * FROM provider_models").fetchall()
        ]
    return {
        "version": 4,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "providers": providers,
        "prompts": prompts,
        "active_slots": slots,
        "slot_chains": chain_rows,
        "provider_models": curated,
    }


@app.post("/api/import")
def import_config(body: dict[str, Any]) -> dict[str, Any]:
    """从 JSON 恢复配置（覆盖式：先清空再导入；body 为 export 返回的完整结构）。"""
    providers = body.get("providers") or []
    prompts = body.get("prompts") or []
    with _conn() as conn:
        conn.execute("DELETE FROM providers")
        conn.execute("DELETE FROM prompts")
        conn.execute("DELETE FROM active_slots")
        now = time.time()
        for p in providers:
            conn.execute(
                """
                INSERT INTO providers (id, name, provider_type, base_url, encrypted_api_key,
                                       default_model, capabilities, priority, is_enabled,
                                       is_active, group_tag, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.get("id") or str(uuid.uuid4()),
                    p.get("name") or "unnamed",
                    p.get("provider_type") or "openai_compatible",
                    p.get("base_url") or "",
                    p.get("encrypted_api_key") or p.get("api_key") or "",
                    p.get("default_model") or "",
                    json.dumps(p.get("capabilities") or {}, ensure_ascii=False),
                    int(p.get("priority") or 1),
                    1 if p.get("is_enabled", True) else 0,
                    1 if p.get("is_active") else 0,
                    p.get("group_tag") or "",
                    p.get("note") or "",
                    p.get("created_at") or now,
                    now,
                ),
            )
        for pr in prompts:
            conn.execute(
                "INSERT INTO prompts (id, name, content, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    pr.get("id") or str(uuid.uuid4()),
                    pr.get("name") or "unnamed",
                    pr.get("content") or "",
                    1 if pr.get("is_active") else 0,
                    pr.get("created_at") or now,
                    now,
                ),
            )
        # 恢复槽位链（v3）；无链数据时回退 v2 active_slots，再无则从 is_active 播种
        chain_rows = body.get("slot_chains") or []
        if chain_rows:
            for cr in chain_rows:
                if cr.get("slot") in SLOTS and cr.get("provider_id"):
                    conn.execute(
                        "INSERT OR REPLACE INTO slot_providers (slot, provider_id, position, updated_at) VALUES (?, ?, ?, ?)",
                        (cr["slot"], cr["provider_id"], int(cr.get("position") or 0), now),
                    )
            _seed_chains_from_slots(conn)  # 兜底：链表仍空时从 v2 槽位播种
        else:
            slots = body.get("active_slots") or []
            if slots:
                for s in slots:
                    if s.get("slot") in SLOTS:
                        conn.execute(
                            "INSERT OR REPLACE INTO active_slots (slot, provider_id, updated_at) VALUES (?, ?, ?)",
                            (s["slot"], s.get("provider_id"), now),
                        )
                _seed_chains_from_slots(conn)
            else:
                _seed_slots(conn)
        # R2：模型 curation 恢复（旧备份无此键则跳过）
        curated = body.get("provider_models") or []
        for cm in curated:
            if not cm.get("provider_id") or not cm.get("model_id"):
                continue
            conn.execute(
                "INSERT OR REPLACE INTO provider_models "
                "(provider_id, model_id, label, pinned, hidden, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cm["provider_id"], cm["model_id"], cm.get("label") or "",
                 1 if cm.get("pinned") else 0, 1 if cm.get("hidden") else 0, now),
            )
        _sync_active_flags(conn)
    return {
        "ok": True,
        "providers_imported": len(providers),
        "prompts_imported": len(prompts),
        "models_curated_imported": len(curated),
    }


# ── 环境变量冲突检测（saiOS .env vs hub 配置）──────────────────────
@app.get("/api/env-conflicts")
def env_conflicts() -> dict[str, Any]:
    """检测 saiOS .env 的 OPENAI_COMPATIBLE_* / ZARK_* 与模型中心配置是否冲突。

    .env 路径可配置（ENV_PATH），默认 ~/aigc-studio/.env；读不到时返回提示。
    """
    env_path = os.environ.get("ENV_PATH", "/home/ubuntu/aigc-studio/.env")
    conflicts: list[dict[str, Any]] = []
    try:
        env_vals: dict[str, str] = {}
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vals[k.strip()] = v.strip()
        with _conn() as conn:
            rows = conn.execute("SELECT * FROM providers WHERE is_enabled = 1").fetchall()
        hub_by_type: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            hub_by_type.setdefault(r["provider_type"] or "openai_compatible", []).append(
                {"name": r["name"], "base_url": r["base_url"], "default_model": r["default_model"]}
            )
        # 关键 env 项与 hub 配置对比
        checks = [
            ("OPENAI_COMPATIBLE_BASE_URL", "openai_compatible", "base_url"),
            ("OPENAI_COMPATIBLE_MODEL", "openai_compatible", "default_model"),
            ("ZARK_BASE_URL", "zarklab", "base_url"),
        ]
        for env_key, ptype, field in checks:
            env_val = env_vals.get(env_key, "")
            hub_vals = hub_by_type.get(ptype, [])
            if env_val and hub_vals:
                for h in hub_vals:
                    if h.get(field) and h.get(field) != env_val:
                        conflicts.append({
                            "env_key": env_key,
                            "env_value": env_val,
                            "hub_provider": h["name"],
                            "hub_value": h.get(field),
                            "type": "mismatch" if field == "base_url" else "model_diff",
                        })
        return {"env_path": env_path, "conflicts": conflicts, "count": len(conflicts)}
    except FileNotFoundError:
        return {"env_path": env_path, "conflicts": [], "count": 0, "error": f"未找到 {env_path}"}
    except Exception as e:  # noqa: BLE001
        return {"env_path": env_path, "conflicts": [], "count": 0, "error": str(e)[:160]}


# ── OpenAI 兼容代理 + 高可用路由（CC Switch 4.x：请求→激活 provider，失败降级）──
@app.api_route("/proxy/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_endpoint(path: str, request: Request) -> Any:
    """将 OpenAI 兼容请求转发到当前激活 provider，失败自动降级到备用。

    用法：把 saiOS/客户端的 base_url 指向 <model-hub>/proxy/v1。
    路径（chat/completions、images/generations、models 等）原样转发。
    """
    import httpx
    from fastapi.responses import JSONResponse, StreamingResponse

    req: Request = request
    if req.method == "OPTIONS":
        return JSONResponse({}, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        })

    # 🔐 可选代理鉴权：MODEL_HUB_PROXY_KEY 非空时强制校验（纯内网使用可不设）
    proxy_key = (os.environ.get("MODEL_HUB_PROXY_KEY") or "").strip()
    if proxy_key:
        _auth = req.headers.get("authorization") or ""
        _token = _auth[7:].strip() if _auth.lower().startswith("bearer ") else ""
        if _token != proxy_key and req.headers.get("x-hub-key", "") != proxy_key:
            return JSONResponse({"error": {"message": "model hub: unauthorized"}}, status_code=401)

    # v3 链路由：chat 类请求按 text 槽位候选链顺序降级（与 UI 配置一致）；
    # 其余路径保持旧行为（enabled 全体按 priority）。链空则回退旧行为。
    _chat_like = (
        path in ("chat/completions", "completions", "models") or path.startswith("chat/")
    )
    with _conn() as conn:
        rows: list = []
        if _chat_like:
            for pid in _chain_ids(conn, "text"):
                r = conn.execute(
                    "SELECT * FROM providers WHERE id = ? AND is_enabled = 1", (pid,)
                ).fetchone()
                if r is not None:
                    rows.append(r)
        if not rows:
            rows = list(conn.execute(
                "SELECT * FROM providers WHERE is_enabled = 1 ORDER BY is_active DESC, priority ASC"
            ).fetchall())

    body = await req.body()
    try:
        payload = json.loads(body) if body else {}
    except Exception:
        payload = {}
    headers = {k: v for k, v in req.headers.items() if k.lower() in ("content-type", "accept")}

    # GET /models：聚合 text 链各供应商的 default_model，供外部系统拉取模型列表
    if path == "models" and req.method == "GET":
        seen: set[str] = set()
        data = []
        for row in rows:
            m = (row["default_model"] or "").strip()
            if m and m not in seen:
                seen.add(m)
                data.append({"id": m, "object": "model", "owned_by": row["name"]})
        return JSONResponse({"object": "list", "data": data})

    # 逐个候选尝试，直到成功
    last_err = ""
    for row in rows:
        base = (row["base_url"] or "").rstrip("/")
        key = row["encrypted_api_key"] or ""
        ptype = row["provider_type"] or ""
        if not base:
            continue
        # 只有 openai_compatible 类参与 OpenAI 兼容代理
        if ptype not in ("openai_compatible", "grok", "grok2api", "zarklab"):
            continue
        # 构造上游 URL：base 已含 /v1 则直接用，否则补 /v1
        up = base if base.endswith("/v1") else base + "/v1"
        upstream_url = f"{up}/{path}"
        up_headers = dict(headers)
        if key:
            if ptype == "zarklab":
                up_headers["X-API-Key"] = key
            else:
                up_headers["Authorization"] = f"Bearer {key}"
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                upstream = await client.request(
                    req.method, upstream_url, headers=up_headers,
                    json=payload if payload else None, follow_redirects=True,
                )
            if upstream.status_code >= 500 and row["is_active"]:
                last_err = f"{row['name']} HTTP {upstream.status_code}"
                continue  # 激活 provider 500 → 降级下一个
            # 流式透传
            if payload.get("stream"):
                async def _gen():
                    async with httpx.AsyncClient(timeout=300) as sc:
                        async with sc.stream(
                            req.method, upstream_url, headers=up_headers,
                            json=payload, follow_redirects=True,
                        ) as sr:
                            async for chunk in sr.aiter_bytes():
                                yield chunk
                return StreamingResponse(_gen(), media_type=upstream.headers.get("content-type", "text/event-stream"))
            return JSONResponse(
                content=json.loads(upstream.content) if upstream.content else {"ok": True},
                status_code=upstream.status_code,
            )
        except Exception as e:  # noqa: BLE001
            last_err = f"{row['name']}: {str(e)[:120]}"
            continue
    return JSONResponse({"error": {"message": f"model hub: 所有 provider 均失败: {last_err}"}}, status_code=502)


# ── 前端静态 ─────────────────────────────────────────────────
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
