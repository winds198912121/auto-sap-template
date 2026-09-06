"""Programmatic entry points shared by CLI and web console."""
from __future__ import annotations

from pathlib import Path

from .gui.mock import MockConfig
from .load import load_bundle
from .orchestrator import Orchestrator
from .store import RunStore

# adapters an operator may *explicitly* choose at apply time.
# mock stays the default; real adapters are consent-gated at construction.
REAL_ADAPTERS = ("sap_gui_mac",)


def plan(vars_file: str | Path, steps_file: str | Path,
         config: MockConfig | None = None) -> RunStore:
    bundle = load_bundle(Path(vars_file), Path(steps_file))
    orch = Orchestrator(adapter_name="mock", config=config)
    return orch.plan_mode(bundle)


def apply(run_id: str, approvals: list[str] | None = None,
          approve_all: bool = False,
          config: MockConfig | None = None,
          adapter: str = "mock") -> RunStore:
    orch = Orchestrator(adapter_name=adapter, config=config)
    return orch.apply_mode(run_id, approvals=approvals or [],
                           approve_all=approve_all)
