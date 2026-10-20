"""Presentation models of the dashboards (spec §7) — versioned, independent of the HTML.

The Core fills these models from the canonical records; templates only print them. Every entity
carries its canonical ID and a `source` (path + record id) so the HTML stays traceable. Values that
are not recorded stay `None` and are shown as "Não informado" — never estimated.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class View(str, Enum):
    OVERVIEW = "overview"
    TASKS = "tasks"
    PROJECTS = "projects"
    PROJECT_DETAIL = "project-detail"
    PEOPLE = "people"
    PERSON_DETAIL = "person-detail"
    AGENDA = "agenda"
    ARCHITECTURE = "architecture"
    KNOWLEDGE = "knowledge"
    ATTENTION = "attention"


VIEW_TITLES: dict[View, str] = {
    View.OVERVIEW: "Visão geral",
    View.TASKS: "Tarefas e pendências",
    View.PROJECTS: "Projetos",
    View.PROJECT_DETAIL: "Projeto",
    View.PEOPLE: "Pessoas e responsabilidades",
    View.PERSON_DETAIL: "Pessoa",
    View.AGENDA: "Agenda",
    View.ARCHITECTURE: "Arquitetura e decisões",
    View.KNOWLEDGE: "Conhecimento e domínios",
    View.ATTENTION: "O que precisa de atenção",
}

VIEW_DESCRIPTIONS: dict[View, str] = {
    View.OVERVIEW: "Indicadores, itens de atenção, projetos, pendências, agenda e atividade recente.",
    View.TASKS: "Tabela de tarefas com filtros, ordenação e agrupamento por responsável.",
    View.PROJECTS: "Projetos por status, responsáveis, bloqueios, riscos e percentual de tarefas concluídas.",
    View.PROJECT_DETAIL: "Um projeto: objetivo, responsáveis atuais e anteriores, tarefas, riscos, decisões, agenda.",
    View.PEOPLE: "Pessoas, times, projetos atuais x anteriores e tarefas por pessoa.",
    View.PERSON_DETAIL: "Uma pessoa: responsabilidades, projetos atuais e anteriores, tarefas e relações.",
    View.AGENDA: "Compromissos de hoje e do período, reuniões, pendências e decisões relacionadas.",
    View.ARCHITECTURE: "Decisões aceitas, propostas e substituídas; integrações, dependências e riscos.",
    View.KNOWLEDGE: "Domínios, sistemas, conceitos, assuntos mais relacionados, lacunas e registros provisórios.",
    View.ATTENTION: "Itens que precisam de atenção, ordenados por pesos configurados, com o motivo de cada um.",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- shared pieces


class SourceRef(_Model):
    path: str
    record_id: str | None = None
    kind: Literal["note", "task", "appointment", "journal", "inbox"] = "note"


class EntityRef(_Model):
    """Reference to another record, resolved by the Core. `missing`: the ID points to nothing."""

    id: str
    title: str | None = None
    type: str | None = None
    path: str | None = None
    missing: bool = False


class Progress(_Model):
    """Share of completed tasks. Explicitly NOT the completion of the project (spec §6.3)."""

    completed: int = 0
    total: int = 0
    percent: int | None = None
    label: str = "Sem dados suficientes para calcular"


class Notice(_Model):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    records: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)


class TaskItem(_Model):
    id: str
    title: str
    description: str | None = None
    status: str
    status_label: str
    priority: str
    priority_label: str
    responsible_ids: list[str] = Field(default_factory=list)
    responsible_names: list[str] = Field(default_factory=list)
    responsible_label: str = "Não informado"
    responsible_missing: bool = False   # assignee_id points to a person that does not exist
    unassigned: bool = True
    projects: list[EntityRef] = Field(default_factory=list)
    topics: list[EntityRef] = Field(default_factory=list)
    context_label: str = "Não informado"
    due_date: str | None = None
    due_label: str = "Sem prazo"
    overdue: bool = False
    days_overdue: int | None = None
    open: bool = True
    created_at: str
    updated_at: str
    updated_label: str
    completed_at: str | None = None
    source_meeting: EntityRef | None = None
    source: SourceRef


class Membership(_Model):
    target: EntityRef
    role: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    period_label: str = "Período não informado"
    current: bool = True


class PersonItem(_Model):
    id: str
    name: str
    role: str | None = None
    provisional: bool = False
    teams: list[EntityRef] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    current_projects: list[Membership] = Field(default_factory=list)
    past_projects: list[Membership] = Field(default_factory=list)
    current_teams: list[Membership] = Field(default_factory=list)
    past_teams: list[Membership] = Field(default_factory=list)
    open_tasks: int = 0
    overdue_tasks: int = 0
    completed_tasks: int = 0          # all time
    completed_in_period: int = 0
    source: SourceRef


class Blocker(_Model):
    id: str
    description: str
    status: str
    since: str | None = None
    resolved_on: str | None = None
    resolution: str | None = None
    related: list[EntityRef] = Field(default_factory=list)


class Milestone(_Model):
    id: str
    kind: str
    kind_label: str
    title: str
    due_date: str | None = None
    due_label: str = "Sem data"
    status: str
    status_label: str
    overdue: bool = False


class ProjectItem(_Model):
    id: str
    title: str
    description: str | None = None
    status: str
    status_label: str
    owner: str | None = None
    owner_label: str = "Não informado"
    priority: str | None = None
    target_date: str | None = None
    target_label: str = "Não informado"
    open_tasks: int = 0
    overdue_tasks: int = 0
    progress: Progress = Field(default_factory=Progress)
    open_blockers: list[Blocker] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    decisions: list[EntityRef] = Field(default_factory=list)
    next_milestones: list[Milestone] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)   # current participants (names)
    updated_at: str
    updated_label: str
    source: SourceRef


class EventItem(_Model):
    id: str
    title: str
    starts_at: str
    ends_at: str | None = None
    date: str
    date_label: str
    time_label: str
    all_day: bool = False
    status: str
    status_label: str
    location: str | None = None
    participants: list[str] = Field(default_factory=list)
    related: list[EntityRef] = Field(default_factory=list)
    meeting: EntityRef | None = None
    is_meeting: bool = False
    is_today: bool = False
    conflicts: list[str] = Field(default_factory=list)
    related_tasks: list[EntityRef] = Field(default_factory=list)
    related_decisions: list[EntityRef] = Field(default_factory=list)
    source: SourceRef


class DecisionItem(_Model):
    id: str
    title: str
    adr_number: int | None = None
    status: str
    status_label: str
    category: Literal["accepted", "proposed", "superseded", "rejected", "other"]
    decision_date: str | None = None
    decision: str | None = None        # "## Decisão" text, when recorded
    rationale_missing: bool = False
    superseded_by: EntityRef | None = None
    supersedes: list[EntityRef] = Field(default_factory=list)
    related: list[EntityRef] = Field(default_factory=list)
    source: SourceRef


class StatementItem(_Model):
    """One recorded statement taken from a note section (risk, integration, hypothesis…)."""

    text: str
    section: str | None = None
    record: EntityRef
    source: SourceRef


class RelationItem(_Model):
    source_node: EntityRef
    relation: str
    relation_label: str
    target: EntityRef
    current: bool = True


class KnowledgeItem(_Model):
    id: str
    title: str
    type: str
    type_label: str
    status: str | None = None
    description: str | None = None
    entities: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    relation_count: int = 0
    open_gaps: int = 0
    provisional: bool = False
    updated_at: str
    updated_label: str
    source: SourceRef


class GapItem(_Model):
    record: EntityRef
    field: str
    question: str | None = None
    priority: str
    priority_label: str
    status: str
    source: SourceRef


class InboxItem(_Model):
    id: str
    text: str
    recorded_label: str
    question: str | None = None
    source: SourceRef


class AttentionItem(_Model):
    key: str                 # kind:record id (one item per record — reasons are merged)
    kinds: list[str]
    weight: int
    title: str
    record_type: str
    reasons: list[str]
    record: EntityRef
    source: SourceRef


class ActivityItem(_Model):
    at: str
    at_label: str
    operation: str
    operation_label: str
    summary: str | None = None
    target: EntityRef | None = None


class TaskGroup(_Model):
    key: str
    label: str
    person_id: str | None = None
    tasks: list[str] = Field(default_factory=list)   # task IDs (the task table holds the data)


# ---------------------------------------------------------------- view data


class OverviewData(_Model):
    kind: Literal["overview"] = "overview"
    attention: list[AttentionItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    tasks: list[TaskItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    activity: list[ActivityItem] = Field(default_factory=list)
    people: list[PersonItem] = Field(default_factory=list)
    knowledge: list[KnowledgeItem] = Field(default_factory=list)


class TasksData(_Model):
    kind: Literal["tasks"] = "tasks"
    tasks: list[TaskItem] = Field(default_factory=list)
    groups: list[TaskGroup] = Field(default_factory=list)
    group_by: Literal["none", "assignee", "project", "status"] = "none"
    filter_options: dict[str, list[dict[str, str]]] = Field(default_factory=dict)


class ProjectsData(_Model):
    kind: Literal["projects"] = "projects"
    projects: list[ProjectItem] = Field(default_factory=list)


class ProjectDetailData(_Model):
    kind: Literal["project-detail"] = "project-detail"
    project: ProjectItem
    objective: list[str] = Field(default_factory=list)
    responsible_current: list[str] = Field(default_factory=list)
    responsible_divergent: bool = False
    members_current: list[Membership] = Field(default_factory=list)
    members_past: list[Membership] = Field(default_factory=list)
    open_tasks: list[TaskItem] = Field(default_factory=list)
    completed_tasks: list[TaskItem] = Field(default_factory=list)
    resolved_blockers: list[Blocker] = Field(default_factory=list)
    dependencies: list[EntityRef] = Field(default_factory=list)
    dependency_notes: list[str] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    decision_notes: list[str] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    meetings: list[EntityRef] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    activity: list[ActivityItem] = Field(default_factory=list)


class PeopleData(_Model):
    kind: Literal["people"] = "people"
    people: list[PersonItem] = Field(default_factory=list)
    teams: list[KnowledgeItem] = Field(default_factory=list)
    unclear: list[TaskItem] = Field(default_factory=list)   # open tasks without a clearly identified person
    projects_without_owner: list[EntityRef] = Field(default_factory=list)


class PersonDetailData(_Model):
    kind: Literal["person-detail"] = "person-detail"
    person: PersonItem
    open_tasks: list[TaskItem] = Field(default_factory=list)
    completed_tasks: list[TaskItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)


class AgendaData(_Model):
    kind: Literal["agenda"] = "agenda"
    range_label: str
    today: list[EventItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    meetings: list[EventItem] = Field(default_factory=list)
    cancelled: list[EventItem] = Field(default_factory=list)
    include_cancelled: bool = False
    projects: list[EntityRef] = Field(default_factory=list)


class ArchitectureData(_Model):
    kind: Literal["architecture"] = "architecture"
    accepted: list[DecisionItem] = Field(default_factory=list)
    proposed: list[DecisionItem] = Field(default_factory=list)
    superseded: list[DecisionItem] = Field(default_factory=list)
    rejected: list[DecisionItem] = Field(default_factory=list)
    hypotheses: list[StatementItem] = Field(default_factory=list)
    open_questions: list[StatementItem] = Field(default_factory=list)
    integrations: list[StatementItem] = Field(default_factory=list)
    dependencies: list[RelationItem] = Field(default_factory=list)
    risks: list[StatementItem] = Field(default_factory=list)
    problems: list[Blocker] = Field(default_factory=list)


class KnowledgeData(_Model):
    kind: Literal["knowledge"] = "knowledge"
    domains: list[KnowledgeItem] = Field(default_factory=list)
    architecture: list[KnowledgeItem] = Field(default_factory=list)
    others: list[KnowledgeItem] = Field(default_factory=list)
    most_related: list[KnowledgeItem] = Field(default_factory=list)
    recent: list[KnowledgeItem] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)
    provisional: list[KnowledgeItem] = Field(default_factory=list)
    inbox: list[InboxItem] = Field(default_factory=list)


class AttentionData(_Model):
    kind: Literal["attention"] = "attention"
    items: list[AttentionItem] = Field(default_factory=list)
    weights: dict[str, int] = Field(default_factory=dict)


ViewData = Annotated[
    Union[OverviewData, TasksData, ProjectsData, ProjectDetailData, PeopleData, PersonDetailData, AgendaData,
          ArchitectureData, KnowledgeData, AttentionData],
    Field(discriminator="kind"),
]


class Metric(_Model):
    key: str
    label: str
    value: int | None = None          # None = data unavailable ("Sem dados"), never a made-up number
    hint: str | None = None
    tone: Literal["neutral", "good", "warning", "danger"] = "neutral"


class Dashboard(_Model):
    """Envelope of every dashboard (spec §7.1)."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    view: View
    title: str
    subtitle: str | None = None
    generated_at: str
    generated_label: str
    timezone: str
    filters: dict[str, Any] = Field(default_factory=dict)
    filters_label: list[str] = Field(default_factory=list)
    metrics: dict[str, int | None] = Field(default_factory=dict)
    metric_cards: list[Metric] = Field(default_factory=list)
    data: ViewData
    sources: list[SourceRef] = Field(default_factory=list)
    warnings: list[Notice] = Field(default_factory=list)
    records_read: int = 0


class Manifest(_Model):
    """What is needed to regenerate a report (embedded in the HTML and kept in the cache registry)."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    view: View
    options: dict[str, Any] = Field(default_factory=dict)   # build options exactly as requested (IDs resolved)
    output: str
    generated_at: str
