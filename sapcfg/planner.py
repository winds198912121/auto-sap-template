"""Planner: build dependency DAG, detect cycles, classify each item against SAP state."""
from __future__ import annotations

import datetime as dt

from .model import (ConfigItem, Plan, PlanItem, PlanStatus, Target,
                    TemplateBundle)

# ------------------------------------------------------------------ DAG / topo sort
class DependencyError(Exception):
    pass


def _topological_order(items: dict[str, ConfigItem]) -> list[ConfigItem]:
    """Kahn's algorithm; stable order by declared sequence."""
    order, visited = [], set()
    temp: set[str] = set()          # for cycle detection

    def visit(iid: str, stack: list[str]):
        if iid in visited:
            return
        if iid in temp:
            chain = " -> ".join(stack + [iid])
            raise DependencyError(f"dependency cycle detected: {chain}")
        temp.add(iid)
        it = items[iid]
        for dep in it.depends_on:
            if dep not in items:
                raise DependencyError(f"{it.id}: unknown dependency {dep!r}")
            visit(dep, stack + [iid])
        temp.discard(iid)
        visited.add(iid)
        order.append(it)

    for it in items.values():
        visit(it.id, [])
    return order


# ------------------------------------------------------------------ state access abstraction
class SapStateView:
    """Read-only view of current SAP config state used by the planner (no writes).

    Phase 1 implementation reads from the configured adapter (mock or real read-only
    queries). It never creates/updates anything.
    """
    def read_entry(self, table: str, key: str) -> dict | None: ...
    def list_keys(self, table: str) -> list[str]: ...


# ------------------------------------------------------------------ classification
def _same(a: dict | None, desired: dict) -> bool:
    """Compare existing record with desired values (scalar eq, subset)."""
    if not a:
        return False
    for k, v in desired.items():
        if isinstance(v, (str, int, float, bool)) and a.get(k) is not None:
            if str(a.get(k)).strip().upper() != str(v).strip().upper():
                return False
    return True


def classify(existing: dict | None, item: ConfigItem, plan: list[PlanItem],
             humans: list[str]) -> tuple[PlanStatus, str, bool]:
    """Return (status, reason, needs_approval)."""
    existed = existing is not None
    matched = _same(existing, item.resolved_params)
    on = item.on_existing

    if not existed:
        return PlanStatus.CREATE, "no existing entry in SAP", bool(item.human_approval)
    if matched:
        return PlanStatus.SKIP, "exists and matches desired state", False
    # exists and differs:
    if on == "require_match":
        return PlanStatus.CONFLICT, "existing entry differs from desired", True
    if on == "skip_if_match":
        return PlanStatus.CONFLICT, "exists with different values; template forbids overwrite", True
    if on == "update_if_diff":
        return PlanStatus.UPDATE, "existing entry differs; safe update", bool(item.human_approval)
    if on == "always_ask":
        return PlanStatus.UPDATE, "existing entry differs; update requires approval", True
    return PlanStatus.CONFLICT, f"unsupported on_existing={on}", True


# ---------------------------------------------------------------- plan builder
def build_plan(bundle: TemplateBundle, state: SapStateView,
               handler_tables: dict[str, dict], run_id: str) -> Plan:
    """Compute execution plan (Plan mode). Does not modify SAP (state is read-only view)."""
    items = {it.id: it for it in bundle.items}
    plan = Plan(run_id=run_id,
                created_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                template_id=bundle.template_id,
                template_version=bundle.template_version,
                customer=bundle.customer, target=bundle.target)

    # 1) dependency resolution (guaranteed acyclic)
    try:
        ordered = _topological_order(items)
    except DependencyError as e:
        for it in bundle.items:
            plan.items.append(PlanItem(seq=0, item_id=it.id, kind=it.kind,
                                       title=it.title, status=PlanStatus.ERROR,
                                       reason=str(e), depends_on=it.depends_on,
                                       transaction=it.transaction))
        plan.warnings.append(str(e))
        return plan

    # 2) compute classification in topo order so we know each dependency's verdict
    status_map: dict[str, PlanStatus] = {}
    for it in ordered:
        deps_status = [status_map.get(d) for d in it.depends_on]
        blocked = [d for d, s in zip(it.depends_on, deps_status)
                   if s in (PlanStatus.BLOCKED, PlanStatus.ERROR, PlanStatus.CONFLICT)]

        existing = None
        table_spec = handler_tables.get(it.kind)
        key_field = (table_spec or {}).get("key")
        key_val = (it.resolved_params or {}).get(key_field) if key_field else None
        if table_spec and key_val is not None:
            existing = state.read_entry(table_spec["table"], str(key_val))

        status, reason, approval = PlanStatus.BLOCKED, "", False
        if blocked:
            reason = "blocked by dependency: " + ", ".join(blocked)
        elif it.unresolved_vars:
            status, reason, approval = PlanStatus.ERROR, \
                "unresolved variables: " + ", ".join(it.unresolved_vars), False
        else:
            status, reason, approval = classify(existing, it, plan.items,
                                                bundle.variables.keys())

        status_map[it.id] = status
        plan.items.append(PlanItem(
            seq=len(plan.items) + 1, item_id=it.id, kind=it.kind, title=it.title,
            status=status, reason=reason,
            current=existing or {}, desired=dict(it.resolved_params or {}),
            needs_approval=approval, depends_on=it.depends_on, transaction=it.transaction))

    plan.items.sort(key=lambda p: p.seq)
    return plan
