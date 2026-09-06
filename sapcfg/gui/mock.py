"""Mock SAP GUI driver + in-memory configuration store.

Implements the same SapGuiAdapter protocol as the Windows SAP GUI Scripting driver so
the whole pipeline (planner / orchestrator / verification / evidence) can be developed
and tested offline with *simulated* data. NEVER touches a real system.

The mock stores configuration entries in plain dicts (never a real SAP DB).
Fault injection lets tests exercise the retry/error machinery deterministically.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Optional

from .base import (ConnectionError_, SapGuiAdapter, SapAutomationError,
                   Screen, StepMessageError)

DEFAULT_SEEDS: dict[str, dict[str, dict]] = {
    # test/demo defaults -- simulates an empty-ish DEV client 100
    "company": {"01": {"company": "01", "name": "Japan Operating Company"}},
}


class MockConfig:
    """Simulated SAP configuration tables (only legal write surface in mock mode)."""

    def __init__(self, seeds: Optional[dict[str, dict[str, dict]]] = None):
        self.tables: dict[str, dict[str, dict]] = {}
        for table, rows in (seeds or DEFAULT_SEEDS).items():
            self.tables[table] = {k: dict(v) for k, v in rows.items()}
        # fault injection hooks: {kind: {count: n, message: "..."}}
        self.faults: dict[str, dict] = {}

    def take_faults(self) -> dict[str, dict]:
        """Hand faults over to a driver instance (consume-on-attach)."""
        f = {k: dict(v) for k, v in self.faults.items()}
        self.faults = {}
        return f

    def get(self, table: str, key: str) -> Optional[dict]:
        row = self.tables.get(table, {}).get(str(key))
        return dict(row) if row else None

    def upsert(self, table: str, row: dict, key_field: str) -> None:
        self.tables.setdefault(table, {})[str(row[key_field])] = dict(row)

    def keys(self, table: str) -> list[str]:
        return list(self.tables.get(table, {}).keys())

    def drop(self, table: str, key: str) -> None:
        self.tables.get(table, {}).pop(str(key), None)


class MockGui(SapGuiAdapter):
    """Drives a catalog of per-tcode screens with a mock config store."""

    name = "mock"

    def __init__(self, catalog: list[dict], config: Optional[MockConfig] = None,
                 system: str = "S4D", client: str = "100"):
        self.catalog = {s["tcode"]: s for s in catalog}
        self.cfg = config or MockConfig()
        self.system, self.client = system, client
        self.user = "MOCK_TECH"
        self._screen: Screen | None = None
        self._screen_def: dict = {}
        self._field_values: dict[str, str] = {}
        self._message = ""
        self._status_class = "info"
        self._log: list[dict] = []
        self.connected = False
        # fault injection:  {step_kind: {count: n, message: "..."}}
        self.faults: dict[str, dict] = config.take_faults() if config else {}
        self.auto_fault_step: dict[str, int] = {}   # set by tests

    # ------------------------------------------------------------- lifecycle
    def connect(self) -> None:
        self.connected = True
        self._note("info", f"connected (MOCK) to {self.system} client {self.client} as {self.user}")

    def disconnect(self) -> None:
        self.connected = False

    def _note(self, cls: str, msg: str):
        self._status_class = cls
        self._message = msg

    def last_message(self) -> str:
        return self._message

    def status_class(self) -> str:
        return self._status_class

    def events(self) -> list[dict]:
        return list(self._log)

    # ------------------------------------------------------------- navigation
    def start_transaction(self, tcode: str) -> Screen:
        if not self.connected:
            raise ConnectionError_("mock adapter not connected")
        if tcode not in self.catalog:
            raise SapAutomationError(f"tcode {tcode} has no screen definition in the step skill catalog")
        self._screen_def = self.catalog[tcode]
        self._field_values = {f["id"]: "" for f in self._screen_def.get("fields", [])}
        self._note("info", f"Transaction {tcode} started")
        self._screen = self._make_screen()
        self._log.append({"t": self._ts(), "event": "tcode", "tcode": tcode})
        return self._screen

    def fill_key(self, field_id: str, value: str) -> None:
        self._set(field_id, value)

    def enter(self) -> Screen:
        key = self._key_field_id()
        val = self._field_values.get(key)
        table, keyf = self._screen_def["read_table"], self._screen_def["read_key"]
        if val and self.cfg.get(table, val):
            row = self.cfg.get(table, val)
            for fid, col in self._screen_def["columns"].items():
                if col in row and row[col] is not None:
                    self._field_values[fid] = str(row[col])
            self._note("info", f"Entry {val} displayed for change")
        elif val:
            self._note("warning", f"Entry {val} does not exist in {table}")
        else:
            self._note("info", "Enter a key")
        return self.refresh()

    def fill(self, field_id: str, value: Any) -> None:
        self._set(field_id, str(value))

    def select_dropdown(self, field_id: str, value: str) -> None:
        self._set(field_id, value)

    def _set(self, fid: str, value: str):
        if self._screen is None:
            raise SapAutomationError("no active screen; call start_transaction first")
        if fid not in self._field_values:
            raise SapAutomationError(f"field id {fid!r} not on screen {self._screen_def.get('tcode')}")
        self._field_values[fid] = value

    # ------------------------------------------------------------- save
    def save(self) -> str:
        spec = self._screen_def
        kind = spec.get("kind", "")
        tcode = spec.get("tcode", "")
        key_fid = self._key_field_id()
        key = self._field_values.get(key_fid, "").strip()
        if not key:
            raise StepMessageError(f"Enter a {spec.get('key_label', 'key')}",
                                   tcode=tcode, msg_class="E", msg_number="001")

        # fault injection: transient/blocking SAP messages for tests & demos
        if self.faults.get(kind, {}).get("count", 0) > 0:
            self.faults[kind]["count"] -= 1
            msg = self.faults[kind].get("message",
                                        "Table E071K is locked by user X")
            cls_ = self.faults[kind].get("msg_class", "")
            num_ = self.faults[kind].get("msg_number", "")
            raise StepMessageError(msg, tcode=tcode, msg_class=cls_, msg_number=num_)

        # business validators (mirror SAP behavior)
        for check in spec.get("validators", []):
            err = self._run_validator(check)
            if err:
                self._note("error", err)
                raise StepMessageError(err, tcode=tcode, msg_class="E", msg_number="002")

        row = {}
        for fid, col in spec["columns"].items():
            v = self._field_values.get(fid, "")
            if v != "":
                row[col] = v
        self.cfg.upsert(spec["save_table"], row, spec["save_key"])
        self._note("success", spec.get("success_message", "Data was saved"))
        self._log.append({"t": self._ts(), "event": "save", "table": spec["save_table"],
                          "key": key, "row": dict(row)})
        return self._message

    def _run_validator(self, check: dict) -> str | None:
        kind = check["type"]
        val = self._field_values.get(check["field"], "")
        if kind == "exists_in":
            other = check["table"]
            if val and not self.cfg.get(other, val):
                return f"{check.get('msg', other)} {val}: entry does not exist in client {self.client}"
        if kind == "member_of":
            allowed = self.cfg.keys(check["table"])
            if val and val not in allowed:
                return f"Value {val} is not valid (choose from {', '.join(sorted(allowed))})"
        return None

    def read_config(self, table: str, key: str) -> Optional[dict]:
        return self.cfg.get(table, key)

    # ------------------------------------------------------------- helpers
    def refresh(self) -> Screen:
        self._screen = self._make_screen()
        return self._screen

    def _key_field_id(self) -> str:
        return self._screen_def.get("key_field", "code")

    def _make_screen(self) -> Screen:
        spec = self._screen_def
        fields = []
        for f in spec.get("fields", []):
            fid = f["id"]
            kind = f.get("kind", "text")
            fields.append({
                "id": fid, "label": f["label"], "kind": kind,
                "value": self._field_values.get(fid, ""),
                "ro": bool(f.get("ro", False)),
                "options": self._dropdown_options(f) if kind == "dropdown" else None,
                "key": fid == spec.get("key_field"),
            })
        return Screen(title=spec.get("title", ""), tcode=spec.get("tcode", ""),
                      system=self.system, client=self.client, user=self.user,
                      fields=fields, buttons=["Save", "Back", "Exit", "Cancel"],
                      status=self._message, table=[])

    def _dropdown_options(self, f: dict) -> list[str]:
        table = f.get("options_table")
        if not table:
            return []
        return sorted(self.cfg.keys(table))

    def capture_screen(self) -> dict:
        """Render the CURRENT live screen (values + status message)."""
        s = self._make_screen()
        return {
            "title": s.title, "tcode": s.tcode, "system": s.system,
            "client": s.client, "user": s.user, "status": s.status,
            "status_class": self._status_class,
            "fields": s.fields, "buttons": s.buttons,
        }

    def _ts(self) -> str:
        return dt.datetime.now().isoformat(timespec="seconds")

    def tick(self, seconds: float = 0.05):
        time.sleep(seconds)
