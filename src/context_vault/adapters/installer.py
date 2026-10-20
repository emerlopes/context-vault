"""Install, inspect, remove and package the canonical skill.

The skill source is `skills/context-vault/` (repository checkout) or the copy bundled in the wheel
(`context_vault/_skill/context-vault/`). Installed copies carry `.context-vault-skill.json` with the
hash of every file written, so updates never overwrite local edits silently and uninstall only
removes what the installer created.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

import yaml

from .. import __version__
from ..errors import ConfirmationRequiredError, NotFoundError, ValidationError
from ..storage.yamlio import atomic_write
from .agents import AGENTS, SKILL_NAME, AgentSpec, home_dir

MANIFEST = ".context-vault-skill.json"
_ZIP_EXTRA = ("INSTALL.md", "install.sh", "install.ps1")


# ---------------------------------------------------------------------------
# Source


@dataclass
class SkillSource:
    root: Path                 # directory containing SKILL.md
    files: dict[str, str]      # relative POSIX path -> sha256
    name: str
    description: str
    origin: str                # "checkout", "package", "directory" or "zip"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _default_source_dir() -> Path:
    checkout = Path(__file__).resolve().parents[3] / "skills" / SKILL_NAME
    if (checkout / "SKILL.md").is_file():
        return checkout
    bundled = Path(__file__).resolve().parents[1] / "_skill" / SKILL_NAME
    if (bundled / "SKILL.md").is_file():
        return bundled
    raise NotFoundError("Skill canônica não encontrada (nem no checkout nem no pacote instalado)",
                        details={"searched": [str(checkout), str(bundled)]})


def parse_skill_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        raise ValidationError("SKILL.md sem frontmatter YAML")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValidationError("Frontmatter de SKILL.md não foi fechado com '---'")
    data = yaml.safe_load(parts[1]) or {}
    if not isinstance(data, dict):
        raise ValidationError("Frontmatter de SKILL.md inválido")
    return data


def check_skill_dir(root: Path) -> tuple[str, str]:
    """Validate the Agent Skills contract: name = folder, lowercase-hyphen ≤ 64, description ≤ 1024."""
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise ValidationError(f"SKILL.md não encontrado em {root}")
    meta = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
    name, description = meta.get("name"), meta.get("description")
    if name != SKILL_NAME:
        raise ValidationError(f"A skill deve se chamar {SKILL_NAME!r} (encontrado: {name!r})")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValidationError("description da skill ausente ou com mais de 1024 caracteres")
    return name, description.strip()


def _collect(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValidationError(f"A skill não pode conter links simbólicos: {rel}")
        if not path.is_file() or rel == MANIFEST or any(p.startswith(".") or p == "__pycache__"
                                                        for p in PurePosixPath(rel).parts):
            continue
        files[rel] = _sha256(path)
    return files


def load_source(root: Path | None = None, origin: str | None = None) -> SkillSource:
    root = root or _default_source_dir()
    if origin is None:
        origin = "package" if "_skill" in root.parts else "checkout"
    name, description = check_skill_dir(root)
    return SkillSource(root=root, files=_collect(root), name=name, description=description, origin=origin)


def _safe_member(name: str) -> PurePosixPath:
    rel = PurePosixPath(name.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or (rel.parts and ":" in rel.parts[0]):
        raise ValidationError(f"Arquivo zip com caminho inseguro: {name!r}")
    return rel


@contextmanager
def open_source(source: str | None) -> Iterator[SkillSource]:
    """Yield the skill from the default location, a directory or a zip built by `package`."""
    if not source:
        yield load_source()
        return
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        root = path if (path / "SKILL.md").is_file() else path / SKILL_NAME
        yield load_source(root, origin="directory")
        return
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise NotFoundError(f"Origem da skill não encontrada (pasta ou .zip): {source}")
    with tempfile.TemporaryDirectory(prefix="context-vault-skill-") as tmp, zipfile.ZipFile(path) as archive:
        base = Path(tmp)
        for info in archive.infolist():
            rel = _safe_member(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValidationError(f"Arquivo zip com link simbólico: {info.filename!r}")
            target = base.joinpath(*rel.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        candidates = [base] + [p for p in base.iterdir() if p.is_dir()] + [base / SKILL_NAME]
        for candidate in candidates:
            if (candidate / "SKILL.md").is_file():
                yield load_source(candidate, origin="zip")
                return
        raise ValidationError("O zip não contém context-vault/SKILL.md")


# ---------------------------------------------------------------------------
# Installed copies


def _read_manifest(dest: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((dest / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _local_changes(dest: Path, manifest: dict[str, Any]) -> list[str]:
    """Managed files edited (or removed) since the installer wrote them."""
    changed = []
    for rel, digest in (manifest.get("files") or {}).items():
        path = dest.joinpath(*_safe_member(rel).parts)
        if not path.is_file() or _sha256(path) != digest:
            changed.append(rel)
    return changed


def _destination(spec: AgentSpec, scope: str, project: Path | None, target: Path | None) -> Path:
    if target is not None:
        root = target
    elif scope == "project":
        root = spec.project_root(project or Path.cwd())
    elif scope == "user":
        root = spec.user_root(home_dir())
    else:
        raise ValidationError("--scope deve ser 'user' ou 'project'")
    return root.expanduser().resolve() / SKILL_NAME if root.name != SKILL_NAME else root.expanduser().resolve()


def discovered_by(dest: Path, project: Path | None) -> list[str]:
    """Agents that scan the skills root containing `dest`."""
    root = dest.parent
    home = home_dir().resolve()
    project = (project or Path.cwd()).resolve()
    agents = []
    for spec in AGENTS.values():
        if spec.name == "agents":
            continue
        roots = [home / r for r in spec.user_roots] + [project / r for r in spec.project_roots]
        if any(root == r.resolve() for r in roots):
            agents.append(spec.name)
    return agents


def _cli_hint() -> dict[str, Any]:
    found = shutil.which("context-vault")
    hint: dict[str, Any] = {"on_path": found is not None, "path": found}
    if not found:
        hint["warning"] = ("A CLI `context-vault` não está no PATH: a skill depende dela. Instale com "
                           "`uv tool install <checkout ou .whl>` ou `pipx install <checkout ou .whl>`.")
    return hint


def install(agents: list[AgentSpec], *, scope: str = "user", project: Path | None = None,
            target: Path | None = None, source: str | None = None, force: bool = False,
            link: bool = False, dry_run: bool = False) -> dict[str, Any]:
    if target is not None and len(agents) > 1:
        raise ValidationError("--target só pode ser usado com um único agente")
    results = []
    with open_source(source) as skill:
        if link and skill.origin == "zip":
            raise ValidationError("--link exige uma pasta de origem (não um .zip)")
        plans = [(spec, _destination(spec, scope, project, target)) for spec in agents]
        # Several agents may share the same root (e.g. codex and agents → ~/.agents/skills).
        seen: dict[Path, dict[str, Any]] = {}
        for spec, dest in plans:
            if dest in seen:
                seen[dest]["agents"].append(spec.name)
                continue
            outcome = _install_one(skill, dest, force=force, link=link, dry_run=dry_run,
                                   agent_names=[spec.name])
            outcome.update(agents=[spec.name], label=spec.label, docs=spec.docs, next_steps=spec.next_steps,
                           discovered_by=discovered_by(dest, project))
            seen[dest] = outcome
            results.append(outcome)
        return {"skill": skill.name, "version": __version__, "source": str(skill.root), "source_kind": skill.origin,
                "scope": "custom" if target else scope, "dry_run": dry_run, "installs": results, "cli": _cli_hint()}


def _install_one(skill: SkillSource, dest: Path, *, force: bool, link: bool, dry_run: bool,
                 agent_names: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"path": str(dest), "mode": "link" if link else "copy"}
    if dest.is_symlink():
        if link and dest.resolve() == skill.root.resolve():
            return {**out, "status": "unchanged"}
        if not force:
            raise ConfirmationRequiredError(
                f"{dest} é um link simbólico para {os.readlink(dest)}; use --force para substituí-lo",
                details={"reasons": ["replace_symlink"], "path": str(dest)})
        if not dry_run:
            dest.unlink()
    elif dest.exists():
        if not dest.is_dir():
            raise ValidationError(f"{dest} existe e não é uma pasta")
        manifest = _read_manifest(dest)
        if manifest is None and any(dest.iterdir()) and not force:
            raise ConfirmationRequiredError(
                f"{dest} já existe e não foi criado pelo ContextVault; use --force para substituir",
                details={"reasons": ["foreign_skill_directory"], "path": str(dest)})
        if manifest is None and force and not dry_run:
            shutil.rmtree(dest)  # foreign folder explicitly replaced
        if manifest is not None:
            changed = _local_changes(dest, manifest)
            if changed and not force:
                raise ConfirmationRequiredError(
                    "A skill instalada tem alterações locais; use --force para sobrescrevê-las",
                    details={"reasons": ["overwrite_modified_skill"], "path": str(dest), "modified": changed})
            if not link and manifest.get("files") == skill.files and not changed:
                return {**out, "status": "unchanged", "files": sorted(skill.files)}
            if link and not dry_run:
                shutil.rmtree(dest)
        elif link and not dry_run and dest.exists():
            shutil.rmtree(dest)

    status = "updated" if dest.exists() or dest.is_symlink() else "installed"
    if dry_run:
        return {**out, "status": {"installed": "would_install", "updated": "would_update"}[status],
                "files": sorted(skill.files)}
    if link:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(skill.root.resolve(), dest, target_is_directory=True)
        return {**out, "status": status, "files": sorted(skill.files)}

    previous = _read_manifest(dest) or {}
    dest.mkdir(parents=True, exist_ok=True)
    for rel in skill.files:
        target_file = dest.joinpath(*PurePosixPath(rel).parts)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = target_file.with_name(f".{target_file.name}.tmp")
        shutil.copyfile(skill.root.joinpath(*PurePosixPath(rel).parts), tmp)
        os.replace(tmp, target_file)
    removed = []
    for rel in previous.get("files") or {}:
        if rel not in skill.files:
            stale = dest.joinpath(*_safe_member(rel).parts)
            if stale.is_file():
                stale.unlink()
                removed.append(rel)
    _prune_empty(dest)
    manifest = {
        "schema_version": 1, "skill": skill.name, "version": __version__,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agents": sorted(set(previous.get("agents") or []) | set(agent_names)),
        "source": skill.origin, "files": skill.files,
    }
    atomic_write(dest / MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {**out, "status": status, "files": sorted(skill.files), "removed": removed}


def _prune_empty(dest: Path) -> None:
    for path in sorted((p for p in dest.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(path.iterdir()):
            path.rmdir()


def uninstall(agents: list[AgentSpec], *, scope: str = "user", project: Path | None = None,
              target: Path | None = None, force: bool = False) -> dict[str, Any]:
    results = []
    done: set[Path] = set()
    for spec in agents:
        dest = _destination(spec, scope, project, target)
        if dest in done:
            continue
        done.add(dest)
        out: dict[str, Any] = {"agent": spec.name, "path": str(dest)}
        if dest.is_symlink():
            dest.unlink()
            results.append({**out, "status": "removed", "mode": "link"})
            continue
        if not dest.exists():
            results.append({**out, "status": "not_installed"})
            continue
        manifest = _read_manifest(dest)
        if manifest is None and not (dest / "SKILL.md").exists():
            # Only files the user kept after a previous uninstall.
            results.append({**out, "status": "not_installed",
                            "kept": sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())})
            continue
        if manifest is None:
            raise ConfirmationRequiredError(
                f"{dest} não foi criado pelo ContextVault; remova manualmente se for o caso",
                details={"reasons": ["foreign_skill_directory"], "path": str(dest)})
        changed = _local_changes(dest, manifest)
        if changed and not force:
            raise ConfirmationRequiredError(
                "A skill instalada tem alterações locais; use --force para removê-las também",
                details={"reasons": ["remove_modified_skill"], "path": str(dest), "modified": changed})
        for rel in manifest.get("files") or {}:
            path = dest.joinpath(*_safe_member(rel).parts)
            if path.is_file():
                path.unlink()
        (dest / MANIFEST).unlink()
        _prune_empty(dest)
        kept = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
        if not kept:
            dest.rmdir()
        results.append({**out, "status": "removed", "kept": kept})
    return {"skill": SKILL_NAME, "uninstalled": results}


def status(agents: list[AgentSpec], *, project: Path | None = None) -> dict[str, Any]:
    """Report, per agent, every discovery location holding the skill and whether it is current."""
    try:
        current = load_source().files
    except NotFoundError:
        current = None
    home = home_dir()
    project = (project or Path.cwd()).resolve()
    report = []
    for spec in agents:
        locations = ([("user", home / r) for r in spec.user_roots]
                     + [("project", project / r) for r in spec.project_roots])
        found = []
        for scope, root in locations:
            dest = root / SKILL_NAME
            if not (dest / "SKILL.md").is_file():
                continue
            entry: dict[str, Any] = {"scope": scope, "path": str(dest), "link": dest.is_symlink()}
            try:
                check_skill_dir(dest)
                entry["valid"] = True
            except ValidationError as exc:
                entry.update(valid=False, problem=exc.message)
            manifest = _read_manifest(dest)
            if dest.is_symlink():
                entry["up_to_date"] = current is not None and _collect(dest) == current
            elif manifest is None:
                entry.update(managed=False, up_to_date=current is not None and _collect(dest) == current)
            else:
                entry.update(managed=True, version=manifest.get("version"),
                             modified=_local_changes(dest, manifest),
                             up_to_date=current is not None and manifest.get("files") == current)
            found.append(entry)
        warnings = []
        if len(found) > 1:
            warnings.append("Mais de uma cópia visível para este agente; mantenha só uma para evitar versões diferentes.")
        if any(not f.get("up_to_date") for f in found):
            warnings.append("Há cópia desatualizada: rode `context-vault install-skill --agent "
                            f"{spec.name}` para atualizar.")
        report.append({"agent": spec.name, "label": spec.label, "installed": bool(found), "locations": found,
                       "scanned": [str(r) for _, r in locations], "warnings": warnings})
    return {"skill": SKILL_NAME, "version": __version__, "agents": report, "cli": _cli_hint()}


# ---------------------------------------------------------------------------
# Packaging (zip to share without a marketplace)


def package(output: Path | None = None, *, skill_only: bool = False, wheel: Path | None = None,
            force: bool = False) -> dict[str, Any]:
    skill = load_source()
    output = (output or Path.cwd() / f"context-vault-skill-{__version__}.zip").expanduser().resolve()
    if output.suffix.lower() != ".zip":
        output = output.with_suffix(".zip")
    if output.exists() and not force:
        raise ConfirmationRequiredError(f"{output} já existe; use --force para sobrescrever",
                                        details={"reasons": ["overwrite_file"], "path": str(output)})
    if wheel is not None:
        wheel = wheel.expanduser().resolve()
        if not wheel.is_file() or wheel.suffix != ".whl":
            raise NotFoundError(f"Wheel não encontrado: {wheel}")
        if skill_only:
            raise ValidationError("--wheel não combina com --skill-only")
    entries: list[str] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in skill.files:
            arc = f"{SKILL_NAME}/{rel}"
            _zip_write(archive, arc, skill.root.joinpath(*PurePosixPath(rel).parts).read_bytes())
            entries.append(arc)
        if not skill_only:
            assets = Path(__file__).resolve().parent / "assets"
            for name in _ZIP_EXTRA:
                data = (assets / name).read_text(encoding="utf-8").replace("{{VERSION}}", __version__)
                _zip_write(archive, name, data.encode("utf-8"), executable=name.endswith(".sh"))
                entries.append(name)
            if wheel is not None:
                _zip_write(archive, f"wheels/{wheel.name}", wheel.read_bytes())
                entries.append(f"wheels/{wheel.name}")
    os.replace(tmp, output)
    return {"path": str(output), "version": __version__, "entries": entries, "skill_only": skill_only,
            "size_bytes": output.stat().st_size}


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes, *, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))  # deterministic archive
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = ((0o755 if executable else 0o644) | stat.S_IFREG) << 16
    archive.writestr(info, data)
