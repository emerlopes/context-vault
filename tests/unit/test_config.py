import pytest
import yaml

from context_vault.config import Config, default_config_yaml, load_config, parse_config, resolve_repository
from context_vault.errors import ValidationError


def test_defaults_match_spec():
    cfg = Config()
    assert cfg.memory.timezone == "America/Sao_Paulo"
    assert cfg.behavior.autonomy == "balanced"
    assert cfg.behavior.auto_push is False
    assert cfg.security.allow_destructive_operations is False


def test_default_yaml_roundtrip():
    data = yaml.safe_load(default_config_yaml("~/x"))
    assert parse_config(data).memory.repository == "~/x"


def test_invalid_config_is_rejected():
    with pytest.raises(ValidationError):
        parse_config({"behavior": {"autonomy": "wild"}})
    with pytest.raises(ValidationError):
        parse_config({"unknown": 1})
    with pytest.raises(ValidationError):
        parse_config({"memory": {"timezone": "Mars/Base"}})


def test_auto_push_is_refused():
    with pytest.raises(ValidationError):
        parse_config({"behavior": {"auto_push": True}})


def test_repository_resolution_order(monkeypatch, tmp_path):
    user_cfg = tmp_path / "user-config.yaml"
    user_cfg.write_text(yaml.safe_dump({"memory": {"repository": str(tmp_path / "from-user")}}))
    monkeypatch.setenv("CONTEXT_VAULT_CONFIG", str(user_cfg))
    assert resolve_repository() == (tmp_path / "from-user").resolve()
    monkeypatch.setenv("CONTEXT_VAULT_REPO", str(tmp_path / "from-env"))
    assert resolve_repository() == (tmp_path / "from-env").resolve()
    assert resolve_repository(tmp_path / "explicit") == (tmp_path / "explicit").resolve()


def test_tilde_expansion(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_repository("~/mem") == (tmp_path / "mem").resolve()


def test_load_config_from_repo(tmp_path):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"memory": {"timezone": "UTC"}}))
    cfg = load_config(tmp_path)
    assert cfg.timezone == "UTC"
    assert cfg.memory.repository == str(tmp_path)
