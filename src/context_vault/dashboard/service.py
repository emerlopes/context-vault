"""Dashboard operations: build, refresh, list and open (spec §6, §12, §13).

`build` = snapshot (one read) → filters → view model (Pydantic) → secret redaction → Jinja2 → checks →
atomic write → re-read and validate → success. It never writes canonical records, never commits and
never reports success before the file exists and passed the checks.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..errors import ErrorCode, NotFoundError, ValidationError, VaultError
from ..models.tasks import OPEN_STATUSES, TaskStatus
from ..search.catalog import CatalogEntry
from ..services.context import responsibility, section_items
from ..services.notes import slugify
from ..services.vault import Vault
from ..storage.layout import CACHE_DIR, TASKS_YAML
from . import aggregations as agg
from . import models as m
from .attention import attention_items
from .filters import BuildOptions, Resolved, resolve_options
from .queries import Snapshot, query_events, query_people, query_projects, query_tasks, task_links
from .renderer import MANIFEST_ID, allowed_remote, expected_scripts, render
from .security import check_html, ensure_reports_ignored, redact_tree, resolve_output

REGISTRY = f"{CACHE_DIR}/dashboards/registry.json"
DEFAULT_FILE = {m.View.OVERVIEW: "dashboard.html"}


# ---------------------------------------------------------------- public API


def build(vault: Vault, options: BuildOptions | dict[str, Any], *, include_model: bool = False) -> dict[str, Any]:
    opts = options if isinstance(options, BuildOptions) else _options(options)
    snap = Snapshot.load(vault)
    res = resolve_options(snap, opts)
    target = resolve_output(vault, opts.output, default_filename(res))
    dashboard = build_model(snap, res)
    manifest_opts = _manifest_options(res)
    manifest = m.Manifest(view=opts.view, options=manifest_opts, output=_display_path(vault, target),
                          generated_at=dashboard.generated_at)
    external = vault.config.dashboard.external_assets
    html = render(dashboard, manifest, output=target, repo=vault.repo, external=external)
    problems = check_html(html, expected_scripts=expected_scripts(external), allowed_remote=allowed_remote(external))
    if problems:
        raise VaultError("O HTML gerado não passou na validação; nenhum arquivo foi gravado.",
                         code=ErrorCode.INTERNAL_ERROR, details={"problems": problems, "written": False})
    _write(vault, target, html)
    _register(vault, manifest)
    out: dict[str, Any] = {
        "success": True, "view": opts.view.value, "title": dashboard.title,
        "output_path": _display_path(vault, target), "absolute_path": str(target),
        "uri": target.resolve().as_uri(), "generated_at": dashboard.generated_at, "timezone": dashboard.timezone,
        "records_read": dashboard.records_read, "filters": dashboard.filters, "metrics": dashboard.metrics,
        "warnings": [w.model_dump(mode="json") for w in dashboard.warnings], "bytes": len(html.encode("utf-8")),
        "external_assets": external,
    }
    if include_model:
        out["model"] = dashboard.model_dump(mode="json")
    return out


def refresh(vault: Vault, output: str | None = None, *, include_model: bool = False) -> dict[str, Any]:
    """Regenerate a report with the view and filters it was generated with (current data, new timestamp)."""
    if output:
        target = resolve_output(vault, output, "dashboard.html")
    else:
        entries = list_reports(vault)["reports"]
        existing = [e for e in entries if e["exists"]]
        if not existing:
            raise NotFoundError("Nenhum dashboard gerado anteriormente foi encontrado. Use `dashboard build`.",
                                details={"registry": REGISTRY})
        target = resolve_output(vault, existing[0]["output_path"], "dashboard.html")
    manifest = read_manifest(target, vault)
    options = BuildOptions.model_validate({**manifest.options, "view": manifest.view.value,
                                           "output": _display_path(vault, target)})
    result = build(vault, options, include_model=include_model)
    result["refreshed"] = {"previous_generated_at": manifest.generated_at, "options": manifest.options}
    return result


def read_manifest(target: Path, vault: Vault) -> m.Manifest:
    if not target.is_file():
        raise NotFoundError(f"Dashboard não encontrado: {_display_path(vault, target)}",
                            details={"output_path": _display_path(vault, target)})
    text = target.read_text(encoding="utf-8")
    match = re.search(rf'<script type="application/json" id="{MANIFEST_ID}">(.*?)</script>', text, re.DOTALL)
    if not match:
        cached = _load_registry(vault).get(_display_path(vault, target))
        if cached is None:
            raise ValidationError("O arquivo não é um dashboard do ContextVault (manifesto ausente).",
                                  details={"output_path": _display_path(vault, target)})
        data = cached
    else:
        try:
            data = json.loads(match.group(1))
        except ValueError:
            raise ValidationError("Manifesto do dashboard ilegível.",
                                  details={"output_path": _display_path(vault, target)}) from None
    try:
        return m.Manifest.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError("Manifesto do dashboard inválido.",
                              details={"errors": [e["msg"] for e in exc.errors()]}) from exc


def list_reports(vault: Vault) -> dict[str, Any]:
    registry = _load_registry(vault)
    out = []
    for path, data in registry.items():
        full = vault.repo / path if not Path(path).is_absolute() else Path(path)
        out.append({"output_path": path, "view": data.get("view"), "options": data.get("options", {}),
                    "generated_at": data.get("generated_at"), "exists": full.is_file()})
    out.sort(key=lambda r: r["generated_at"] or "", reverse=True)
    return {"reports": out, "total": len(out),
            "views": [{"view": v.value, "title": m.VIEW_TITLES[v], "description": m.VIEW_DESCRIPTIONS[v]}
                      for v in m.View]}


def open_report(vault: Vault, output: str | None = None) -> dict[str, Any]:
    if output:
        target = resolve_output(vault, output, "dashboard.html")
    else:
        existing = [r for r in list_reports(vault)["reports"] if r["exists"]]
        if not existing:
            raise NotFoundError("Nenhum dashboard gerado foi encontrado. Use `dashboard build`.")
        target = resolve_output(vault, existing[0]["output_path"], "dashboard.html")
    if not target.is_file():
        raise NotFoundError(f"Dashboard não encontrado: {_display_path(vault, target)}",
                            details={"output_path": _display_path(vault, target)})
    uri = target.resolve().as_uri()
    opened = False
    if not os.environ.get("CONTEXT_VAULT_NO_BROWSER"):
        try:
            opened = bool(webbrowser.open(uri))   # the OS default browser, whatever it is
        except webbrowser.Error:
            opened = False
    return {"output_path": _display_path(vault, target), "uri": uri, "opened": opened,
            **({} if opened else {"notice": "Não foi possível abrir o navegador; abra o arquivo manualmente."})}


# ---------------------------------------------------------------- helpers


def _options(data: dict[str, Any]) -> BuildOptions:
    try:
        return BuildOptions.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationError("Parâmetros inválidos para o dashboard.",
                              details={"errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]}
                                                  for e in exc.errors()]}) from exc


def default_filename(res: Resolved) -> str:
    view = res.options.view
    if view in DEFAULT_FILE and not (res.person or res.project or res.topic):
        return DEFAULT_FILE[view]
    parts = ["dashboard", view.value]
    for entry in (res.project, res.person, res.topic):
        if entry is not None:
            parts.append(slugify(entry.title, 40))
    return "-".join(parts) + ".html"


def _manifest_options(res: Resolved) -> dict[str, Any]:
    """Options to replay: entities as canonical IDs (stable across renames), periods as requested
    ("esta semana" stays relative, so a refresh next week shows next week)."""
    opts = res.options.model_dump(mode="json", exclude={"view", "output"})
    for key, entry in (("person", res.person), ("project", res.project), ("topic", res.topic)):
        if entry is not None:
            opts[key] = entry.id
    return {k: v for k, v in opts.items() if v not in (None, [], False, "none")}


def _display_path(vault: Vault, target: Path) -> str:
    try:
        return Path(os.path.realpath(target)).relative_to(Path(os.path.realpath(vault.repo))).as_posix()
    except ValueError:
        return str(target)


def _write(vault: Vault, target: Path, html: str) -> None:
    """Atomic write, then read back and compare. Any OS failure → structured error, nothing reported as
    generated (CV-DASH-015)."""
    try:
        ensure_reports_ignored(vault, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".dashboard-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(html)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        written = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise VaultError(
            f"Não foi possível gravar o dashboard em {_display_path(vault, target)}: {exc.strerror or exc}. "
            "Nenhum arquivo foi gerado.", code=ErrorCode.REPOSITORY_UNAVAILABLE,
            details={"output_path": _display_path(vault, target), "written": False, "os_error": type(exc).__name__,
                     "errno": exc.errno}) from None
    if written != html:
        raise VaultError("O arquivo gravado difere do gerado; não considere o dashboard atualizado.",
                         code=ErrorCode.INTERNAL_ERROR,
                         details={"output_path": _display_path(vault, target), "written": False})


def _load_registry(vault: Vault) -> dict[str, dict[str, Any]]:
    path = vault.repo / REGISTRY
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("reports", {}) if isinstance(data, dict) else {}


def _register(vault: Vault, manifest: m.Manifest) -> None:
    """Derived cache (never a source of truth): lets `refresh`/`open`/`list` find previous reports."""
    registry = _load_registry(vault)
    registry[manifest.output] = manifest.model_dump(mode="json")
    path = vault.repo / REGISTRY
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "reports": registry}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:  # pragma: no cover - the report itself is already written and validated
        pass


# ---------------------------------------------------------------- view models


def build_model(snap: Snapshot, res: Resolved) -> m.Dashboard:
    view = res.options.view
    builder = BUILDERS[view]
    title, subtitle, data, cards, sources = builder(snap, res)
    notices = list(snap.notices)
    metrics = {c.key: c.value for c in cards}
    dashboard = m.Dashboard(
        view=view, title=title, subtitle=subtitle, generated_at=snap.now.isoformat(),
        generated_label=agg.moment_label(snap, snap.now), timezone=snap.vault.timezone, filters=res.filters,
        filters_label=res.labels, metrics=metrics, metric_cards=cards, data=data,
        sources=_dedupe_sources(sources), warnings=notices, records_read=snap.records_read,
    )
    dumped, redacted = redact_tree(dashboard.model_dump(mode="json"))
    if redacted:
        dumped["warnings"].append(m.Notice(
            code="SECRET_REDACTED", severity="warning",
            message=f"{redacted} trecho(s) com aparência de credencial foram ocultados no relatório. Revise os "
                    "registros de origem: o ContextVault não deve guardar segredos.").model_dump(mode="json"))
    return m.Dashboard.model_validate(dumped)


def _dedupe_sources(sources: list[m.SourceRef]) -> list[m.SourceRef]:
    seen: dict[tuple[str, str | None], m.SourceRef] = {}
    for src in sources:
        if src.path:
            seen.setdefault((src.path, src.record_id), src)
    return sorted(seen.values(), key=lambda s: (s.path, s.record_id or ""))


def _card(key: str, label: str, value: int | None, *, hint: str | None = None, alert: bool = False,
          good: bool = False) -> m.Metric:
    tone = "neutral"
    if value:
        tone = "danger" if alert else ("good" if good else "neutral")
    return m.Metric(key=key, label=label, value=value, hint=hint, tone=tone)  # type: ignore[arg-type]


def _scope(snap: Snapshot, res: Resolved) -> set[str] | None:
    """Subject + its direct neighbours (notes) when filtered by project or topic."""
    sid = res.scope_id
    if sid is None:
        return None
    ids = {sid}
    for nb in snap.graph.neighbors(sid):
        if snap.note(nb.other) is not None:
            ids.add(nb.other)
    return ids


def _filtered_tasks(snap: Snapshot, res: Resolved, *, period_is_due: bool = False) -> list:
    opts = res.options
    person = res.person
    tasks = query_tasks(
        snap, status=opts.status or None, responsible_id=person.id if person else None,
        responsible_names=snap.person_names(person.id) if person else None,  # type: ignore[arg-type]
        project_id=res.project.id if res.project else None, topic_id=res.topic.id if res.topic else None,
        due_after=res.period[0] if (period_is_due and res.period) else None,
        due_before=res.period[1] if (period_is_due and res.period) else None,
    )
    if opts.priority:
        tasks = [t for t in tasks if t.priority.value in opts.priority]
    if opts.overdue:
        tasks = [t for t in tasks if agg.overdue(snap, t)]
    if opts.unassigned:
        tasks = [t for t in tasks if not t.assignee_id and not t.assignee_name and t.status in OPEN_STATUSES]
    if opts.no_due:
        tasks = [t for t in tasks if t.due_date is None and t.status in OPEN_STATUSES]
    return tasks


def _filtered_projects(snap: Snapshot, res: Resolved) -> list[CatalogEntry]:
    scope = _scope(snap, res)
    return query_projects(snap, responsible_id=res.person.id if res.person else None, ids=scope)  # type: ignore[arg-type]


def _task_sources(tasks: list) -> list[m.SourceRef]:
    return [m.SourceRef(path=TASKS_YAML, record_id=t.id, kind="task") for t in tasks]


def _task_cards(snap: Snapshot, metrics: dict[str, int | None]) -> list[m.Metric]:
    return [
        _card("open_tasks", "Abertas", metrics["open_tasks"], hint="Inclui em andamento e bloqueadas"),
        _card("in_progress_tasks", "Em andamento", metrics["in_progress_tasks"]),
        _card("blocked_tasks", "Bloqueadas", metrics["blocked_tasks"], alert=True),
        _card("overdue_tasks", "Atrasadas", metrics["overdue_tasks"], alert=True, hint="Abertas com prazo vencido"),
        _card("completed_tasks", "Concluídas", metrics["completed_tasks"], good=True),
        _card("unassigned_tasks", "Sem responsável", metrics["unassigned_tasks"], alert=True),
        _card("no_due_tasks", "Sem prazo", metrics["no_due_tasks"]),
    ]


def _overview(snap: Snapshot, res: Resolved):
    scope = _scope(snap, res)
    tasks = _filtered_tasks(snap, res)
    recent = res.recent(snap)
    upcoming = res.upcoming(snap)
    metrics = agg.task_metrics(snap, tasks, recent)
    projects = agg.sort_projects([agg.project_item(snap, e) for e in _filtered_projects(snap, res)])
    events = [agg.event_item(snap, rel, a) for rel, a in query_events(
        snap, starts_after=upcoming[0], starts_before=upcoming[1],
        project_id=res.scope_id, person_id=res.person.id if res.person else None)]
    events = [e for e in events if e.status != "cancelled"]
    decisions = [e for e in snap.notes_of("architecture_decision") if (e.meta or {}).get("status") == "proposed"
                 and (scope is None or e.id in scope)]
    blockers_open = [b for p in projects for b in p.open_blockers]
    gaps = [g for g in agg.gap_items(snap, relevant_only=True) if scope is None or g.record.id in scope]
    attention = attention_items(snap, scope=scope, person_id=res.person.id if res.person else None)
    task_items = agg.sort_tasks([agg.task_item(snap, t) for t in tasks if t.status in OPEN_STATUSES])
    people = []
    if res.person is None:
        for entry in query_people(snap, active_only=True):
            item = agg.person_item(snap, entry, recent)
            if item.open_tasks or item.current_projects or item.responsibilities:
                people.append(item)
        people.sort(key=lambda p: (-p.open_tasks, p.name.lower()))
    else:
        people = [agg.person_item(snap, res.person, recent)]
    knowledge_entries = [e for e in snap.notes_of("domain", "architecture", "architecture_decision")
                         if scope is None or e.id in scope]
    knowledge = sorted((agg.knowledge_item(snap, e) for e in knowledge_entries), key=lambda k: k.updated_at,
                       reverse=True)[:8]
    activity = agg.activity(snap, recent, ids=scope, limit=15)
    cards = [
        _card("open_tasks", "Tarefas abertas", metrics["open_tasks"]),
        _card("overdue_tasks", "Atrasadas", metrics["overdue_tasks"], alert=True),
        _card("in_progress_tasks", "Em andamento", metrics["in_progress_tasks"]),
        _card("completed_in_period", "Concluídas no período", metrics["completed_in_period"], good=True,
              hint=agg.period_label(*recent)),
        _card("active_projects", "Projetos ativos", sum(1 for p in projects if p.status == "active")),
        _card("blocked_projects", "Projetos bloqueados", sum(1 for p in projects if agg.is_blocked(p)), alert=True),
        _card("upcoming_events", "Próximos compromissos", len(events) if snap.agenda_available else None,
              hint=agg.period_label(*upcoming)),
        _card("pending_decisions", "Decisões pendentes", len(decisions), alert=True),
        _card("open_problems", "Problemas em aberto", len(blockers_open), alert=True, hint="Bloqueios registrados"),
        _card("knowledge_gaps", "Lacunas relevantes", len(gaps), hint="Alta prioridade, em aberto"),
    ]
    data = m.OverviewData(attention=attention[:12], projects=[p for p in projects if p.status not in
                                                              ("completed", "cancelled", "archived")],
                          tasks=task_items[:25], events=events, activity=activity, people=people[:12],
                          knowledge=knowledge)
    sources = [p.source for p in data.projects] + [t.source for t in data.tasks] + [e.source for e in events] \
        + [k.source for k in knowledge] + [p.source for p in data.people] + [a.source for a in data.attention]
    subtitle = _subject_subtitle(res)
    return m.VIEW_TITLES[m.View.OVERVIEW], subtitle, data, cards, sources


def _subject_subtitle(res: Resolved) -> str | None:
    return " · ".join(res.labels) if res.labels else None


def _tasks(snap: Snapshot, res: Resolved):
    tasks = _filtered_tasks(snap, res, period_is_due=True)
    metrics = agg.task_metrics(snap, tasks, res.recent(snap))
    items = agg.sort_tasks([agg.task_item(snap, t) for t in tasks])
    group_by = res.options.group_by
    groups = agg.group_tasks(items, group_by) if group_by != "none" else []

    def options(values: dict[str, str]) -> list[dict[str, str]]:
        return [{"value": k, "label": v} for k, v in sorted(values.items(), key=lambda kv: kv[1].lower())]

    people = {(i.responsible_ids[0] if i.responsible_ids else "name:" + i.responsible_label): i.responsible_label
              for i in items if not i.unassigned and not i.responsible_missing}
    projects = {p.id: p.title or p.id for i in items for p in i.projects}
    data = m.TasksData(tasks=items, groups=groups, group_by=group_by, filter_options={
        "status": [{"value": k, "label": v} for k, v in agg.TASK_STATUS.items() if any(i.status == k for i in items)],
        "responsible": options(people), "project": options(projects),
        "priority": [{"value": k, "label": v} for k, v in agg.PRIORITY.items() if any(i.priority == k for i in items)],
    })
    title = m.VIEW_TITLES[m.View.TASKS]
    if res.options.overdue:
        title = "Tarefas atrasadas"
    return title, _subject_subtitle(res), data, _task_cards(snap, metrics), [i.source for i in items]


def _projects(snap: Snapshot, res: Resolved):
    items = agg.sort_projects([agg.project_item(snap, e) for e in _filtered_projects(snap, res)])
    cards = [
        _card("active_projects", "Ativos", sum(1 for p in items if p.status == "active")),
        _card("blocked_projects", "Bloqueados", sum(1 for p in items if agg.is_blocked(p)), alert=True),
        _card("paused_projects", "Pausados", sum(1 for p in items if p.status == "paused")),
        _card("planned_projects", "Planejados", sum(1 for p in items if p.status == "planned")),
        _card("completed_projects", "Concluídos", sum(1 for p in items if p.status == "completed"), good=True),
        _card("open_blockers", "Bloqueios em aberto", sum(len(p.open_blockers) for p in items), alert=True),
        _card("projects_with_risks", "Com riscos registrados", sum(1 for p in items if p.risks)),
    ]
    return m.VIEW_TITLES[m.View.PROJECTS], _subject_subtitle(res), m.ProjectsData(projects=items), cards, \
        [p.source for p in items]


def _project_detail(snap: Snapshot, res: Resolved):
    entry = res.project
    assert entry is not None
    meta = entry.meta or {}
    item = agg.project_item(snap, entry)
    pid: str = entry.id  # type: ignore[assignment]
    tasks = agg.project_tasks(snap, pid)
    if res.person:
        tasks = [t for t in tasks if t in agg.person_tasks(snap, res.person)]
    task_items = agg.sort_tasks([agg.task_item(snap, t) for t in tasks])
    members: list[m.Membership] = []
    past: list[m.Membership] = []
    for person in snap.notes_of("person"):
        for ms in (person.meta or {}).get("memberships", []):
            if ms.get("kind") == "project" and ms.get("target_id") == pid:
                info = agg.membership_item(snap, ms)
                info.target = snap.ref(person.id)  # type: ignore[arg-type]
                (members if info.current else past).append(info)
    current_ids = {x.target.id for x in members}
    past = [x for x in past if x.target.id not in current_ids]
    resp = responsibility(snap.catalog, snap.graph, entry)
    responsible = list(dict.fromkeys(c["name"] for c in resp["claims"]))
    deps = []
    for nb in snap.graph.neighbors(pid, direction="out", types={"depends_on"}):
        deps.append(snap.ref(nb.other))
    decisions = [agg.decision_item(snap, d) for d in agg.project_decisions(snap, pid)]
    meetings = [snap.ref(nb.other) for nb in snap.graph.neighbors(pid)
                if (snap.note(nb.other) and snap.note(nb.other).type == "meeting")]  # type: ignore[union-attr]
    meetings = sorted({r.id: r for r in meetings}.values(), key=lambda r: r.path or "", reverse=True)
    upcoming_start = res.period[0] if res.period else snap.today
    events = [agg.event_item(snap, rel, a, with_context=False) for rel, a in query_events(
        snap, starts_after=upcoming_start, starts_before=res.period[1] if res.period else None, project_id=pid)]
    events = [e for e in events if e.status == "scheduled"]
    ids = {pid, *(t.id for t in tasks)}
    activity = agg.activity(snap, res.recent(snap) if res.period else (date.min, snap.today), ids=ids, limit=20)
    objective = section_items(entry.body, "Objetivos", "Objetivo", "Visão geral")
    data = m.ProjectDetailData(
        project=item, objective=objective, responsible_current=responsible, responsible_divergent=resp["divergent"],
        members_current=members, members_past=past, open_tasks=[t for t in task_items if t.open],
        completed_tasks=[t for t in task_items if t.status == "completed"],
        resolved_blockers=[agg.blocker_item(snap, b) for b in meta.get("blockers", []) if b.get("status") != "open"],
        dependencies=deps, dependency_notes=section_items(entry.body, "Dependências"), decisions=decisions,
        decision_notes=section_items(entry.body, "Decisões"),
        milestones=[agg.milestone_item(snap, x) for x in sorted(
            meta.get("milestones", []), key=lambda x: (x.get("due_date") is None, x.get("due_date") or ""))],
        meetings=meetings, events=events, history=agg.history_of(entry), activity=activity,
    )
    metrics = agg.task_metrics(snap, tasks, res.recent(snap))
    cards = [
        _card("open_tasks", "Tarefas abertas", metrics["open_tasks"]),
        _card("overdue_tasks", "Atrasadas", metrics["overdue_tasks"], alert=True),
        _card("completed_tasks", "Tarefas concluídas", metrics["completed_tasks"], good=True),
        _card("open_blockers", "Bloqueios em aberto", len(item.open_blockers), alert=True),
        _card("risks", "Riscos registrados", len(item.risks)),
        _card("decisions", "Decisões relacionadas", len(decisions)),
        _card("upcoming_events", "Compromissos futuros", len(events) if snap.agenda_available else None),
    ]
    sources = [item.source, *(t.source for t in task_items), *(e.source for e in events),
               *(d.source for d in decisions)]
    return entry.title, f"Projeto · {item.status_label}", data, cards, sources


def _people(snap: Snapshot, res: Resolved):
    recent = res.recent(snap)
    entries = query_people(snap, project_id=res.project.id if res.project else None)
    if res.person:
        entries = [e for e in entries if e.id == res.person.id]
    people = sorted((agg.person_item(snap, e, recent) for e in entries), key=lambda p: p.name.lower())
    teams = [agg.knowledge_item(snap, e) for e in snap.notes_of("team")]
    unclear = [agg.task_item(snap, t) for t in snap.tasks if t.status in OPEN_STATUSES and (
        not t.assignee_id and t.assignee_name or (t.assignee_id and snap.note(t.assignee_id) is None)
        or (not t.assignee_id and not t.assignee_name))]
    unclear = agg.sort_tasks(unclear)
    without_owner = [snap.ref(e.id) for e in snap.notes_of("project")  # type: ignore[arg-type]
                     if (e.meta or {}).get("status") in ("active", "planned", "blocked")
                     and not (e.meta or {}).get("owner") and not agg.project_people(snap, e.id)[0]]  # type: ignore[arg-type]
    data = m.PeopleData(people=people, teams=teams, unclear=unclear, projects_without_owner=without_owner)
    cards = [
        _card("people", "Pessoas cadastradas", len(people)),
        _card("teams", "Times", len(teams)),
        _card("people_with_open_tasks", "Com tarefas abertas", sum(1 for p in people if p.open_tasks)),
        _card("people_with_overdue", "Com tarefas atrasadas", sum(1 for p in people if p.overdue_tasks), alert=True),
        _card("completed_in_period", "Concluídas no período", sum(p.completed_in_period for p in people), good=True,
              hint=agg.period_label(*recent)),
        _card("unclear", "Sem responsável identificado", len(unclear), alert=True, hint="Tarefas abertas"),
    ]
    return m.VIEW_TITLES[m.View.PEOPLE], _subject_subtitle(res), data, cards, \
        [p.source for p in people] + [t.source for t in teams] + [t.source for t in unclear]


def _person_detail(snap: Snapshot, res: Resolved):
    entry = res.person
    assert entry is not None
    recent = res.recent(snap)
    person = agg.person_item(snap, entry, recent)
    tasks = agg.person_tasks(snap, entry)
    if res.project:
        tasks = [t for t in tasks if res.project.id in task_links(snap, t)]
    items = agg.sort_tasks([agg.task_item(snap, t) for t in tasks])
    relations = []
    for nb in snap.graph.neighbors(entry.id):  # type: ignore[arg-type]
        other = snap.note(nb.other)
        if other is None or other.type in ("project", "team", "meeting"):
            continue  # projects/teams have their own sections (with period); meetings are listed apart
        src, dst = (entry.id, nb.other) if nb.direction == "outgoing" else (nb.other, entry.id)
        relations.append(agg.relation_item(snap, src, nb.edge.type, dst, nb.edge.current))  # type: ignore[arg-type]
    events = [agg.event_item(snap, rel, a) for rel, a in query_events(
        snap, starts_after=snap.today, starts_before=res.upcoming(snap)[1], person_id=entry.id)]  # type: ignore[arg-type]
    history = agg.history_of(entry) + [f"Encerrou participação em {x.target.title or x.target.id} ({x.period_label})"
                                       for x in person.past_projects + person.past_teams]
    data = m.PersonDetailData(person=person, open_tasks=[t for t in items if t.open],
                              completed_tasks=[t for t in items if t.status == "completed"], relations=relations,
                              history=history, events=[e for e in events if e.status == "scheduled"])
    cards = [
        _card("open_tasks", "Tarefas abertas", person.open_tasks),
        _card("overdue_tasks", "Atrasadas", person.overdue_tasks, alert=True),
        _card("completed_tasks", "Concluídas", person.completed_tasks, good=True),
        _card("current_projects", "Projetos atuais", len(person.current_projects)),
        _card("past_projects", "Participações anteriores", len(person.past_projects)),
    ]
    sources = [person.source, *(t.source for t in items), *(e.source for e in data.events)]
    subtitle = " · ".join(x for x in ["Pessoa", person.role or ""] if x)
    return entry.title, subtitle, data, cards, sources


def _agenda(snap: Snapshot, res: Resolved):
    start, end = res.upcoming(snap)
    rows = query_events(snap, starts_after=start, starts_before=end, project_id=res.scope_id,
                        person_id=res.person.id if res.person else None, include_cancelled=True)
    items = [agg.event_item(snap, rel, a, with_context=True) for rel, a in rows]
    active = [e for e in items if e.status != "cancelled"]
    cancelled = [e for e in items if e.status == "cancelled"]
    today_rows = query_events(snap, starts_after=snap.today, starts_before=snap.today, project_id=res.scope_id,
                              person_id=res.person.id if res.person else None)
    today = [agg.event_item(snap, rel, a, with_context=True) for rel, a in today_rows]
    projects: dict[str, m.EntityRef] = {}
    for e in active:
        for ref in e.related:
            if ref.type == "project":
                projects[ref.id] = ref
    data = m.AgendaData(range_label=agg.period_label(start, end), today=today, events=active,
                        meetings=[e for e in active if e.is_meeting],
                        cancelled=cancelled if res.options.include_cancelled else [],
                        include_cancelled=res.options.include_cancelled,
                        projects=sorted(projects.values(), key=lambda r: (r.title or "").lower()))
    available = snap.agenda_available
    cards = [
        _card("today_events", "Hoje", len(today) if available else None),
        _card("period_events", "No período", len(active) if available else None, hint=data.range_label),
        _card("meetings", "Reuniões", len(data.meetings) if available else None),
        _card("conflicts", "Com conflito de horário", sum(1 for e in active if e.conflicts) if available else None,
              alert=True),
        _card("cancelled", "Cancelados no período", len(cancelled) if available else None,
              hint="Não aparecem como ativos"),
    ]
    sources = [e.source for e in active + data.cancelled]
    return m.VIEW_TITLES[m.View.AGENDA], data.range_label + (f" · {_subject_subtitle(res)}" if res.labels else ""), \
        data, cards, sources


def _architecture(snap: Snapshot, res: Resolved):
    scope = _scope(snap, res)
    adrs = [e for e in snap.notes_of("architecture_decision") if scope is None or e.id in scope]
    decisions = sorted((agg.decision_item(snap, e) for e in adrs), key=lambda d: (d.adr_number or 0, d.title.lower()))
    notes = [e for e in snap.notes_of("architecture", "architecture_decision", "domain")
             if scope is None or e.id in scope]
    arch_notes = [e for e in notes if e.type in ("architecture", "architecture_decision")]
    deps = []
    for entry in notes:
        for nb in snap.graph.neighbors(entry.id, direction="out", types={"depends_on"}):  # type: ignore[arg-type]
            deps.append(agg.relation_item(snap, entry.id, "depends_on", nb.other, nb.edge.current))  # type: ignore[arg-type]
    problems = [agg.blocker_item(snap, b) for p in snap.notes_of("project") if scope is None or p.id in scope
                for b in (p.meta or {}).get("blockers", []) if b.get("status") == "open"]
    data = m.ArchitectureData(
        accepted=[d for d in decisions if d.category == "accepted"],
        proposed=[d for d in decisions if d.category == "proposed"],
        superseded=[d for d in decisions if d.category == "superseded"],
        rejected=[d for d in decisions if d.category in ("rejected", "other")],
        hypotheses=agg.statements(snap, notes, unconfirmed_only=True),
        open_questions=agg.statements(snap, notes, "Dúvidas conhecidas", "Dúvidas em aberto", "Problema"),
        integrations=agg.statements(snap, notes, "Integrações", "Contratos"),
        dependencies=deps, risks=agg.statements(snap, arch_notes, "Riscos"), problems=problems,
    )
    cards = [
        _card("accepted_decisions", "Decisões aceitas", len(data.accepted), good=True),
        _card("proposed_decisions", "Propostas (pendentes)", len(data.proposed), alert=True),
        _card("superseded_decisions", "Substituídas", len(data.superseded)),
        _card("hypotheses", "Hipóteses", len(data.hypotheses)),
        _card("integrations", "Integrações", len(data.integrations)),
        _card("dependencies", "Dependências", len(deps)),
        _card("risks", "Riscos arquiteturais", len(data.risks)),
        _card("open_problems", "Problemas em aberto", len(problems), alert=True),
    ]
    sources = [d.source for d in decisions] + [s.source for s in data.hypotheses + data.integrations + data.risks]
    return m.VIEW_TITLES[m.View.ARCHITECTURE], _subject_subtitle(res), data, cards, sources


def _knowledge(snap: Snapshot, res: Resolved):
    from ..services.inbox import load_inbox

    scope = _scope(snap, res)
    entries = [e for e in snap.catalog.valid() if e.type != "meeting" and (scope is None or e.id in scope)]
    items = {e.id: agg.knowledge_item(snap, e) for e in entries}
    by_title = sorted(items.values(), key=lambda k: k.title.lower())
    gaps = [g for g in agg.gap_items(snap) if scope is None or g.record.id in scope]
    try:
        inbox = [e for e in load_inbox(snap.vault) if e.status.value == "pending"] if scope is None else []
    except VaultError:
        inbox = []
    data = m.KnowledgeData(
        domains=[k for k in by_title if k.type == "domain"],
        architecture=[k for k in by_title if k.type in ("architecture", "architecture_decision")],
        others=[k for k in by_title if k.type in ("project", "team")],
        most_related=sorted((k for k in by_title if k.relation_count), key=lambda k: -k.relation_count)[:10],
        recent=sorted(by_title, key=lambda k: k.updated_at, reverse=True)[:10], gaps=gaps,
        provisional=[k for k in by_title if k.provisional],
        inbox=[m.InboxItem(id=e.id, text=e.text, recorded_label=agg.moment_label(snap, e.recorded_at),
                           question=e.pending_question,
                           source=m.SourceRef(path=".context-vault/inbox.md", record_id=e.id, kind="inbox"))
               for e in inbox],
    )
    systems = {s for k in by_title for s in k.systems}
    cards = [
        _card("domains", "Domínios", len(data.domains)),
        _card("systems", "Sistemas e serviços", len(systems)),
        _card("architecture_notes", "Notas de arquitetura", len(data.architecture)),
        _card("integrations", "Integrações", sum(len(k.integrations) for k in by_title)),
        _card("knowledge_gaps", "Lacunas em aberto", len(gaps)),
        _card("provisional", "Registros provisórios", len(data.provisional) + len(data.inbox),
              hint="Pessoas provisórias e capturas na inbox"),
    ]
    sources = [k.source for k in by_title] + [i.source for i in data.inbox]
    return m.VIEW_TITLES[m.View.KNOWLEDGE], _subject_subtitle(res), data, cards, sources


def _attention(snap: Snapshot, res: Resolved):
    items = attention_items(snap, scope=_scope(snap, res), person_id=res.person.id if res.person else None)
    weights = snap.config.attention.model_dump()
    data = m.AttentionData(items=items, weights=weights)

    def count(kind: str) -> int:
        return sum(1 for i in items if kind in i.kinds)

    cards = [
        _card("attention_items", "Itens de atenção", len(items), alert=True),
        _card("overdue_task", "Tarefas atrasadas", count("overdue_task"), alert=True),
        _card("blocked", "Bloqueios", count("blocked_task") + count("blocked_project"), alert=True),
        _card("pending_decision", "Decisões aguardando", count("pending_decision")),
        _card("upcoming_meeting", "Compromissos próximos", count("upcoming_meeting")),
        _card("unassigned_task", "Sem responsável", count("unassigned_task")),
        _card("inconsistency", "Inconsistências", count("inconsistency"), alert=True),
    ]
    return m.VIEW_TITLES[m.View.ATTENTION], _subject_subtitle(res), data, cards, [i.source for i in items]


BUILDERS = {
    m.View.OVERVIEW: _overview, m.View.TASKS: _tasks, m.View.PROJECTS: _projects,
    m.View.PROJECT_DETAIL: _project_detail, m.View.PEOPLE: _people, m.View.PERSON_DETAIL: _person_detail,
    m.View.AGENDA: _agenda, m.View.ARCHITECTURE: _architecture, m.View.KNOWLEDGE: _knowledge,
    m.View.ATTENTION: _attention,
}

__all__ = ["build", "refresh", "list_reports", "open_report", "build_model", "BuildOptions", "TaskStatus"]
