"""ContextVault Dashboard: local, offline, read-only HTML views of the memory (docs/dashboard.md).

Layers (spec §3.2): `queries` (snapshot + structured filters over canonical records) →
`aggregations`/`attention` (indicators and items) → `models` (versioned view model) →
`renderer` (Jinja2 templates in `templates/`, assets inlined from `assets/`). `service` orchestrates
build/refresh/list/open; `security` redacts secrets, validates paths and checks the generated HTML.
"""

from .filters import BuildOptions
from .models import SCHEMA_VERSION, View
from .service import build, list_reports, open_report, refresh

__all__ = ["BuildOptions", "SCHEMA_VERSION", "View", "build", "list_reports", "open_report", "refresh"]
