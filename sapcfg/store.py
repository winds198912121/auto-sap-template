"""Run store: folders, SQLite state, JSONL event log, evidence (SVG screenshots)."""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .model import Evidence, Plan, StepResult

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


# ====================================================================== SVG screen renderer
_XML_ESC = re.compile(r'[<>&"\']')


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _color(cls: str) -> str:
    return {"success": "#1b7f3b", "error": "#c0392b", "warning": "#b7791f",
            "info": "#2456a6"}.get(cls, "#333333")


def render_screen_svg(cap: dict) -> str:
    """Render a simulated SAP GUI screen capture as SVG (viewable evidence)."""
    W, H = 720, 430
    w_title = _esc(cap.get("title", "SAP Easy Access"))
    w_tcode = _esc(cap.get("tcode", ""))
    header = f"{w_title}   [{w_tcode}]   {_esc(cap.get('system', ''))} / {_esc(cap.get('client', ''))} / {_esc(cap.get('user', ''))}"
    fields = cap.get("fields") or []
    n = len(fields)
    rows = max(1, (n + 1) // 2)
    top, row_h = 92, 40
    y = top
    cells = []
    for i, f in enumerate(fields):
        col = i % 2
        if i % 2 == 0:
            y = top + (i // 2) * row_h
        x = 24 + col * 350
        lab = _esc(f.get("label", f.get("id", "")))
        val = _esc(f.get("value", ""))
        if f.get("key"):
            val = f"[{val}]"
        cells.append(f'<text x="{x}" y="{y-8}" font-size="11" fill="#555">{lab}</text>')
        cells.append(f'<rect x="{x-4}" y="{y-2}" width="300" height="20" rx="3" fill="#fff" '
                     f'stroke="#9aa5b1" stroke-width="1"/>')
        cells.append(f'<text x="{x+4}" y="{y+13}" font-size="13" fill="#111">{val}</text>')
    buttons = "    ".join(f"[ {_esc(b)} ]" for b in (cap.get("buttons") or []))
    status = _esc(cap.get("status", ""))
    scls = _color(cap.get("status_class", "info"))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Menlo,Consolas,monospace">
<rect width="{W}" height="{H}" fill="#eef2f6"/>
<rect x="0" y="0" width="{W}" height="34" fill="#1e3a5f"/>
<text x="14" y="23" font-size="15" fill="#fff" font-weight="bold">{header}</text>
<rect x="8" y="44" width="704" height="{max(120, rows*row_h+30)}" fill="#fbfcfd" stroke="#c3ccd6" rx="4"/>
<text x="24" y="72" font-size="12" fill="#8a94a0">Data entry</text>
{chr(10).join(cells)}
<text x="24" y="{top + rows*row_h + 8}" font-size="12" fill="#444">{buttons}</text>
<rect x="0" y="{H-30}" width="{W}" height="30" fill="#dfe6ec"/>
<rect x="0" y="{H-30}" width="{W}" height="4" fill="{scls}"/>
<text x="14" y="{H-11}" font-size="13" fill="{scls}" font-weight="bold">{status}</text>
</svg>"""


# ====================================================================== run store
class RunStore:
    """One run = one folder under runs/. SQLite for step state; JSONL for events."""

    def __init__(self, run_id: Optional[str] = None, base: Path = RUNS_DIR):
        self.base = base
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.dir = base / self.run_id
        self.ev_dir = self.dir / "evidence"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ev_dir.mkdir(exist_ok=True)
        self._seq = 0
        self.events_fh = open(self.dir / "events.jsonl", "a", encoding="utf-8")
        self._db = sqlite3.connect(str(self.dir / "run.sqlite"))
        self._init_db()

    # ------------------------------------------------------------- sqlite
    def _init_db(self):
        cur = self._db.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS runs(
            run_id TEXT PRIMARY KEY, template_id TEXT, customer TEXT, adapter TEXT,
            status TEXT, plan_json TEXT, created TEXT, updated TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS steps(
            run_id TEXT, item_id TEXT, seq INT, kind TEXT, state TEXT, attempts INT,
            verified INT, error TEXT, readback TEXT, messages TEXT,
            approval TEXT, started TEXT, finished TEXT,
            PRIMARY KEY(run_id, item_id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS approvals(
            run_id TEXT, item_id TEXT, actor TEXT, granted INT, ts TEXT,
            PRIMARY KEY(run_id, item_id))""")
        self._db.commit()

    def close(self):
        self.events_fh.close()
        self._db.close()

    # ------------------------------------------------------------- events
    def emit(self, etype: str, payload: dict, step_id: str = "") -> int:
        self._seq += 1
        rec = dict(seq=self._seq, t=datetime.now().astimezone().isoformat(timespec="seconds"),
                   type=etype, step=step_id, payload=payload)
        self.events_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.events_fh.flush()
        return self._seq

    def log(self, msg: str, step_id: str = "", level: str = "info"):
        return self.emit("log", dict(msg=msg, level=level), step_id)

    def screen(self, step_id: str, cap: dict) -> int | None:
        if not cap or cap.get("empty"):
            return None
        cap = dict(cap)
        # sanitize / shorten value payload for the event stream
        cap.pop("value", None)
        seq = self.emit("screen", cap, step_id)
        fname = f"{seq:05d}_{step_id or 'nav'}.svg"
        (self.ev_dir / fname).write_text(render_screen_svg(cap), encoding="utf-8")
        self.emit("evidence", dict(file=f"evidence/{fname}", kind="screen-svg"), step_id)
        return seq

    def message(self, step_id: str, text: str, cls: str):
        return self.emit("message", dict(text=text, cls=cls), step_id)

    # ------------------------------------------------------------- run meta
    def meta(self, plan: Plan, adapter_name: str):
        self._db.execute("""INSERT OR REPLACE INTO runs(run_id, template_id, customer,
            adapter, status, plan_json, created, updated) VALUES(?,?,?,?,?,?,?,?)""",
            (self.run_id, plan.template_id, plan.customer, adapter_name, "planned",
             json.dumps(self.plan_doc(plan), ensure_ascii=False, indent=2),
             plan.created_at, plan.created_at))
        self._db.commit()
        (self.dir / "plan.json").write_text(
            json.dumps(self.plan_doc(plan), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def plan_doc(plan: Plan) -> dict:
        t = plan.target
        return dict(run_id=plan.run_id, created_at=plan.created_at,
                    template_id=plan.template_id, template_version=plan.template_version,
                    customer=plan.customer,
                    target=dict(environment=t.environment, sap_system=t.sap_system,
                                client=t.client, language=t.language),
                    warnings=plan.warnings,
                    items=[dict(seq=i.seq, item_id=i.item_id, kind=i.kind, title=i.title,
                                status=i.status.value, reason=i.reason, current=i.current,
                                desired=i.desired, needs_approval=i.needs_approval,
                                depends_on=i.depends_on, transaction=i.transaction)
                           for i in plan.items])

    def run_status(self) -> str:
        self._reopen_if_closed()
        row = self._db.execute("SELECT status FROM runs WHERE run_id=?",
                               (self.run_id,)).fetchone()
        return row[0] if row else ""

    def set_run_status(self, status: str):
        self._db.execute("UPDATE runs SET status=?, updated=? WHERE run_id=?",
                         (status, datetime.now().astimezone().isoformat(timespec="seconds"),
                          self.run_id))
        self._db.commit()

    # ------------------------------------------------------------- step state
    def _reopen_if_closed(self):
        """apply_mode() closes the store; readers may reopen on demand."""
        try:
            self._db.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            self._db = sqlite3.connect(str(self.dir / "run.sqlite"))

    def step_save(self, item_id: str, seq: int, kind: str, state: StepResult,
                  attempts: int = 0, verified: Optional[bool] = None,
                  error: str = "", readback: Optional[dict] = None,
                  messages: Optional[list] = None, approval: str = "not_required",
                  started: str = "", finished: str = ""):
        self._db.execute("""INSERT OR REPLACE INTO steps(run_id, item_id, seq, kind,
            state, attempts, verified, error, readback, messages, approval,
            started, finished) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (self.run_id, item_id, seq, kind, state.value, attempts,
             int(verified) if verified is not None else None, error,
             json.dumps(readback or {}, ensure_ascii=False),
             json.dumps(messages or [], ensure_ascii=False), approval, started, finished))
        self._db.commit()

    def step_load(self, item_id: str) -> Optional[dict]:
        cur = self._db.execute(
            "SELECT * FROM steps WHERE run_id=? AND item_id=?", (self.run_id, item_id))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))
        d["readback"] = json.loads(d["readback"] or "{}")
        d["messages"] = json.loads(d["messages"] or "[]")
        return d

    def list_steps(self) -> list[dict]:
        self._reopen_if_closed()
        cur = self._db.execute("SELECT item_id, seq, kind, state, attempts, verified, "
                               "error, approval FROM steps WHERE run_id=? ORDER BY seq",
                               (self.run_id,))
        return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]

    # ------------------------------------------------------------- approvals
    def grant(self, item_id: str, actor: str = "console-user") -> bool:
        try:
            self._db.execute("""INSERT OR REPLACE INTO approvals(run_id, item_id, actor,
                granted, ts) VALUES(?,?,?,1,?)""",
                (self.run_id, item_id, actor,
                 datetime.now().astimezone().isoformat(timespec="seconds")))
            self._db.commit()
            return True
        except sqlite3.Error:
            return False

    def approved(self, item_id: str) -> bool:
        row = self._db.execute("SELECT granted FROM approvals WHERE run_id=? AND item_id=?",
                               (self.run_id, item_id)).fetchone()
        return bool(row and row[0])

    def pending_approvals(self) -> list[str]:
        self._reopen_if_closed()
        cur = self._db.execute(
            "SELECT item_id FROM steps WHERE run_id=? AND approval='pending'", (self.run_id,))
        return [r[0] for r in cur.fetchall()]

    def summary_stats(self) -> dict:
        self._reopen_if_closed()
        cur = self._db.execute(
            "SELECT state, COUNT(*) FROM steps WHERE run_id=? GROUP BY state", (self.run_id,))
        return {r[0]: r[1] for r in cur.fetchall()}

    # ------------------------------------------------------------- misc
    def evidence_files(self) -> list[str]:
        return sorted(p.name for p in self.ev_dir.glob("*.svg"))

    def events_all(self) -> list[dict]:
        return [json.loads(l) for l in
                (self.dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if l]

    def cleanup(self):
        self.close()
        shutil.rmtree(self.dir, ignore_errors=True)
