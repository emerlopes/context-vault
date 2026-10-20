"""Repository commands: init, status, validate, index, recover, journal."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import typer

from ..config import resolve_repository
from ..errors import ValidationError
from ..search.catalog import Catalog
from ..services.indexer import generate, index_drift
from ..services.journal import iter_journal_files, journal_path, parse_journal
from ..services.transaction import Transaction, pending_transactions, recover
from ..services.validation import validate_repository
from ..services.vault import Vault
from ..storage.layout import initialize_layout
from .support import open_vault, run, state


def register(app: typer.Typer) -> None:
    index_app = typer.Typer(help="Índices derivados (INDEX.md e index.json).", no_args_is_help=True)
    journal_app = typer.Typer(help="Diário de eventos.", no_args_is_help=True)
    app.add_typer(index_app, name="index")
    app.add_typer(journal_app, name="journal")

    @app.command()
    def init(no_git: bool = typer.Option(False, "--no-git", help="Não inicializar Git (não recomendado).")) -> None:
        """Cria (ou completa) a estrutura do repositório de memória. Idempotente."""

        def _do() -> dict[str, Any]:
            repo = resolve_repository(state.repo)
            result = initialize_layout(repo)
            vault = Vault(repo)
            commit = None
            git_initialized = False
            if not no_git:
                if not vault.git.is_repo():
                    vault.git.init()
                    git_initialized = True
                if vault.config.behavior.auto_commit:
                    commit = vault.git.commit("context-vault: init", None)
            return {"repository": str(repo), "created": result.created, "existing": result.existing,
                    "git_initialized": git_initialized, "commit": commit}

        run("repository.init", _do)

    @app.command()
    def status() -> None:
        """Mostra o estado do repositório de memória."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            report = validate_repository(vault)
            git_info: dict[str, Any] = {"initialized": vault.git.is_repo()}
            if git_info["initialized"]:
                pending = vault.git.status_porcelain()
                last = vault.git.last_commit()
                git_info.update(
                    clean=not pending, uncommitted=pending,
                    last_commit=None if last is None else {"hash": last.short, "message": last.message, "date": last.date},
                )
            from ..services.inbox import load_inbox

            return {
                "repository": str(vault.repo), "timezone": vault.timezone, "now": vault.now().isoformat(),
                "counts": report.counts, "inbox_pending": sum(1 for e in load_inbox(vault) if e.status.value == "pending"),
                "pending_transactions": len(pending_transactions(vault)), "valid": report.ok, "git": git_info,
            }

        run("repository.status", _do)

    @app.command()
    def validate() -> None:
        """Valida schemas, IDs, referências, caminhos e o índice. Sai com código 5 se houver erros."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            report = validate_repository(vault)
            stale = _stale_index(vault)
            if stale:
                report.warning("INDEX_STALE", None, "Índice desatualizado; rode `context-vault index rebuild`",
                               files=stale)
                for item in index_drift(vault.repo, Catalog.load(vault))["missing_files"]:
                    report.warning("INDEX_MISSING_FILE", item["path"],
                                   f"O índice aponta para \"{item['title']}\", mas o arquivo não existe. O conteúdo "
                                   f"pode estar no histórico Git (git log -- {item['path']}); `index rebuild` "
                                   "remove a entrada.", id=item["id"])
            data = report.to_dict()
            if not report.ok:
                data["_exit_code"] = 5
            return data

        run("repository.validate", _do)

    @index_app.command("rebuild")
    def index_rebuild() -> None:
        """Reconstrói INDEX.md e index.json e reporta inconsistências (exit 9 se houver erros)."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            drift = index_drift(vault.repo, Catalog.load(vault, use_cache=False))
            with Transaction(vault, "context-vault: index rebuild") as tx:
                catalog = Catalog.load(vault, use_cache=False)
                tx.reindex = False
                for rel, content in generate(catalog).items():
                    if tx.read(rel) != content:
                        tx.write(rel, content)
                result = tx.commit()
            report = validate_repository(vault)
            data = {"entries": len(catalog.valid()), "changed": result.paths, "commit": result.commit,
                    "removed_entries": drift["missing_files"], "added_entries": drift["unindexed"],
                    "consistent": report.ok, **{k: v for k, v in report.to_dict().items() if k in ("errors", "warnings", "issues")}}
            if not report.ok:
                data["_exit_code"] = 9
            return data

        run("index.rebuild", _do)

    @index_app.command("check")
    def index_check() -> None:
        """Verifica se os índices estão atualizados (exit 9 se não estiverem)."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            stale = _stale_index(vault)
            drift = index_drift(vault.repo, Catalog.load(vault)) if stale else {}
            return {"consistent": not stale, "stale": stale, **{k: v for k, v in drift.items() if v},
                    **({"_exit_code": 9} if stale else {})}

        run("index.check", _do)

    @app.command("recover")
    def recover_cmd() -> None:
        """Recupera transações interrompidas (rollback ou roll-forward)."""
        run("repository.recover", lambda: {"recovered": recover(open_vault())})

    @journal_app.command("list")
    def journal_list(
        on: Optional[str] = typer.Option(None, "--date", help="Data AAAA-MM-DD (padrão: hoje)."),
        target: Optional[str] = typer.Option(None, "--target", help="Filtra por ID do registro."),
        all_days: bool = typer.Option(False, "--all", help="Todos os dias."),
        period: Optional[str] = typer.Option(None, "--period", "-p",
                                             help="Período: 'esta semana', 'ontem', AAAA-MM-DD (até hoje)…"),
    ) -> None:
        """Lista eventos do diário."""

        def _do() -> dict[str, Any]:
            vault = open_vault()
            if period:
                from ..services.dates import parse_range

                start, end = parse_range(period, vault.now(), vault.timezone)
                if start == end and start <= vault.now().date():
                    end = vault.now().date()
                files = [f for f in iter_journal_files(vault.repo) if start.isoformat() <= f.stem <= end.isoformat()]
            elif all_days:
                files = iter_journal_files(vault.repo)
            else:
                try:
                    day = date.fromisoformat(on) if on else vault.now().date()
                except ValueError:
                    raise ValidationError(f"Data inválida: {on}") from None
                files = [vault.repo / journal_path(day)]
            events = []
            for file in files:
                if file.is_file():
                    events += [e for e in parse_journal(file.read_text(encoding="utf-8"))
                               if not target or str(e.get("target_id", "")).startswith(target)]
            return {"events": events, "total": len(events)}

        run("journal.list", _do)


def _stale_index(vault: Vault) -> list[str]:
    expected = generate(Catalog.load(vault))
    stale = []
    for rel, content in expected.items():
        path = vault.repo / rel
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            stale.append(rel)
    return stale
