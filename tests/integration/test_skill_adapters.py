"""Skill contract and agent adapters: install, discovery, update safety, uninstall, zip packaging."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from context_vault import __version__
from context_vault.adapters.installer import MANIFEST, check_skill_dir, parse_skill_frontmatter
from context_vault.cli import app

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "context-vault"
REFERENCES = ["classification", "retrieval", "agenda", "meetings", "tasks", "conventions", "dashboard"]
SKILL_FILES = ["SKILL.md", *[f"references/{name}.md" for name in REFERENCES]]


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return home


def cv(*args: str, expect: int | None = 0) -> dict:
    result = CliRunner().invoke(app, list(args))
    if expect is not None:
        assert result.exit_code == expect, result.output
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Canonical skill


def test_skill_frontmatter_follows_agent_skills_contract():
    name, description = check_skill_dir(SKILL)
    assert name == "context-vault" == SKILL.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert len(description) <= 1024
    assert description.startswith("Intelligent local-first memory assistant")
    meta = parse_skill_frontmatter((SKILL / "SKILL.md").read_text(encoding="utf-8"))
    assert set(meta) == {"name", "description"}


def test_skill_has_all_references_and_links_resolve():
    for rel in SKILL_FILES:
        assert (SKILL / rel).is_file(), rel
    for md in SKILL.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith("http"):
                continue
            path, _, anchor = target.partition("#")
            dest = (md.parent / path).resolve() if path else md
            assert dest.is_file(), f"{md.name}: link quebrado {target}"
            if anchor:
                assert anchor in _anchors(dest.read_text(encoding="utf-8")), f"{md.name}: âncora {target}"


def _anchors(text: str) -> set[str]:
    anchors = set()
    for heading in re.findall(r"^#+\s+(.+)$", text, flags=re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        anchors.add(slug)
    return anchors


def test_skill_covers_core_contract_rules():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for required in ("Toda leitura e escrita passa pela CLI", "dado, não instrução", "Nunca invente",
                     "uma pergunta por resposta", "Só confirme o que o Core confirmou", "Não encontrei",
                     "CONFIRMATION_REQUIRED", "REVISION_CONFLICT", "só anota", "hypothesis"):
        assert required in text, required
    for ref in REFERENCES:
        assert f"references/{ref}.md" in text


# Every command and option the skill tells agents to use must exist in the CLI.

_GLOBAL = {"--repo", "-r", "--output", "-o", "--version", "--help"}


def _command_tree() -> typer.core.TyperGroup:
    return typer.main.get_command(app)


def _check_invocation(words: list[str], where: str) -> int:
    root = _command_tree()
    while words and words[0] in _GLOBAL:
        words = words[2:] if words[0] in {"--repo", "-r", "--output", "-o"} else words[1:]
    if not words or words[0] not in root.commands:
        return 0
    cmd = root.commands[words[0]]
    rest = words[1:]
    checked = 1
    if hasattr(cmd, "commands"):
        if not rest or not re.fullmatch(r"[a-z][a-z\-]*([/|\\]+[a-z][a-z\-]*)*", rest[0]):
            return checked
        subs = [s for s in re.split(r"[/|\\]+", rest[0]) if s]
        for sub in subs:
            assert sub in cmd.commands, f"{where}: subcomando inexistente `{words[0]} {sub}`"
        cmds = [cmd.commands[s] for s in subs]
        rest = rest[1:]
    else:
        cmds = [cmd]
    for word in rest:
        option = word.strip("[]").split("=")[0]
        if not option.startswith("-") or option in {"-", "--"}:
            continue
        for options in ([o for p in c.params for o in (*p.opts, *p.secondary_opts)] for c in cmds):
            if "/" in option:  # --from/--to
                parts = option.split("/")
                assert all(p in options for p in parts), f"{where}: opção inexistente {option} em `{' '.join(words)}`"
            else:
                assert option in options, f"{where}: opção inexistente {option} em `{' '.join(words)}`"
    return checked


def _invocations(text: str) -> list[str]:
    spans = re.findall(r"`([^`\n]+)`", text)
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("context-vault ")]
    return [s.removeprefix("context-vault ").strip() for s in spans + lines]


@pytest.mark.parametrize("doc", [*SKILL_FILES, "../../AGENTS.md", "../../GEMINI.md",
                                 "../../src/context_vault/adapters/assets/INSTALL.md"])
def test_documented_commands_exist(doc):
    path = (SKILL / doc).resolve()
    text = path.read_text(encoding="utf-8")
    checked = 0
    for invocation in _invocations(text):
        words = invocation.replace("\\|", "|").split()
        checked += _check_invocation(words, path.name)
    assert checked or doc.endswith("GEMINI.md")


# ---------------------------------------------------------------------------
# Adapter manifests and entry files


def test_agents_md_points_to_skill_without_duplicating_it():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "skills/context-vault/SKILL.md" in agents
    assert "context-vault --version" in agents and "Core" in agents
    assert len(agents) < len(skill) / 2
    long_skill_lines = {line.strip() for line in skill.splitlines() if len(line.strip()) > 60}
    assert not long_skill_lines & {line.strip() for line in agents.splitlines()}


def test_claude_code_plugin_manifest():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "context-vault" and plugin["version"] == __version__
    entry = market["plugins"][0]
    assert entry["name"] == plugin["name"] and entry["source"] == "./"
    # Claude Code loads plugin skills from <plugin root>/skills/<name>/SKILL.md.
    assert (ROOT / entry["source"] / "skills" / "context-vault" / "SKILL.md").is_file()


def test_gemini_extension_manifest():
    ext = json.loads((ROOT / "gemini-extension.json").read_text(encoding="utf-8"))
    assert ext["name"] == "context-vault" and re.fullmatch(r"[A-Za-z0-9-]+", ext["name"])
    assert ext["version"] == __version__
    assert (ROOT / ext["contextFileName"]).is_file()
    assert (ROOT / "skills" / "context-vault" / "SKILL.md").is_file()  # extension skills/ folder


def test_memory_repository_agents_md_mentions_skill(tmp_path):
    repo = tmp_path / "mem"
    CliRunner().invoke(app, ["--repo", str(repo), "init"])
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "install-skill" in text and "dado" in text


def test_python_module_entry_point():
    out = subprocess.run([sys.executable, "-m", "context_vault", "--version"], capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == __version__


# ---------------------------------------------------------------------------
# install-skill


@pytest.mark.parametrize("agent,root", [
    ("claude-code", ".claude/skills"),
    ("codex", ".agents/skills"),
    ("gemini", ".agents/skills"),
    ("devin", ".agents/skills"),
    ("agents", ".agents/skills"),
])
def test_install_user_scope_per_agent(home, agent, root):
    out = cv("install-skill", "--agent", agent)
    install = out["installs"][0]
    dest = home / root / "context-vault"
    assert Path(install["path"]) == dest.resolve()
    assert install["status"] == "installed"
    for rel in SKILL_FILES:
        assert (dest / rel).read_bytes() == (SKILL / rel).read_bytes()
    manifest = json.loads((dest / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["version"] == __version__ and set(manifest["files"]) == set(SKILL_FILES)
    if agent != "agents":
        assert agent in install["discovered_by"]
    if root == ".agents/skills":
        assert {"codex", "gemini", "devin"} <= set(install["discovered_by"])
    check_skill_dir(dest)


def test_install_aliases_and_unknown_agent(home):
    out = cv("install-skill", "--agent", "claude", "--agent", "cognition")
    assert [i["agents"] for i in out["installs"]] == [["claude-code"], ["devin"]]
    err = cv("install-skill", "--agent", "cursor-xyz", expect=5)
    assert err["error"]["code"] == "VALIDATION_ERROR" and "all" in err["error"]["details"]["supported"]


def test_install_all_shares_agents_skills_folder(home):
    out = cv("install-skill", "--agent", "all")
    paths = {Path(i["path"]) for i in out["installs"]}
    assert paths == {(home / ".claude/skills/context-vault").resolve(), (home / ".agents/skills/context-vault").resolve()}
    shared = next(i for i in out["installs"] if ".agents" in i["path"])
    assert set(shared["agents"]) == {"codex", "gemini", "devin"}
    status = cv("skill", "status")
    by_agent = {a["agent"]: a for a in status["agents"]}
    for name in ("claude-code", "codex", "gemini", "devin"):
        assert by_agent[name]["installed"] and not by_agent[name]["warnings"], by_agent[name]
        assert all(loc["up_to_date"] and loc["valid"] for loc in by_agent[name]["locations"])


def test_reinstall_is_idempotent_and_dry_run_writes_nothing(home):
    dry = cv("install-skill", "--agent", "codex", "--dry-run")
    assert dry["installs"][0]["status"] == "would_install"
    assert not (home / ".agents").exists()
    cv("install-skill", "--agent", "codex")
    again = cv("install-skill", "--agent", "codex")
    assert again["installs"][0]["status"] == "unchanged"


def test_local_edits_are_never_overwritten_silently(home):
    cv("install-skill", "--agent", "claude-code")
    edited = home / ".claude/skills/context-vault/SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nMinha regra local.\n", encoding="utf-8")
    err = cv("install-skill", "--agent", "claude-code", expect=11)
    assert err["error"]["details"]["reasons"] == ["overwrite_modified_skill"]
    assert err["error"]["details"]["modified"] == ["SKILL.md"]
    status = cv("skill", "status", "--agent", "claude-code")
    assert status["agents"][0]["locations"][0]["modified"] == ["SKILL.md"]
    forced = cv("install-skill", "--agent", "claude-code", "--force")
    assert forced["installs"][0]["status"] == "updated"
    assert edited.read_bytes() == (SKILL / "SKILL.md").read_bytes()


def test_foreign_folder_requires_force(home):
    foreign = home / ".agents/skills/context-vault"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("---\nname: context-vault\ndescription: outra\n---\n", encoding="utf-8")
    (foreign / "extra.md").write_text("x", encoding="utf-8")
    err = cv("install-skill", "--agent", "codex", expect=11)
    assert err["error"]["details"]["reasons"] == ["foreign_skill_directory"]
    cv("install-skill", "--agent", "codex", "--force")
    assert not (foreign / "extra.md").exists()
    assert (foreign / MANIFEST).is_file()


def test_project_scope_and_custom_target(home, tmp_path):
    project = tmp_path / "repo-x"
    out = cv("install-skill", "--agent", "devin", "--scope", "project", "--project-dir", str(project))
    assert Path(out["installs"][0]["path"]) == (project / ".agents/skills/context-vault").resolve()
    assert "devin" in out["installs"][0]["discovered_by"] or out["installs"][0]["discovered_by"] == []
    status = cv("skill", "status", "--agent", "devin", "--project-dir", str(project))
    assert [loc["scope"] for loc in status["agents"][0]["locations"]] == ["project"]
    cwd_out = cv("install-skill", "--agent", "claude-code", "--scope", "project")
    assert Path(cwd_out["installs"][0]["path"]) == (Path.cwd() / ".claude/skills/context-vault").resolve()
    custom = tmp_path / "custom-skills"
    out = cv("install-skill", "--agent", "gemini", "--target", str(custom))
    assert Path(out["installs"][0]["path"]) == (custom / "context-vault").resolve()
    err = cv("install-skill", "--agent", "all", "--target", str(custom), expect=5)
    assert err["error"]["code"] == "VALIDATION_ERROR"


def test_update_removes_files_dropped_from_the_skill(home, tmp_path):
    source = tmp_path / "src-skill" / "context-vault"
    shutil.copytree(SKILL, source)
    (source / "references" / "old.md").write_text("antigo\n", encoding="utf-8")
    cv("install-skill", "--agent", "codex", "--source", str(source))
    dest = home / ".agents/skills/context-vault"
    assert (dest / "references/old.md").is_file()
    out = cv("install-skill", "--agent", "codex")
    assert out["installs"][0]["removed"] == ["references/old.md"]
    assert not (dest / "references/old.md").exists()


def test_invalid_source_is_rejected(home, tmp_path):
    bad = tmp_path / "bad" / "context-vault"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("---\nname: outra-coisa\ndescription: x\n---\n", encoding="utf-8")
    err = cv("install-skill", "--agent", "codex", "--source", str(bad), expect=5)
    assert "context-vault" in err["error"]["message"]
    assert cv("install-skill", "--agent", "codex", "--source", str(tmp_path / "nada"), expect=3)


@pytest.mark.skipif(sys.platform == "win32", reason="links simbólicos exigem privilégio no Windows")
def test_link_mode_for_development(home):
    out = cv("install-skill", "--agent", "claude-code", "--link")
    dest = home / ".claude/skills/context-vault"
    assert dest.is_symlink() and dest.resolve() == SKILL.resolve()
    assert cv("install-skill", "--agent", "claude-code", "--link")["installs"][0]["status"] == "unchanged"
    err = cv("install-skill", "--agent", "claude-code", expect=11)
    assert err["error"]["details"]["reasons"] == ["replace_symlink"]
    status = cv("skill", "status", "--agent", "claude-code")
    assert status["agents"][0]["locations"][0]["link"] is True
    removed = cv("skill", "uninstall", "--agent", "claude-code")
    assert removed["uninstalled"][0]["status"] == "removed"
    assert not dest.exists() and SKILL.is_dir()
    assert out["installs"][0]["mode"] == "link"


# ---------------------------------------------------------------------------
# uninstall / status


def test_uninstall_removes_only_managed_files(home):
    cv("install-skill", "--agent", "gemini")
    dest = home / ".agents/skills/context-vault"
    (dest / "minhas-notas.md").write_text("meu arquivo\n", encoding="utf-8")
    out = cv("skill", "uninstall", "--agent", "gemini")
    assert out["uninstalled"][0]["kept"] == ["minhas-notas.md"]
    assert sorted(p.name for p in dest.iterdir()) == ["minhas-notas.md"]
    again = cv("skill", "uninstall", "--agent", "codex")  # same shared folder, already removed
    assert again["uninstalled"][0]["status"] == "not_installed"
    assert again["uninstalled"][0]["kept"] == ["minhas-notas.md"]


def test_uninstall_refuses_modified_or_foreign(home):
    cv("install-skill", "--agent", "claude-code")
    skill_md = home / ".claude/skills/context-vault/SKILL.md"
    skill_md.write_text("editado", encoding="utf-8")
    err = cv("skill", "uninstall", "--agent", "claude-code", expect=11)
    assert err["error"]["details"]["modified"] == ["SKILL.md"]
    cv("skill", "uninstall", "--agent", "claude-code", "--force")
    assert not (home / ".claude/skills/context-vault").exists()
    assert cv("skill", "uninstall", "--agent", "claude-code")["uninstalled"][0]["status"] == "not_installed"


def test_status_warns_about_duplicate_copies(home):
    cv("install-skill", "--agent", "codex")
    cv("install-skill", "--agent", "gemini", "--target", str(home / ".gemini/skills"))
    status = cv("skill", "status", "--agent", "gemini")
    gemini = status["agents"][0]
    assert len(gemini["locations"]) == 2 and gemini["warnings"]
    codex = cv("skill", "status", "--agent", "codex")["agents"][0]
    assert len(codex["locations"]) == 1 and not codex["warnings"]


def test_skill_agents_lists_discovery_locations():
    out = cv("skill", "agents")
    names = {a["name"]: a for a in out["agents"]}
    assert set(names) == {"claude-code", "codex", "gemini", "devin", "agents"}
    assert "~/.claude/skills" in names["claude-code"]["user_roots"]
    assert "~/.agents/skills" in names["gemini"]["user_roots"] and "~/.gemini/skills" in names["gemini"]["user_roots"]
    assert ".devin/skills" in names["devin"]["project_roots"]


# ---------------------------------------------------------------------------
# Zip packaging (local sharing without a marketplace)


def test_package_skill_zip_contents_and_install_from_zip(home, tmp_path):
    out_zip = tmp_path / "dist" / "cv.zip"
    out = cv("package-skill", "--output-file", str(out_zip))
    assert Path(out["path"]) == out_zip.resolve()
    with zipfile.ZipFile(out_zip) as archive:
        names = set(archive.namelist())
        assert {f"context-vault/{rel}" for rel in SKILL_FILES} <= names
        assert {"INSTALL.md", "install.sh", "install.ps1"} <= names
        assert __version__ in archive.read("INSTALL.md").decode("utf-8")
        assert "{{VERSION}}" not in archive.read("install.sh").decode("utf-8")
        assert (archive.getinfo("install.sh").external_attr >> 16) & 0o111
        assert not any(n.endswith(MANIFEST) for n in names)
    assert cv("package-skill", "--output-file", str(out_zip), expect=11)["error"]["details"]["reasons"] == ["overwrite_file"]
    first = out_zip.read_bytes()
    cv("package-skill", "--output-file", str(out_zip), "--force")
    assert out_zip.read_bytes() == first  # deterministic archive

    installed = cv("install-skill", "--agent", "claude-code", "--source", str(out_zip))
    assert installed["source_kind"] == "zip"
    dest = home / ".claude/skills/context-vault"
    for rel in SKILL_FILES:
        assert (dest / rel).read_bytes() == (SKILL / rel).read_bytes()
    assert json.loads((dest / MANIFEST).read_text(encoding="utf-8"))["source"] == "zip"


def test_package_skill_only_and_with_wheel(tmp_path):
    only = cv("package-skill", "-f", str(tmp_path / "only.zip"), "--skill-only")
    with zipfile.ZipFile(only["path"]) as archive:
        assert all(n.startswith("context-vault/") for n in archive.namelist())
    wheel = tmp_path / f"context_vault-{__version__}-py3-none-any.whl"
    wheel.write_bytes(b"PK fake wheel")
    full = cv("package-skill", "-f", str(tmp_path / "full.zip"), "--wheel", str(wheel))
    assert f"wheels/{wheel.name}" in full["entries"]
    assert cv("package-skill", "-f", str(tmp_path / "x.zip"), "--wheel", str(tmp_path / "nao.whl"), expect=3)


def test_zip_with_unsafe_paths_is_rejected(home, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("context-vault/SKILL.md", (SKILL / "SKILL.md").read_text(encoding="utf-8"))
        archive.writestr("../../escape.txt", "x")
    err = cv("install-skill", "--agent", "codex", "--source", str(evil), expect=5)
    assert "inseguro" in err["error"]["message"]
    assert not (tmp_path.parent / "escape.txt").exists()
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("README.md", "nada")
    assert cv("install-skill", "--agent", "codex", "--source", str(empty), expect=5)


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="install.sh requer bash")
def test_install_sh_without_cli_copies_skill(tmp_path):
    out = cv("package-skill", "-f", str(tmp_path / "share.zip"))
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(out["path"]) as archive:
        archive.extractall(unpacked)
    home = tmp_path / "friend-home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}  # no context-vault on PATH
    result = subprocess.run(["bash", str(unpacked / "install.sh"), "all"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "CLI context-vault não foi encontrada" in result.stdout
    for root in (".claude/skills", ".agents/skills"):
        for rel in SKILL_FILES:
            assert (home / root / "context-vault" / rel).read_bytes() == (SKILL / rel).read_bytes()
    again = subprocess.run(["bash", str(unpacked / "install.sh"), "codex"], env=env, capture_output=True, text=True)
    assert again.returncode == 11
    project = tmp_path / "proj"
    proj = subprocess.run(["bash", str(unpacked / "install.sh"), "devin", "--project", str(project)], env=env,
                          capture_output=True, text=True)
    assert proj.returncode == 0, proj.stderr
    assert (project / ".agents/skills/context-vault/SKILL.md").is_file()


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="install.sh requer bash")
def test_install_sh_delegates_to_cli_when_available(tmp_path):
    out = cv("package-skill", "-f", str(tmp_path / "share.zip"))
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(out["path"]) as archive:
        archive.extractall(unpacked)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "context-vault"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m context_vault "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    home = tmp_path / "home2"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:/usr/bin:/bin"}
    result = subprocess.run(["bash", str(unpacked / "install.sh"), "codex"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".agents/skills/context-vault" / MANIFEST).is_file()  # written by the CLI installer
