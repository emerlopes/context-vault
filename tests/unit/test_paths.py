import os

import pytest

from context_vault.errors import PermissionDeniedError
from context_vault.paths import safe_path


def test_accepts_relative_paths(tmp_path):
    assert safe_path(tmp_path, "dominios/a.md") == tmp_path.resolve() / "dominios" / "a.md"


@pytest.mark.parametrize("bad", ["../x.md", "dominios/../../x", "/etc/passwd", "C:\\x", "", ".git/config", "a\\..\\..\\b"])
def test_rejects_external_paths(tmp_path, bad):
    with pytest.raises(PermissionDeniedError):
        safe_path(tmp_path, bad)


def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    os.symlink(outside, repo / "link")
    with pytest.raises(PermissionDeniedError):
        safe_path(repo, "link/secret.md")
    # Allowed when the check is explicitly disabled.
    safe_path(repo, "link/secret.md", reject_symlink_escape=False)


def test_symlink_inside_repo_is_allowed(tmp_path):
    (tmp_path / "real").mkdir()
    os.symlink(tmp_path / "real", tmp_path / "alias")
    safe_path(tmp_path, "alias/x.md")
