"""Generate the example dashboards from the test fixture memory (fictitious data).

    uv run python scripts/dashboard_demo.py [output-dir]

Builds a throwaway memory repository with `tests/dashboard/conftest.py::populate` (only CLI calls), at the
fixed test clock 2026-10-20 09:00 -03:00, and copies every generated view to `output-dir`
(default: docs/examples/dashboard).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests" / "dashboard")]

os.environ.setdefault("CONTEXT_VAULT_NOW", "2026-10-20T09:00:00-03:00")
os.environ.setdefault("GIT_AUTHOR_NAME", "Demo")
os.environ.setdefault("GIT_AUTHOR_EMAIL", "demo@example.com")
os.environ.setdefault("GIT_COMMITTER_NAME", "Demo")
os.environ.setdefault("GIT_COMMITTER_EMAIL", "demo@example.com")


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "examples" / "dashboard")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CONTEXT_VAULT_CONFIG"] = str(Path(tmp) / "user-config.yaml")
        from conftest import Cli  # tests/conftest.py
        import importlib.util

        spec = importlib.util.spec_from_file_location("dash_fixture", ROOT / "tests" / "dashboard" / "_dash.py")
        fixture = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(fixture)  # type: ignore[union-attr]
        cli = Cli(Path(tmp) / "memory")
        cli("init")
        fixture.populate(cli)
        builds = [["--view", v] for v in ("overview", "tasks", "projects", "people", "agenda", "architecture",
                                         "knowledge", "attention")]
        builds += [["--view", "project-detail", "--project", "Orion"], ["--view", "person-detail", "--person", "João"],
                   ["--view", "tasks", "--group-by", "assignee", "--output", "dashboard-tasks-by-assignee.html"]]
        out_dir.mkdir(parents=True, exist_ok=True)
        for args in builds:
            result = cli("dashboard", "build", *args)
            src = cli.repo / result["output_path"]
            shutil.copyfile(src, out_dir / src.name)
            print(f"{result['view']:<15} → {out_dir / src.name}")


if __name__ == "__main__":
    main()
