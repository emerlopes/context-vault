"""Dashboard test fixtures (memory built once per session, copied per test)."""

from __future__ import annotations

import pytest

from _dash import populate


@pytest.fixture(scope="session")
def _template(tmp_path_factory):
    """The fixture memory is built once per session (≈30 CLI writes) and copied for each test."""
    import importlib.util
    import os
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("cv_root_conftest", Path(__file__).parents[1] / "conftest.py")
    root = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(root)  # type: ignore[union-attr]
    FIXED_NOW, Cli = root.FIXED_NOW, root.Cli

    base = tmp_path_factory.mktemp("dashboard-template")
    env = {"CONTEXT_VAULT_NOW": FIXED_NOW, "CONTEXT_VAULT_CONFIG": str(base / "user-config.yaml"),
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "test@example.com"}
    saved = {k: os.environ.get(k) for k in [*env, "CONTEXT_VAULT_REPO"]}
    os.environ.update(env)
    os.environ.pop("CONTEXT_VAULT_REPO", None)
    try:
        cli = Cli(base / "memory")
        cli("init")
        ids = populate(cli)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return base / "memory", ids


@pytest.fixture
def mem(cli, _template) -> dict[str, str]:
    import shutil

    shutil.copytree(_template[0], cli.repo, symlinks=True)
    return dict(_template[1])


@pytest.fixture
def vault(mem, cli):
    from context_vault.services.vault import Vault

    return Vault.open(cli.repo)


@pytest.fixture
def snap(vault):
    from context_vault.dashboard.queries import Snapshot

    return Snapshot.load(vault)

