# SPDX-License-Identifier: Apache-2.0
"""Behavioral contracts for usage-driven dashboard cost rows."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = ROOT / "omlx/admin/static/js/dashboard.js"
STATUS_TEMPLATE = ROOT / "omlx/admin/templates/dashboard/_status.html"
I18N_DIR = ROOT / "omlx/admin/i18n"


def _method_source(name: str) -> str:
    """Lift one complete Alpine method out of the shipped dashboard source."""

    source = DASHBOARD_JS.read_text()
    match = re.search(rf"^[ \t]*(?:async\s+)?{re.escape(name)}\(", source, re.M)
    assert match is not None, f"dashboard.js has no {name}() method"
    start = match.start()
    body_start = source.index("{", source.index(")", source.index("(", start)))
    depth = 0
    for index in range(body_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{name} has unbalanced braces in dashboard.js")


def test_cost_rows_only_include_models_with_tokens_in_selected_scope():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to execute the dashboard cost filter")

    method = _method_source("costModelsForScope")
    script = f"""
const component = {{
  {method},
  models: [{{ id: 'installed-but-unused' }}],
  modelPricing: {{ 'priced-but-unused': {{ prompt_price_per_m: 1 }} }},
  costData: {{ models: {{
    'session-used': {{
      session: {{ prompt_tokens: 12, completion_tokens: 0 }},
      alltime: {{ prompt_tokens: 12, completion_tokens: 0 }},
    }},
    'completion-only': {{
      session: {{ prompt_tokens: 0, completion_tokens: 4 }},
      alltime: {{ prompt_tokens: 0, completion_tokens: 4 }},
    }},
    'historical-only': {{
      session: {{ prompt_tokens: 0, completion_tokens: 0 }},
      alltime: {{ prompt_tokens: 20, completion_tokens: 8 }},
    }},
    'tracked-without-usage': {{
      session: {{ prompt_tokens: 0, completion_tokens: 0 }},
      alltime: {{ prompt_tokens: 0, completion_tokens: 0 }},
    }},
  }} }},
}};
const ids = scope => component.costModelsForScope(scope).map(model => model.id);
console.log(JSON.stringify({{ session: ids('session'), alltime: ids('alltime') }}));
"""
    result = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "session": ["completion-only", "session-used"],
        "alltime": ["completion-only", "historical-only", "session-used"],
    }


def test_cost_table_uses_scope_filter_and_has_localized_empty_state():
    javascript = DASHBOARD_JS.read_text()
    template = STATUS_TEMPLATE.read_text()

    getter = javascript.split("get costModelList() {", 1)[1].split("},", 1)[0]
    assert "this.costModelsForScope(this.statsScope)" in getter
    assert 'x-show="costModelList.length === 0"' in template
    assert "status.cost.no_usage" in template

    for locale_path in I18N_DIR.glob("*.json"):
        translations = json.loads(locale_path.read_text())
        assert translations["status.cost.no_usage"]


def test_status_polling_refreshes_and_stops_cost_updates():
    start = _method_source("startStatsRefresh")
    stop = _method_source("stopStatsRefresh")

    assert "this._costRefreshTimer = setInterval" in start
    assert "this.loadCosts()" in start
    assert "3000" in start
    assert "clearInterval(this._costRefreshTimer)" in stop
    assert "this._costRefreshTimer = null" in stop
