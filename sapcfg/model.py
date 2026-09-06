"""Domain model: templates, plan items, execution state."""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

VERSION = "0.1.0"


# ---------------------------------------------------------------- template model
@dataclass
class Target:
    environment: str = "DEV"
    sap_system: str = ""
    client: str = "000"
    language: str = "EN"


@dataclass
class ConfigItem:
    id: str
    kind: str
    title: str
    params: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    transaction: str = ""
    on_existing: str = "skip_if_match"
    human_approval: bool = False
    timeout_s: int = 120
    retry_max: int = 2
    retry_backoff_s: float = 2.0
    retry_whitelist: list[str] = field(default_factory=list)
    verify_scope: Optional[list[str]] = None
    verify_ignore: list[str] = field(default_factory=list)
    verify_extra: dict[str, dict[str, Any]] = field(default_factory=dict)
    # resolved at plan time
    resolved_params: dict[str, Any] = field(default_factory=dict)
    unresolved_vars: list[str] = field(default_factory=list)

    def scalar_params(self) -> dict[str, Any]:
        return {k: v for k, v in self.resolved_params.items()
                if isinstance(v, (str, int, float, bool))}


@dataclass
class TemplateBundle:
    template_id: str
    template_version: str
    customer: str
    target: Target
    variables: dict[str, Any] = field(default_factory=dict)
    items: list[ConfigItem] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    title: str = ""
    notes: str = ""

    def item(self, item_id: str) -> Optional[ConfigItem]:
        for it in self.items:
            if it.id == item_id:
                return it
        return None


# ---------------------------------------------------------------- plan model
class PlanStatus(str, Enum):
    CREATE = "CREATE"          # missing in SAP -> will create
    UPDATE = "UPDATE"          # exists, differs, safe+approved path
    SKIP = "SKIP"              # exists and matches (idempotent)
    CONFLICT = "CONFLICT"      # exists, differs, requires human (require_match)
    BLOCKED = "BLOCKED"        # dependency not satisfiable / precondition missing
    ERROR = "ERROR"            # schema/parse problem


class StepResult(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    MANUAL = "MANUAL"          # moved to human queue
    BLOCKED = "BLOCKED"
    ABORTED = "ABORTED"


@dataclass
class PlanItem:
    seq: int
    item_id: str
    kind: str
    title: str
    status: PlanStatus
    reason: str = ""
    current: dict[str, Any] = field(default_factory=dict)
    desired: dict[str, Any] = field(default_factory=dict)
    needs_approval: bool = False
    depends_on: list[str] = field(default_factory=list)
    transaction: str = ""


@dataclass
class Plan:
    run_id: str
    created_at: str
    template_id: str
    template_version: str
    customer: str
    target: Target
    items: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_status(self, s: PlanStatus) -> list[PlanItem]:
        return [i for i in self.items if i.status is s]

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {s.value: 0 for s in PlanStatus}
        for i in self.items:
            out[i.status.value] += 1
        return out


# ---------------------------------------------------------------- run / evidence
@dataclass
class Evidence:
    step_id: str
    kind: str               # 'screen' | 'screenshot' | 'message' | 'log'
    ts: str
    seq: int
    payload: dict[str, Any] = field(default_factory=dict)
    file: str = ""          # relative path if persisted (svg/png/txt)


@dataclass
class StepRun:
    seq: int
    item_id: str
    kind: str
    state: StepResult = StepResult.PENDING
    attempts: int = 0
    messages: list[str] = field(default_factory=list)
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    verified: Optional[bool] = None
    readback: dict[str, Any] = field(default_factory=dict)
    approval: str = "not_required"   # not_required | approved | denied | pending


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")
