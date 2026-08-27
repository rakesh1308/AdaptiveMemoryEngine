from __future__ import annotations

import pytest

from adaptive_memory_engine.config import Config


def test_config_validates_transport(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSPORT", "invalid")
    with pytest.raises(ValueError, match="TRANSPORT"):
        Config.load(str(tmp_path / "missing.env"))


def test_config_validates_port(monkeypatch, tmp_path):
    monkeypatch.setenv("PORT", "70000")
    with pytest.raises(ValueError, match="between"):
        Config.load(str(tmp_path / "missing.env"))


def test_config_does_not_retain_process_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-retain")
    cfg = Config.load(str(tmp_path / "missing.env"))
    assert cfg.extra == {}


def test_http_allowlists_are_optional(monkeypatch, tmp_path):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    cfg = Config.load(str(tmp_path / "missing.env"))
    assert cfg.allowed_hosts == []
    assert cfg.allowed_origins == []


def test_config_rejects_weak_auth_token(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_TOKEN", "too-short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        Config.load(str(tmp_path / "missing.env"))


def test_database_url_selects_postgres(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/memory")
    cfg = Config.load(str(tmp_path / "missing.env"))
    assert cfg.storage_backend == "postgres"
    assert cfg.database_url == "postgresql://example.invalid/memory"


def test_postgres_requires_database_url(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Config.load(str(tmp_path / "missing.env"))
