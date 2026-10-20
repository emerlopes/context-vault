"""Configuration loading, validation and repository resolution.

Resolution order for the memory repository:
1. Explicit path (CLI `--repo`).
2. Environment variable `CONTEXT_VAULT_REPO`.
3. User config `~/.config/context-vault/config.yaml` (or `$CONTEXT_VAULT_CONFIG`) -> `memory.repository`.
4. Default `~/context-vault-memory`.

Behavior settings are read from `<repo>/config.yaml`, falling back to the user config, then defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .clock import get_zone
from .errors import ValidationError

DEFAULT_REPOSITORY = "~/context-vault-memory"
CONFIG_FILENAME = "config.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryConfig(_Strict):
    repository: str = DEFAULT_REPOSITORY
    language: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        get_zone(value)
        return value

    @property
    def repository_path(self) -> Path:
        return Path(os.path.expandvars(self.repository)).expanduser()


class BehaviorConfig(_Strict):
    autonomy: Literal["conservative", "balanced", "autonomous"] = "balanced"
    confirm_new_topics: bool = True
    confirm_conflicting_updates: bool = True
    preserve_original_capture: bool = True
    auto_commit: bool = True
    auto_push: bool = False

    @field_validator("auto_push")
    @classmethod
    def _no_push(cls, value: bool) -> bool:
        if value:
            raise ValueError("auto_push não é suportado: o ContextVault nunca faz push automaticamente")
        return value


class SearchConfig(_Strict):
    max_candidates: int = Field(default=5, ge=1, le=100)
    include_meetings: bool = True
    include_journal: bool = True
    include_tasks: bool = True


class AgendaConfig(_Strict):
    default_timezone: str = "America/Sao_Paulo"
    detect_conflicts: bool = True
    confirm_conflicts: bool = False  # true: overlapping appointments need confirmation (not just a warning)

    @field_validator("default_timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        get_zone(value)
        return value


class SecurityConfig(_Strict):
    restrict_to_repository: bool = True
    reject_symlink_escape: bool = True
    allow_destructive_operations: bool = False


class Config(_Strict):
    schema_version: Literal[1] = 1
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    agenda: AgendaConfig = Field(default_factory=AgendaConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @property
    def timezone(self) -> str:
        return self.memory.timezone


def user_config_path() -> Path:
    override = os.environ.get("CONTEXT_VAULT_CONFIG")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "context-vault" / CONFIG_FILENAME


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValidationError(f"YAML inválido em {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"Configuração inválida em {path}: esperado um mapa")
    return data


def parse_config(data: dict[str, Any], source: str = "<config>") -> Config:
    from pydantic import ValidationError as PydanticValidationError

    try:
        return Config.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"Configuração inválida em {source}",
            details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]},
        ) from exc


def load_user_config() -> Config | None:
    path = user_config_path()
    if path.is_file():
        return parse_config(_read_yaml(path), str(path))
    return None


def resolve_repository(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(os.path.expandvars(str(explicit))).expanduser().resolve()
    env = os.environ.get("CONTEXT_VAULT_REPO")
    if env:
        return Path(os.path.expandvars(env)).expanduser().resolve()
    user = load_user_config()
    if user is not None:
        return user.memory.repository_path.resolve()
    return Path(DEFAULT_REPOSITORY).expanduser().resolve()


def load_config(repo: Path) -> Config:
    """Load the effective configuration for `repo`."""
    repo_file = repo / CONFIG_FILENAME
    if repo_file.is_file():
        config = parse_config(_read_yaml(repo_file), str(repo_file))
    else:
        config = load_user_config() or Config()
    # The repository actually in use always wins over what the file says.
    config.memory.repository = str(repo)
    return config


def default_config_yaml(repository: str = DEFAULT_REPOSITORY) -> str:
    data = Config().model_dump(mode="json")
    data["memory"]["repository"] = repository
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
