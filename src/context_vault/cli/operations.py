"""Operational commands: agenda, meetings, tasks and relative dates."""

from __future__ import annotations

from typing import Any, Optional

import typer

from ..models.agenda import AppointmentStatus
from ..models.notes import MeetingStatus
from ..services import agenda as agenda_service
from ..services import meetings as meetings_service
from ..services import tasks as tasks_service
from ..services.dates import resolve as resolve_date
from ..services.reader import read_record
from .support import open_vault, read_json_input, run


def register(app: typer.Typer) -> None:
    _register_dates(app)
    _register_agenda(app)
    _register_tasks(app)
    _register_meetings(app)


def _register_dates(app: typer.Typer) -> None:
    dates_app = typer.Typer(help="Datas relativas resolvidas pela data atual real, no fuso configurado.",
                            no_args_is_help=True)
    app.add_typer(dates_app, name="dates")

    @dates_app.command("resolve")
    def dates_resolve(expression: list[str] = typer.Argument(..., help="Ex.: amanhã, quinta às 14h, próxima semana.")) -> None:
        """Resolve 'hoje', 'amanhã', 'quinta', 'sexta', 'próxima semana', horários... (ambíguo → ambiguous: true)."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            return resolve_date(" ".join(expression), vault.now(), vault.timezone).to_dict()

        run("dates.resolve", _do)


def _register_agenda(app: typer.Typer) -> None:
    agenda_app = typer.Typer(help="Compromissos (agenda/AAAA/MM.yaml).", no_args_is_help=True)
    app.add_typer(agenda_app, name="agenda")

    @agenda_app.command("add")
    def agenda_add(
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON do compromisso ('-' = stdin)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Só valida (datas, conflitos, duplicatas)."),
    ) -> None:
        """Registra um compromisso. Sem horário exige all_day: true; conflitos geram alerta."""
        run("agenda.add", lambda: agenda_service.add_appointment(open_vault(), read_json_input(input_),
                                                                 dry_run=dry_run))

    @agenda_app.command("list")
    def agenda_list(
        date: Optional[str] = typer.Option(None, "--date", "-d", help="Dia ou período: 2026-10-20, hoje, amanhã, "
                                                                      "quinta, 'esta semana'."),
        from_: Optional[str] = typer.Option(None, "--from", help="Data inicial."),
        to: Optional[str] = typer.Option(None, "--to", help="Data final."),
        at: Optional[str] = typer.Option(None, "--at", help="Horário (ex.: 14h, 'amanhã às 14h')."),
        next_: bool = typer.Option(False, "--next", help="Só o próximo compromisso."),
        query: Optional[str] = typer.Option(None, "--query", "-q", help="Assunto (título, descrição, relacionados)."),
        related: Optional[str] = typer.Option(None, "--related", help="ID/caminho de nota relacionada."),
        status: Optional[list[AppointmentStatus]] = typer.Option(None, "--status", "-s", help="Status (repetível)."),
        all_: bool = typer.Option(False, "--all", help="Inclui cancelados."),
    ) -> None:
        """Consulta a agenda (padrão: de hoje em diante, sem cancelados)."""
        run("agenda.list", lambda: agenda_service.list_appointments(
            open_vault(), day=date, start=from_, end=to, statuses=[s.value for s in status or []] or None,
            include_all=all_, query=query, related=related, at=at, next_only=next_))

    @agenda_app.command("update")
    def agenda_update(input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON {id, ...}.")) -> None:
        """Reagenda ou altera título, descrição, participantes, local, relacionados (histórico preservado)."""
        run("agenda.update", lambda: agenda_service.update_appointment(open_vault(), read_json_input(input_)))

    @agenda_app.command("cancel")
    def agenda_cancel(
        appointment_id: str = typer.Argument(..., help="ID (ou prefixo) do compromisso."),
        reason: Optional[str] = typer.Option(None, "--reason", help="Motivo."),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Idempotência."),
    ) -> None:
        """Cancela (o registro e o histórico são mantidos; notas de reunião não são apagadas)."""
        run("agenda.cancel", lambda: agenda_service.set_status(open_vault(), appointment_id,
                                                               AppointmentStatus.CANCELLED, reason=reason,
                                                               request_id=request_id))

    @agenda_app.command("complete")
    def agenda_complete(
        appointment_id: str = typer.Argument(..., help="ID (ou prefixo) do compromisso."),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Idempotência."),
    ) -> None:
        """Marca o compromisso como concluído."""
        run("agenda.complete", lambda: agenda_service.set_status(open_vault(), appointment_id,
                                                                 AppointmentStatus.COMPLETED, request_id=request_id))

    @agenda_app.command("read")
    def agenda_read(appointment_id: str = typer.Argument(..., help="ID (ou prefixo)."),
                    history: bool = typer.Option(False, "--history", help="Inclui eventos do diário.")) -> None:
        """Lê um compromisso."""
        run("agenda.read", lambda: read_record(open_vault(), appointment_id, history=history))


def _register_tasks(app: typer.Typer) -> None:
    tasks_app = typer.Typer(help="Pendências (pendencias/tarefas.yaml).", no_args_is_help=True)
    app.add_typer(tasks_app, name="tasks")

    @tasks_app.command("add")
    def tasks_add(
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON da pendência ('-' = stdin)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Só valida (duplicatas, prazo, responsável)."),
    ) -> None:
        """Cria uma pendência (prazo relativo aceito; nada é inventado)."""
        run("tasks.add", lambda: tasks_service.add_task(open_vault(), read_json_input(input_), dry_run=dry_run))

    @tasks_app.command("list")
    def tasks_list(
        assignee: Optional[str] = typer.Option(None, "--assignee", "-a", help="Responsável (nome ou ID)."),
        related: Optional[str] = typer.Option(None, "--related", "--project", "-p",
                                              help="Projeto/nota relacionada (ID ou caminho)."),
        status: Optional[list[str]] = typer.Option(None, "--status", "-s", help="open, in_progress, blocked, "
                                                                                "completed, cancelled."),
        all_: bool = typer.Option(False, "--all", help="Todas, inclusive concluídas/canceladas."),
        overdue: bool = typer.Option(False, "--overdue", help="Só atrasadas (abertas com prazo vencido)."),
        due: Optional[str] = typer.Option(None, "--due", help="Vencimento em um dia/período ('esta semana')."),
        due_from: Optional[str] = typer.Option(None, "--due-from", help="Vencimento a partir de."),
        due_to: Optional[str] = typer.Option(None, "--due-to", help="Vencimento até."),
        meeting: Optional[str] = typer.Option(None, "--meeting", "-m", help="Reunião de origem (ID ou 'last')."),
        query: Optional[str] = typer.Option(None, "--query", "-q", help="Texto."),
    ) -> None:
        """Consulta pendências (padrão: abertas, em andamento e bloqueadas)."""
        run("tasks.list", lambda: tasks_service.list_tasks(
            open_vault(), statuses=status or None, include_all=all_, assignee=assignee, related=related,
            overdue=overdue, due=due, due_from=due_from, due_to=due_to, meeting=meeting, query=query))

    @tasks_app.command("update")
    def tasks_update(input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON {id, ...}.")) -> None:
        """Atualiza status, responsável, prazo, relações ou contexto (histórico preservado)."""
        run("tasks.update", lambda: tasks_service.update_task(open_vault(), read_json_input(input_)))

    @tasks_app.command("complete")
    def tasks_complete(
        task_id: str = typer.Argument(..., help="ID (ou prefixo) da pendência."),
        reason: Optional[str] = typer.Option(None, "--reason", help="Observação."),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Idempotência."),
    ) -> None:
        """Conclui a pendência (registra completed_at; repetir não gera segunda conclusão)."""
        run("tasks.complete", lambda: tasks_service.complete_task(open_vault(), task_id, reason=reason,
                                                                  request_id=request_id))

    @tasks_app.command("read")
    def tasks_read(task_id: str = typer.Argument(..., help="ID (ou prefixo)."),
                   history: bool = typer.Option(False, "--history", help="Inclui eventos do diário.")) -> None:
        """Lê uma pendência."""
        run("tasks.read", lambda: read_record(open_vault(), task_id, history=history))


def _register_meetings(app: typer.Typer) -> None:
    meetings_app = typer.Typer(help="Reuniões (reunioes/AAAA/MM/).", no_args_is_help=True)
    app.add_typer(meetings_app, name="meetings")

    @meetings_app.command("create")
    def meetings_create(
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON da reunião ('-' = stdin)."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Mostra o plano sem gravar."),
    ) -> None:
        """Cria o registro de uma reunião (opcionalmente a partir de um compromisso, com pendências)."""

        def _do() -> dict[str, Any]:
            out = meetings_service.create_meeting(open_vault(), read_json_input(input_), dry_run=dry_run)
            return {**out, "_operation": "meetings.create" + (".propose" if dry_run else "")}

        run("meetings.create", _do)

    @meetings_app.command("list")
    def meetings_list(
        date: Optional[str] = typer.Option(None, "--date", "-d", help="Dia ou período (ex.: hoje, 'esta semana')."),
        from_: Optional[str] = typer.Option(None, "--from", help="Data inicial."),
        to: Optional[str] = typer.Option(None, "--to", help="Data final."),
        status: Optional[list[str]] = typer.Option(None, "--status", "-s", help="Status (repetível)."),
        related: Optional[str] = typer.Option(None, "--related", help="Nota relacionada (ID ou caminho)."),
        participant: Optional[str] = typer.Option(None, "--participant", help="Participante (nome ou ID)."),
        query: Optional[str] = typer.Option(None, "--query", "-q", help="Assunto."),
    ) -> None:
        """Lista reuniões."""
        run("meetings.list", lambda: meetings_service.list_meetings(
            open_vault(), day=date, start=from_, end=to, statuses=status or None, related=related,
            participant=participant, query=query))

    @meetings_app.command("read")
    def meetings_read(
        ref: str = typer.Argument(..., help="ID, prefixo, caminho ou assunto da reunião."),
        date: Optional[str] = typer.Option(None, "--date", "-d", help="Desambigua por data."),
        history: bool = typer.Option(False, "--history", help="Inclui commits e eventos."),
    ) -> None:
        """Lê a nota da reunião com o resumo estruturado."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            from ..search.catalog import Catalog

            meeting_id = meetings_service.find_meeting(vault, Catalog.load(vault), ref, date)
            data = read_record(vault, meeting_id, history=history)
            data["summary"] = meetings_service.summarize(vault, meeting_id)
            return data

        run("meetings.read", _do)

    @meetings_app.command("note")
    def meetings_note(
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON {request_id, meeting?, entries, tasks}."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Mostra o plano sem gravar."),
    ) -> None:
        """Registra anotações na reunião informada ou na reunião ativa (em andamento)."""

        def _do() -> dict[str, Any]:
            out = meetings_service.note_meeting(open_vault(), read_json_input(input_), dry_run=dry_run)
            return {**out, "_operation": "meetings.note" + (".propose" if dry_run else "")}

        run("meetings.note", _do)

    @meetings_app.command("update")
    def meetings_update(input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON {request_id, meeting, ...}.")) -> None:
        """Atualiza metadados ou corrige a ata (correções exigem reason; original vai para o histórico)."""
        run("meetings.update", lambda: meetings_service.update_meeting(open_vault(), read_json_input(input_)))

    @meetings_app.command("start")
    def meetings_start(
        ref: str = typer.Argument(..., help="Reunião (ID, prefixo, caminho ou assunto)."),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Idempotência."),
    ) -> None:
        """Marca a reunião como em andamento (reunião ativa para anotações)."""
        run("meetings.start", lambda: meetings_service.set_meeting_status(
            open_vault(), ref, MeetingStatus.IN_PROGRESS, request_id=request_id))

    @meetings_app.command("end")
    def meetings_end(
        ref: Optional[str] = typer.Argument(None, help="Reunião (padrão: a reunião ativa)."),
        end_time: Optional[str] = typer.Option(None, "--end-time", help="Horário de término informado."),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Idempotência."),
    ) -> None:
        """Encerra a reunião (status completed)."""
        run("meetings.end", lambda: meetings_service.set_meeting_status(
            open_vault(), ref, MeetingStatus.COMPLETED, request_id=request_id, end_time=end_time))

    @meetings_app.command("active")
    def meetings_active() -> None:
        """Mostra a reunião em andamento (se houver exatamente uma)."""
        run("meetings.active", lambda: meetings_service.active_meetings(open_vault()))

    @meetings_app.command("summarize")
    def meetings_summarize(
        ref: str = typer.Argument(..., help="Reunião (ID, prefixo, caminho, assunto) ou compromisso."),
        date: Optional[str] = typer.Option(None, "--date", "-d", help="Desambigua por data."),
    ) -> None:
        """Dados registrados para o resumo: discussões, decisões, pendências, responsáveis, prazos, dúvidas."""
        run("meetings.summarize", lambda: meetings_service.summarize(open_vault(), ref, date))
