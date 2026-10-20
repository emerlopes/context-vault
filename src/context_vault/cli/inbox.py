"""Inbox commands (provisional captures)."""

from __future__ import annotations

from typing import Any, Optional

import typer

from ..errors import ValidationError
from ..models.common import SourceType
from ..models.inbox import InboxStatus
from ..services import inbox as inbox_service
from ..services.proposals import apply as apply_proposal
from ..services.proposals import parse_proposal
from ..services.reader import resolve_ref
from .support import open_vault, read_json_input, run


def register(app: typer.Typer) -> None:
    inbox_app = typer.Typer(help="Capturas provisórias não classificadas.", no_args_is_help=True)
    app.add_typer(inbox_app, name="inbox")

    @inbox_app.command("add")
    def add(
        text: Optional[str] = typer.Option(None, "--text", help="Texto original da captura."),
        entity: Optional[list[str]] = typer.Option(None, "--entity", "-e", help="Entidade identificada (repetível)."),
        question: Optional[str] = typer.Option(None, "--question", "-q", help="Pergunta pendente."),
        source: SourceType = typer.Option(SourceType.USER, "--source", help="Origem."),
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="JSON {text, entities, question}."),
    ) -> None:
        """Guarda uma informação sem classificação (texto original preservado)."""

        def _do() -> dict[str, Any]:
            data = read_json_input(input_) if input_ else {}
            body = text or data.get("text")
            if not body or not str(body).strip():
                raise ValidationError("Informe --text ou 'text' no JSON")
            entry, commit = inbox_service.add_entry(
                open_vault(), str(body), entities=list(entity or data.get("entities") or []),
                question=question or data.get("question"), source_type=SourceType(data.get("source_type", source)),
                request_id=data.get("request_id"),
            )
            return {"record_id": entry.id, "path": ".context-vault/inbox.md", "entry": entry.model_dump(mode="json"),
                    "commit": commit}

        run("inbox.add", _do)

    @inbox_app.command("list")
    def list_(
        status: Optional[InboxStatus] = typer.Option(InboxStatus.PENDING, "--status", help="Filtra por status."),
        all_: bool = typer.Option(False, "--all", help="Todas as entradas."),
    ) -> None:
        """Lista o que ficou sem classificar."""

        def _do() -> dict[str, Any]:
            entries = inbox_service.load_inbox(open_vault())
            if not all_:
                entries = [e for e in entries if e.status == status]
            return {"entries": [e.model_dump(mode="json") for e in entries], "total": len(entries)}

        run("inbox.list", _do)

    @inbox_app.command("classify")
    def classify(
        entry_id: str = typer.Argument(..., help="ID (ou prefixo) da entrada."),
        target: Optional[str] = typer.Option(None, "--target", help="Registro onde a informação foi consolidada."),
        proposal_: Optional[str] = typer.Option(None, "--proposal", "-p",
                                                help="Proposta a aplicar junto (mesma transação)."),
    ) -> None:
        """Marca uma entrada como classificada, opcionalmente aplicando a proposta que a consolida."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            if proposal_:
                proposal = parse_proposal(read_json_input(proposal_))
                holder: dict[str, Any] = {}

                def hook(tx, plan) -> None:
                    holder["entry"] = inbox_service.update_entry(vault, entry_id, status=InboxStatus.CLASSIFIED,
                                                                 classified_to=plan.record_id, tx=tx)

                result = apply_proposal(vault, proposal, hook=hook)
                entry = holder.get("entry")
                return {**result, "inbox_entry": entry.model_dump(mode="json") if entry else None,
                        "_operation": "inbox.classify"}
            if not target:
                raise ValidationError("Informe --target ou --proposal")
            target_id = resolve_ref(vault, target)[1]
            entry = inbox_service.update_entry(vault, entry_id, status=InboxStatus.CLASSIFIED, classified_to=target_id)
            return {"record_id": entry.id, "classified_to": target_id, "entry": entry.model_dump(mode="json")}

        run("inbox.classify", _do)

    @inbox_app.command("discard")
    def discard(entry_id: str = typer.Argument(..., help="ID (ou prefixo) da entrada.")) -> None:
        """Descarta uma entrada (permanece no arquivo com status discarded)."""

        def _do() -> dict[str, Any]:
            entry = inbox_service.update_entry(open_vault(), entry_id, status=InboxStatus.DISCARDED)
            return {"record_id": entry.id, "entry": entry.model_dump(mode="json")}

        run("inbox.discard", _do)
