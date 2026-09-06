"""macOS real SAP GUI (Java) driver — Accessibility keystrokes + local OCR.

Real channel for THIS machine (SAP GUI for Java 8.10, macOS). SAP GUI Scripting
is Windows-only, so the adapter drives the Java GUI the way a user does:

  * keystrokes via macOS Accessibility (System Events) — keyboard-first,
    no screen coordinates for typing;
  * field *location* via the local OCR service (http://localhost:8765,
    RapidOCR): screenshots of the SAP window -> text lines with boxes ->
    click next to a field label -> type. Works over any DPI / layout;
  * verification is intentionally conservative (see read_config / save).

Safety posture (mirrors win_gui.py):
  * macOS only; refuses to import elsewhere,
  * requires explicit consent: env SAPCFG_ALLOW_REAL_SAP=1  OR  a flag file
    named `.sapcfg_allow_real_sap` in the repo root (created from the console
    after the operator ticks the real-SAP consent),
  * the framework never stores SAP credentials; attach to an already
    logged-on session (optional auto-logon via env-only creds, off by default),
  * fills only fields whose label is *visible* on the current screen; when a
    field cannot be located it raises HumanRequiredError -> human queue
    (never blind-tabs into unknown controls),
  * transport-request dialogs are never auto-created: a request number may be
    pre-supplied via SAP_TRANSPORT (operator choice), otherwise the step goes
    to the human queue with a screenshot.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .base import (ConnectionError_, HumanRequiredError, RetryableError,
                   SapAutomationError, SapGuiAdapter, Screen,
                   StepMessageError)

ROOT = Path(__file__).resolve().parents[2]          # repo root
FLAG_FILE = ROOT / ".sapcfg_allow_real_sap"
OCR_URL = os.environ.get("OCR_URL", "http://localhost:8765/ocr/image")
APP_NAME = os.environ.get("SAP_APP", "SAPGUI")

# macOS virtual keycodes (US layout) — only those we need
KEY = {"return": 36, "enter": 36, "tab": 48, "esc": 53, "space": 49,
       "down": 125, "up": 126, "left": 123, "right": 124, "f4": 118,
       "f8": 100, "home": 115, "end": 119}


def real_sap_allowed() -> bool:
    return (os.environ.get("SAPCFG_ALLOW_REAL_SAP") == "1"
            or FLAG_FILE.exists())


def _aq(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class MacSapGui(SapGuiAdapter):
    name = "sap_gui_mac"

    def __init__(self, system: str = "", client: str = "",
                 language: str = "EN"):
        if sys.platform != "darwin":
            raise SystemError(
                "MacSapGui requires macOS + SAP GUI for Java. Use adapter=mock "
                "for offline plan/simulation.")
        if not real_sap_allowed():
            raise PermissionError(
                "Real SAP connection refused (macOS driver). Explicit human "
                "consent required: export SAPCFG_ALLOW_REAL_SAP=1 or create the "
                "flag file `.sapcfg_allow_real_sap` in the repo root.")
        self._expect_system = system
        self._expect_client = client
        self._language = language
        self.system, self.client, self.user = system, client, ""
        self._connected = False
        self._message = ""
        self._status_class = "info"
        self._ev_dir: Optional[Path] = None
        self._tcode = ""
        self._last_fields: dict[str, str] = {}     # typed values this screen
        self._catalog: dict[str, dict] = {}
        self._verify_mode = os.environ.get("SAPCFG_REAL_VERIFY", "none")  # none|screen
        self._transport = os.environ.get("SAP_TRANSPORT", "").strip()
        self._strict = os.environ.get("SAPCFG_STRICT_SESSION", "") == "1"
        try:                                       # label/kind map per tcode
            from ..steps import fi_basic
            self._catalog = fi_basic.SCREENS_BY_TCODE
        except Exception:
            pass

    # ------------------------------------------------------------------ osascript
    def _osa(self, script: str) -> str:
        p = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True)
        if p.returncode != 0:
            err = p.stderr.strip()
            if re.search(r"assistive access|not allowed|-1728", err):
                raise ConnectionError_(
                    "Accessibility permission missing. Grant it in System "
                    "Settings > Privacy & Security > Accessibility to the app "
                    "that runs the console, then retry.")
            raise SapAutomationError(f"osascript failed: {err}")
        return p.stdout.strip()

    def _activate(self):
        try:
            self._osa(f'tell application "{APP_NAME}" to activate')
        except SapAutomationError:
            pass
        time.sleep(0.8)

    def _type(self, text: str):
        self._osa(f'tell application "System Events" to tell process "{APP_NAME}" '
                  f'to keystroke "{_aq(text)}"')

    def _key(self, name: str):
        n = name.lower()
        if n in KEY:
            self._osa(f'tell application "System Events" to tell process '
                      f'"{APP_NAME}" to key code {KEY[n]}')
        else:
            self._osa(f'tell application "System Events" to tell process '
                      f'"{APP_NAME}" to keystroke "{_aq(n)}"')

    def _combo(self, spec: str):
        """'cmd+a' / 'ctrl+s' / 'cmd+shift+s'"""
        parts = [p.strip() for p in spec.split("+")]
        mods, key = parts[:-1], parts[-1].lower()
        using = []
        for m in mods:
            using.append({"ctrl": "control down", "cmd": "command down",
                          "opt": "option down", "shift": "shift down"}.get(m))
        clause = f" using {{{', '.join(x for x in using if x)}}}" if using else ""
        if key in KEY:
            self._osa(f'tell application "System Events" to tell process '
                      f'"{APP_NAME}" to key code {KEY[key]} {clause}')
        else:
            self._osa(f'tell application "System Events" to tell process '
                      f'"{APP_NAME}" to keystroke "{_aq(key)}" {clause}')

    def _click(self, gx: float, gy: float):
        self._osa(f'tell application "System Events" to click at '
                  f'{{{int(gx)}, {int(gy)}}}')

    def _win_rect(self) -> dict | None:
        """Front SAP window {x,y,w,h} in global points (Accessibility)."""
        try:
            pos = self._osa(f'tell application "System Events" to tell process '
                            f'"{APP_NAME}" to get position of window 1').split(", ")
            size = self._osa(f'tell application "System Events" to tell process '
                             f'"{APP_NAME}" to get size of window 1').split(", ")
            return dict(x=int(pos[0]), y=int(pos[1]),
                        w=int(size[0]), h=int(size[1]))
        except Exception:
            return None

    # ------------------------------------------------------------------ OCR
    def _shot_region(self, region: dict | None, out: Path) -> bool:
        if region:
            r = f"{region['x']},{region['y']},{region['w']},{region['h']}"
            subprocess.run(["screencapture", "-x", "-R", r, str(out)],
                           capture_output=True)
        else:
            subprocess.run(["screencapture", "-x", str(out)],
                           capture_output=True)
        return out.exists() and out.stat().st_size > 0

    def _ocr(self) -> tuple[list[dict], Path]:
        """OCR the SAP window; lines [{text,score,x1,y1,x2,y2}] in window points."""
        rect = self._win_rect()
        tmp = Path("/tmp") / f"sapcfg_{os.getpid()}_{int(time.time())}.png"
        if not self._shot_region(rect, tmp):
            return [], tmp
        p = subprocess.run(["curl", "-s", "-m", "40", "-F", f"file=@{tmp}",
                            OCR_URL], capture_output=True, text=True)
        lines: list[dict] = []
        if p.returncode == 0 and p.stdout.strip():
            try:
                for ln in json.loads(p.stdout).get("lines", []):
                    box = ln.get("box") or []
                    # box formats: [x1,y1,x2,y2]  |  [[x,y] x4] (RapidOCR corners)
                    if box and isinstance(box[0], (list, tuple)):
                        px = [pt[0] for pt in box]
                        py = [pt[1] for pt in box]
                        x1, x2, y1, y2 = min(px), max(px), min(py), max(py)
                    elif len(box) >= 4:
                        x1, y1, x2, y2 = box[:4]
                    else:
                        continue
                    lines.append(dict(text=ln.get("text", ""),
                                      score=ln.get("score", 0),
                                      x1=float(x1), y1=float(y1),
                                      x2=float(x2), y2=float(y2)))
            except Exception:
                pass
        return lines, tmp

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", "", s).lower()

    def _find_label(self, lines: list[dict], label: str) -> dict | None:
        want = self._norm(label)
        if len(want) < 3:
            return None
        best, best_score = None, 0.0
        for ln in lines:
            t = self._norm(ln["text"])
            score = 1.0 if t == want else (0.8 if t.startswith(want)
                                           or want.startswith(t) else 0.0)
            if score and score > best_score:
                best, best_score = ln, score
        return best

    def _bottom_status(self, lines: list[dict], h: float) -> str:
        low = [ln for ln in lines if ln["y2"] > h * 0.8]
        return " ".join(ln["text"] for ln in sorted(low, key=lambda l: l["y1"]))

    # ------------------------------------------------------------------ lifecycle
    def set_evidence_dir(self, d: str):
        self._ev_dir = Path(d)
        self._ev_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> None:
        # SAP GUI process present?
        try:
            procs = self._osa('tell application "System Events" to get name of '
                              'every process')
        except SapAutomationError:
            raise
        if APP_NAME not in procs:
            raise ConnectionError_(
                f"SAP GUI ({APP_NAME}) is not running. Start it and log on to "
                f"system '{self._expect_system}' client '{self._expect_client}' "
                f"first — the framework never stores SAP credentials.")
        self._activate()
        self._connected = True
        self._note("info", f"attached to {APP_NAME} (expect {self._expect_system}/"
                   f"{self._expect_client})")
        # best-effort session sanity check (strict mode only)
        if self._strict:
            lines, tmp = self._ocr()
            txt = " ".join(ln["text"] for ln in lines)
            hint = (self._expect_system.lower().split()[0]
                    if self._expect_system else "")
            if not txt or (hint and hint not in txt.lower()
                           and "easy access" not in txt.lower()):
                raise ConnectionError_(
                    "STRICT session check failed: cannot confirm an SAP session "
                    f"for '{self._expect_system}' on screen. Unset "
                    "SAPCFG_STRICT_SESSION to attach anyway.")

    def disconnect(self) -> None:
        self._connected = False

    def _note(self, cls: str, msg: str):
        self._status_class = cls
        self._message = msg

    def last_message(self) -> str:
        return self._message

    def status_class(self) -> str:
        return self._status_class

    # ------------------------------------------------------------------ navigation
    def start_transaction(self, tcode: str) -> Screen:
        if not self._connected:
            raise ConnectionError_("adapter not connected — call connect() first")
        self._activate()
        self._type(f"/n{tcode}")
        self._key("enter")
        time.sleep(5.0)                     # remote system (~235ms RTT)
        self._tcode = tcode
        self._last_fields = {}
        lines, tmp = self._ocr()
        self._read_status_ocr(lines, tmp)
        return self._snapshot(lines)

    def _snapshot(self, lines: list[dict] | None = None) -> Screen:
        return Screen(title="", tcode=self._tcode, system=self.system,
                      client=self.client, user=self.user,
                      status=self._message, table=[])

    # ------------------------------------------------------------------ field entry
    def _screen_def(self) -> dict:
        return self._catalog.get(self._tcode, {})

    def _label_of(self, field_id: str) -> str:
        sdef = self._screen_def()
        for f in sdef.get("fields", []):
            if f["id"] == field_id:
                return f.get("label", field_id)
        return field_id

    def _field_kind(self, field_id: str) -> str:
        for f in self._screen_def().get("fields", []):
            if f["id"] == field_id:
                return f.get("kind", "text")
        return "text"

    def _click_field(self, label: str) -> bool:
        """Click into the input that follows the visible label. True if found."""
        self._activate()
        lines, tmp = self._ocr()
        rect = self._win_rect() or dict(x=0, y=0, w=1440, h=900)
        ln = self._find_label(lines, label)
        if not ln:
            return False
        # field sits to the right of the label on the same row (table/screen forms)
        gx = rect["x"] + ln["x2"] + 14
        gy = rect["y"] + (ln["y1"] + ln["y2"]) / 2
        self._click(gx, gy)
        time.sleep(0.8)
        return True

    def fill_key(self, field_id: str, value: str) -> None:
        self._fill_typed(field_id, value)

    def fill(self, field_id: str, value: Any) -> None:
        self._fill_typed(field_id, str(value))

    def _fill_typed(self, field_id: str, value: str) -> None:
        label = self._label_of(field_id)
        if not self._click_field(label):
            raise HumanRequiredError(
                f"field '{field_id}' (label '{label}') not visible on the current "
                f"SAP screen — record its position on this client system "
                f"(Phase 1: only label-visible fields are auto-filled).")
        self._combo("cmd+a")                  # replace any existing content
        self._type(value)
        self._last_fields[field_id] = value
        time.sleep(0.6)

    def enter(self) -> Screen:
        self._activate()
        self._key("enter")
        time.sleep(4.0)
        lines, tmp = self._ocr()
        self._read_status_ocr(lines, tmp)
        return self._snapshot(lines)

    def select_dropdown(self, field_id: str, value: str) -> None:
        label = self._label_of(field_id)
        if not self._click_field(label):
            raise HumanRequiredError(
                f"dropdown '{field_id}' (label '{label}') not visible — human "
                f"attention needed on tcode {self._tcode}.")
        self._key("f4")
        time.sleep(4.0)                       # value help (remote)
        self._type(value)
        time.sleep(1.5)
        self._key("enter")
        time.sleep(1.0)
        self._key("esc")                      # close any lingering pick list
        time.sleep(1.0)
        self._last_fields[field_id] = value
        # soft confirmation: value help keywords should be gone now
        lines, tmp = self._ocr()
        txt = " ".join(ln["text"] for ln in lines).lower()
        if any(k in txt for k in ("possible entries", "value help",
                                  "restricted value range", "matchcode")):
            raise HumanRequiredError(
                f"value-help for '{field_id}' did not resolve on the real GUI "
                f"(select '{value}' manually).")

    # ------------------------------------------------------------------ save / transport
    def save(self) -> str:
        self._activate()
        self._combo("ctrl+s")
        time.sleep(6.0)                       # remote save + transport prompt
        lines, tmp = self._ocr()
        rect = self._win_rect() or dict(x=0, y=0, w=1440, h=900)
        txt = " ".join(ln["text"] for ln in lines).lower()
        # --- transport request dialog: never auto-create -----------------------
        if any(k in txt for k in ("transport request", "request/task",
                                  "customizing request", "create request",
                                  "transport of copies")):
            if self._transport:
                ln = self._find_label(lines, "Request/Task") or \
                     self._find_label(lines, "Request")
                if ln:
                    gx = rect["x"] + ln["x2"] + 14
                    gy = rect["y"] + (ln["y1"] + ln["y2"]) / 2
                    self._click(gx, gy)
                    time.sleep(0.8)
                    self._type(self._transport)
                    self._key("enter")
                    time.sleep(4.0)
                else:
                    raise HumanRequiredError(
                        "transport dialog shown but request field not located; "
                        f"entering SAP_TRANSPORT={self._transport} manually needed.")
            else:
                raise HumanRequiredError(
                    "SAP asks for a transport/customizing request. Complete the "
                    "request in the GUI (or set SAP_TRANSPORT=<request> and "
                    "re-run) — the framework never creates transports.")
            lines, tmp = self._ocr()
            txt = " ".join(ln["text"] for ln in lines).lower()
        self._read_status_ocr(lines, tmp)
        msg = self._message
        if self._status_class == "error":
            if re.search(r"lock|locked|another user", msg.lower()):
                raise RetryableError(msg)
            raise StepMessageError(msg)
        return msg

    def _read_status_ocr(self, lines: list[dict], tmp: Path):
        h = (self._win_rect() or dict(h=900))["h"]
        status = self._bottom_status(lines, h) or ""
        low = status.lower()
        if any(k in low for k in ("error", "not possible", "does not exist",
                                  "not authorized", "specify a different",
                                  "enter a valid")):
            self._note("error", status.strip())
        elif any(k in low for k in ("saved", "was saved", "created",
                                    "successfully", "activated")):
            self._note("success", status.strip())
        else:
            self._note("info", status.strip())
        if self._ev_dir:
            tmp.replace(self._ev_dir / f"screen_{int(time.time())}.png")

    # ------------------------------------------------------------------ read-back
    def read_config(self, table: str, key: str) -> Optional[dict]:
        """Real read-back.

        default ('none'): returns None -> orchestrator treats the entry as
        missing -> verification goes to the human queue (safe default).

        With SAPCFG_REAL_VERIFY=screen: re-opens the maintenance view for
        `table` and reads column values via OCR. Any ambiguity -> None (safe).
        """
        if self._verify_mode != "screen":
            return None
        sdef = next((s for s in self._catalog.values()
                     if s.get("read_table") == table), None)
        if not sdef or not sdef.get("columns"):
            return None
        try:
            self.start_transaction(sdef["tcode"])
            key_fid = sdef.get("key_field") or sdef.get("read_key", "")
            if not self._click_field(self._label_of(key_fid)):
                return None
            self._combo("cmd+a")
            self._type(str(key))
            self._key("enter")
            time.sleep(5.0)
            lines, _tmp = self._ocr()
            out: dict[str, str] = {}
            for fid, col in sdef["columns"].items():
                lab = self._label_of(fid)
                v = self._ocr_value_for(lines, lab, fid)
                if v is None:
                    return None              # cannot verify all columns -> safe
                out[col] = v
            return out
        except Exception:
            return None

    def _ocr_value_for(self, lines: list[dict], label: str,
                       field_id: str) -> Optional[str]:
        """Value for a column/grid header 'label' on the data row(s)."""
        hdr = self._find_label(lines, label)
        if not hdr:
            # single-entry forms: label then value on the same line is usual;
            # grid: header at top, first data row under it.
            return None
        cand = [ln for ln in lines
                if ln["y1"] >= hdr["y2"] and self._norm(ln["text"]) != self._norm(label)
                and ln["x1"] >= hdr["x1"] - 10 and ln["x2"] <= hdr["x2"] + 260]
        if not cand:
            return None
        cand.sort(key=lambda l: (l["y1"], l["x1"]))
        val = cand[0]["text"].strip()
        if self._norm(val) == self._norm(label):
            return None
        return val or None

    # ------------------------------------------------------------------ evidence
    def capture_screen(self) -> dict:
        lines, tmp = self._ocr()
        self._read_status_ocr(lines, tmp)
        cap = dict(title="", tcode=self._tcode, system=self.system,
                   client=self.client, user=self.user or "-",
                   status=self._message, status_class=self._status_class,
                   fields=[], buttons=["Save (Ctrl+S)"],
                   note="real SAP GUI — screenshot saved to evidence/")
        if self._ev_dir:
            name = f"real_{int(time.time())}.png"
            try:
                if self._shot_region(self._win_rect(), self._ev_dir / name):
                    cap["png"] = name
            except Exception:
                pass
        return cap

    def events(self) -> list[dict]:
        return []


__all__ = ["MacSapGui", "real_sap_allowed", "FLAG_FILE"]
