"""Knowledge commands: search, read, propose, apply, gaps."""

from __future__ import annotations

from typing import Any, Optional

import typer

from ..search.engine import search as run_search
from ..services.proposals import apply as apply_proposal
from ..services.proposals import parse_proposal, plan
from ..services.reader import list_gaps, read_record
from .support import open_vault, read_json_input, run


def register(app: typer.Typer) -> None:
    gaps_app = typer.Typer(help="Lacunas de conhecimento (informações a esclarecer).", no_args_is_help=True)
    app.add_typer(gaps_app, name="gaps")

    @app.command()
    def search(
        query: str = typer.Argument(..., help="Texto, sigla, nome ou ID."),
        limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Máximo de resultados."),
        type_: Optional[list[str]] = typer.Option(None, "--type", "-t", help="Filtra tipo de nota (repetível)."),
        kind: Optional[list[str]] = typer.Option(None, "--kind", "-k",
                                                 help="note, task, appointment, inbox, journal (repetível)."),
        no_related: bool = typer.Option(False, "--no-related", help="Não expandir por relacionamentos."),
    ) -> None:
        """Busca híbrida em notas, pendências, agenda, inbox e diário."""
        run("memory.search", lambda: run_search(open_vault(), query, limit=limit, types=type_ or None,
                                                kinds=kind or None, include_related=not no_related))

    @app.command()
    def read(
        ref: str = typer.Argument(..., help="ID, prefixo de ID (8+ caracteres) ou caminho da nota."),
        history: bool = typer.Option(False, "--history", help="Inclui commits e eventos do diário."),
    ) -> None:
        """Lê um registro com relações, backlinks, pendências e compromissos relacionados."""
        run("memory.read", lambda: read_record(open_vault(), ref, history=history))

    @app.command()
    def propose(
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="Arquivo JSON da proposta ('-' = stdin)."),
        proposal_: Optional[str] = typer.Option(None, "--proposal", "-p", help="Sinônimo de --input."),
    ) -> None:
        """Valida uma proposta e mostra o plano (diff, duplicações, confirmação exigida). Não grava nada."""

        def _do() -> dict[str, Any]:
            proposal = parse_proposal(read_json_input(input_ or proposal_))
            result = plan(open_vault(), proposal)
            return {**result.to_dict(), "_operation": f"{proposal.operation.value}.propose"}

        run("memory.propose", _do)

    @app.command()
    def apply(
        proposal_: Optional[str] = typer.Option(None, "--proposal", "-p", help="Arquivo JSON da proposta ('-' = stdin)."),
        input_: Optional[str] = typer.Option(None, "--input", "-i", help="Sinônimo de --proposal."),
    ) -> None:
        """Aplica uma proposta: grava, atualiza índices, registra no diário e faz commit local."""

        def _do() -> dict[str, Any]:
            proposal = parse_proposal(read_json_input(proposal_ or input_))
            return {**apply_proposal(open_vault(), proposal), "_operation": proposal.operation.value}

        run("memory.apply", _do)

    @gaps_app.command("list")
    def gaps_list(
        ref: Optional[str] = typer.Argument(None, help="Restringe a um registro (ID ou caminho)."),
        include_resolved: bool = typer.Option(False, "--all", help="Inclui lacunas resolvidas."),
    ) -> None:
        """Lista lacunas de conhecimento em aberto (ou adiadas)."""

        def _do() -> dict[str, Any]:
            gaps = list_gaps(open_vault(), ref, include_resolved)
            return {"gaps": gaps, "total": len(gaps)}

        run("gaps.list", _do)
