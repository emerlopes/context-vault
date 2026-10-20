from context_vault.git import Git


def test_commit_and_log(tmp_path):
    git = Git(tmp_path)
    assert not git.is_repo()
    git.init()
    assert git.is_repo()
    assert git.commit("empty") is None
    (tmp_path / "a.md").write_text("x")
    short = git.commit("add a")
    assert short and git.is_clean()
    assert git.last_commit().message == "add a"
    assert [c.message for c in git.log("a.md")] == ["add a"]


def test_no_destructive_or_push_api():
    for name in ("push", "reset", "clean", "checkout", "force"):
        assert not hasattr(Git, name)
