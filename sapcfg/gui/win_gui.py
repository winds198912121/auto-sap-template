"""SAP GUI Scripting driver for the *real* SAP GUI (Windows only).

Production channel for Phase 1 (design doc §3: SAP Adapter -> GUI Scripting).
This module CANNOT run on macOS / without SAP GUI, by design:

  * import raises SystemError unless running on Windows with pywin32 available,
  * connect() only attaches to an ALREADY LOGGED-ON SAP GUI session (no credentials
    are ever stored or typed by the framework),
  * an extra environment flag SAPCFG_ALLOW_REAL_SAP=1 is required at runtime, and the
    orchestrator refuses this adapter unless the run was explicitly approved.

Control paths (e.g. 'wnd[0]/usr/txtRF05V-BUKRS') differ per SAP release/theme and are
NOT hardcoded here blindly: each screen definition in the step skill catalog may carry
an optional 'ctl' per field. Those paths must be recorded on the actual client system
(the console provides a 'record' helper for a consultant to capture them once). Until
then this driver only supports: attach, tcode start, key entry, status-bar readback,
and screenshot capture -- safe, non-writing primitives.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any, Optional

from .base import (ConnectionError_, RetryableError, SapAutomationError,
                   SapGuiAdapter, Screen)


def _win32_gui_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


class WinSapGui(SapGuiAdapter):
    """Attaches to the active SAP GUI Scripting session."""

    name = "sap_gui_scripting"

    def __init__(self, system: str = "", client: str = ""):
        if not _win32_gui_available():
            raise SystemError(
                "SAP GUI Scripting driver requires Windows + SAP GUI with scripting "
                "enabled (SAP GUI Options -> Scripting). It cannot run in this "
                "environment (macOS). Use adapter=mock for offline plan/simulation.")
        if os.environ.get("SAPCFG_ALLOW_REAL_SAP") != "1":
            raise PermissionError(
                "Real SAP connection refused: set SAPCFG_ALLOW_REAL_SAP=1 explicitly "
                "AFTER human approval of the plan. Design principle: DEV auto only "
                "with explicit consent; never PRD.")
        import win32com.client
        self._com = win32com.client
        self.system, self.client = system, client
        self._session = None
        self._app = None
        self._message, self._status_class = "", "info"

    # -- lifecycle ------------------------------------------------------------
    def connect(self) -> None:
        try:
            self._app = self._com.GetObject("SAPGUI").GetScriptingEngine
        except Exception as e:  # COM not reachable
            raise ConnectionError_(f"cannot attach to SAP GUI scripting engine: {e}") from e
        conns = self._app.Children
        if conns.Count == 0:
            raise ConnectionError_("SAP GUI is open but no connection/logon session found "
                                   "(please log on first; framework never stores credentials)")
        # prefer target system if given, else first session
        target = None
        for i in range(conns.Count):
            c = conns.Item(i)
            for j in range(c.Children.Count):
                s = c.Children.Item(j)
                if self.system and s.Info.SystemName.upper() == self.system.upper():
                    target = s
                if target is None:
                    target = s
        if target is None:
            raise ConnectionError_("no usable SAP session")
        self._session = target
        self.system = self.system or self._session.Info.SystemName
        self.client = self.client or self._session.Info.Client

    def disconnect(self) -> None:
        self._session, self._app = None, None

    # -- primitives (safe / read-only unless a skill explicitly writes) --------
    def start_transaction(self, tcode: str) -> Screen:
        self._ensure()
        self._session.findById("wnd[0]/tbar[0]/okcd").text = tcode
        self._session.findById("wnd[0]").sendVKey(0)          # Enter
        time.sleep(0.3)
        return self._snapshot()

    def fill_key(self, field_id: str, value: str) -> None:
        self._ensure()
        ctl = self._screen_ctl(field_id) or self._last_ctl(field_id)
        if ctl:
            self._session.findById(ctl).text = value

    def enter(self) -> Screen:
        self._ensure()
        self._session.findById("wnd[0]").sendVKey(0)
        time.sleep(0.2)
        return self._snapshot()

    def fill(self, field_id: str, value: Any) -> None:
        self.fill_key(field_id, str(value))

    def select_dropdown(self, field_id: str, value: str) -> None:
        ctl = self._screen_ctl(field_id) or self._last_ctl(field_id)
        if ctl:
            box = self._session.findById(ctl)
            try:
                box.keyToValue = value
            except Exception:
                box.text = value

    def save(self) -> str:
        self._ensure()
        self._session.findById("wnd[0]/tbar[0]/btn[11]").press()   # Save
        time.sleep(0.4)
        msg = self.last_message()
        self._session.findById("wnd[0]").sendVKey(0)               # ack status bar
        if self._status_class == "error":
            if any(k in msg.lower() for k in ("lock", "locked", "another user")):
                raise RetryableError(msg)
            raise SapAutomationError(msg)
        return msg

    def read_config(self, table: str, key: str) -> Optional[dict]:
        """GUI-level read-back: not implemented generically for real systems yet.

        Replace per step with (a) a read-only RFC/report call or (b) the step's own
        screen read-back implemented in the handler skill. Returning None forces the
        verification engine to treat the entry as 'missing' -- a safe default.
        """
        return None

    def last_message(self) -> str:
        self._ensure()
        try:
            bar = self._session.findById("wnd[0]/sbar")
            self._message = bar.Text or ""
            self._status_class = "success" if bar.MessageType == "S" else (
                "error" if bar.MessageType == "E" else "warning")
        except Exception:
            pass
        return self._message

    def status_class(self) -> str:
        return self._status_class

    def capture_screen(self) -> dict:
        self._ensure()
        try:
            w = self._session.findById("wnd[0]")
            w.HardCopy("", "", os.path.join(self._evidence_dir or ".", "screen.bmp"))
        except Exception as e:
            return {"error": f"HardCopy failed: {e}"}
        return {"hardcopy": "screen.bmp", "note": "Windows-only evidence stored as BMP/PNG"}

    # -- internals -------------------------------------------------------------
    _evidence_dir = "."

    def set_evidence_dir(self, d: str):
        self._evidence_dir = d

    def _ensure(self):
        if self._session is None:
            raise ConnectionError_("not connected")

    def _snapshot(self) -> Screen:
        self.last_message()
        return Screen(system=self.system, client=self.client,
                      status=self._message, title="", tcode="")

    _screen_ctl = None
    _last_ctl = None

    def _path(self, *parts: str) -> str:
        return "/".join(parts)
