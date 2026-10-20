"""Structured queries of the dashboard over the canonical records (spec §8)."""

from datetime import date

from context_vault.dashboard.queries import (overdue, project_people, query_events, query_people, query_projects,
                                             query_tasks)


def _titles(items):
    return sorted(t.title for t in items)


def test_open_tasks_exclude_completed(snap, mem):
    open_ = query_tasks(snap, include_completed=False)
    assert "Mapear meios de pagamento" not in _titles(open_)
    assert len(open_) == 5
    assert len(query_tasks(snap)) == 6


def test_overdue_rules(snap, mem):
    late = [t for t in snap.tasks if overdue(snap, t)]
    # Only the open task with a past due date; the completed one (due 10/10) and tasks without due never count.
    assert _titles(late) == ["Validar integração Orion"]


def test_tasks_by_status_responsible_project_and_due(snap, mem):
    assert _titles(query_tasks(snap, status=["blocked"])) == ["Subir ambiente Atlas"]
    joao = query_tasks(snap, responsible_id=mem["joao"], responsible_names=snap.person_names(mem["joao"]))
    assert _titles(joao) == ["Criar repositório ABC", "Mapear meios de pagamento", "Validar integração Orion"]
    orion = query_tasks(snap, project_id=mem["orion"])
    assert _titles(orion) == ["Mapear meios de pagamento", "Revisar contrato do gateway", "Validar integração Orion"]
    assert _titles(query_tasks(snap, topic_id=mem["domain"])) == ["Documentar fluxo de simulação"]
    week = query_tasks(snap, due_after=date(2026, 10, 19), due_before=date(2026, 10, 25))
    assert _titles(week) == ["Revisar contrato do gateway"]
    assert query_tasks(snap, updated_after=date(2026, 10, 21)) == []


def test_active_projects_and_filters(snap, mem):
    assert sorted(e.title for e in query_projects(snap, status=["active"])) == ["Atlas", "Orion"]
    assert [e.title for e in query_projects(snap, has_blockers=True)] == ["Atlas"]
    assert [e.title for e in query_projects(snap, has_risks=True)] == ["Orion"]
    assert [e.title for e in query_projects(snap, responsible_id=mem["joao"])] == ["Orion"]


def test_current_people_and_historical_participation(snap, mem):
    current, past = project_people(snap, mem["atlas"])
    assert current == [] and past == [mem["joao"]]          # left Atlas: history, not current
    current, _ = project_people(snap, mem["orion"])
    assert mem["joao"] in current
    assert [e.title for e in query_people(snap, project_id=mem["orion"])] == ["João Silva"]
    assert [e.title for e in query_people(snap, project_id=mem["atlas"])] == []
    assert [e.title for e in query_people(snap, team_id=mem["team"])] == ["João Silva"]
    assert sorted(e.title for e in query_people(snap, has_open_tasks=True)) == ["João Silva", "Maria Souza"]


def test_agenda_by_period_and_cancelled(snap, mem):
    today = query_events(snap, starts_after=date(2026, 10, 20), starts_before=date(2026, 10, 20))
    assert [a.title for _, a in today] == ["Reunião de status do Orion"]
    week = query_events(snap, starts_after=date(2026, 10, 20), starts_before=date(2026, 10, 26))
    assert [a.title for _, a in week] == ["Reunião de status do Orion", "Revisão de arquitetura"]
    with_cancelled = query_events(snap, starts_after=date(2026, 10, 20), starts_before=date(2026, 10, 26),
                                  include_cancelled=True)
    assert "Alinhamento Atlas" in [a.title for _, a in with_cancelled]
    assert [a.title for _, a in query_events(snap, project_id=mem["orion"])] == ["Reunião de status do Orion"]
    assert [a.title for _, a in query_events(snap, person_id=mem["joao"])] == ["Reunião de status do Orion"]


def test_current_decisions_and_relationships(snap, mem):
    from context_vault.dashboard.aggregations import decision_item, project_decisions

    decisions = {d.title: decision_item(snap, d) for d in project_decisions(snap, mem["orion"])}
    assert decisions["Integração síncrona ABC-XYZ"].category == "accepted"
    old = decisions["Integração assíncrona ABC-XYZ"]
    assert old.category == "superseded" and old.superseded_by.id == mem["adr_new"]   # never shown as current
    assert decisions["Cache de simulações"].category == "proposed"


def test_snapshot_reads_each_source_once(vault, monkeypatch):
    from context_vault.dashboard import queries
    from context_vault.services import records

    calls = {"tasks": 0, "agenda": 0}
    real_tasks, real_agenda = records.load_tasks, records.load_appointments

    def count_tasks(v):
        calls["tasks"] += 1
        return real_tasks(v)

    def count_agenda(v):
        calls["agenda"] += 1
        return real_agenda(v)

    monkeypatch.setattr(queries, "load_tasks", count_tasks)
    monkeypatch.setattr(queries, "load_appointments", count_agenda)
    monkeypatch.setattr(records, "load_tasks", count_tasks)
    monkeypatch.setattr(records, "load_appointments", count_agenda)
    snap = queries.Snapshot.load(vault)
    assert calls == {"tasks": 1, "agenda": 1}            # graph reuses the loaded records
    assert snap.records_read == len(snap.catalog.valid()) + len(snap.tasks) + len(snap.appointments)
