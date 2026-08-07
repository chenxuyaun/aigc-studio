"""storage_backend 工厂与 choose_write_backend。"""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.storage import choose_write_backend, get_storage, reset_storage_cache
from app.storage.local_provider import LocalStorageProvider


@pytest.fixture(autouse=True)
def _reset():
    reset_storage_cache()
    yield
    reset_storage_cache()


def test_default_is_local(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "STORAGE_R2_WRITE_PERCENT", 0)
    reset_storage_cache()
    assert isinstance(get_storage(), LocalStorageProvider)
    assert isinstance(get_storage("local"), LocalStorageProvider)
    assert choose_write_backend("user-1") == "local"


def test_unknown_backend_fails(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "not-a-backend")
    reset_storage_cache()
    with pytest.raises(ValueError, match="不支持的存储 backend"):
        get_storage()


def test_choose_write_respects_percent_zero(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_R2_WRITE_PERCENT", 0)
    assert choose_write_backend("abc") == "local"


@pytest.mark.asyncio
async def test_local_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    reset_storage_cache()
    store = get_storage("local")
    await store.put("x/y.txt", b"hi", "text/plain")
    assert await store.get("x/y.txt") == b"hi"
    assert await store.delete("x/y.txt") is True
