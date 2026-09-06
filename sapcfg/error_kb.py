"""Error Knowledge Base (design §7.2).

Stores rule usage statistics (first_seen/last_seen/success_rate) and a PENDING queue
for unknown errors that a consultant must review & promote (auto_fix_allowed stays
False until approved). The rule *definitions* live versioned in error_rules/*.yaml;
this module only maintains runtime history + the review queue.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "error_kb"
HISTORY = KB_DIR / "history.jsonl"
PENDING = KB_DIR / "pending.json"
STATS = KB_DIR / "stats.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ErrorKB:
    def __init__(self, root: Path = KB_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self.stats = self._load_json(self.root / "stats.json")

    # lazy history file handle (open on first write, safe to close between runs)
    def _open(self):
        if self._fh is None:
            self._fh = open(self.root / "history.jsonl", "a", encoding="utf-8")
        return self._fh

    def _load_json(self, p: Path, default=None) -> dict:
        if not p.exists():
            return default if default is not None else {}
        return json.loads(p.read_text(encoding="utf-8"))

    def _save_pending(self, rows: list[dict]):
        (self.root / "pending.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_stats(self):
        (self.root / "stats.json").write_text(
            json.dumps(self.stats, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- usage stats
    def record_hit(self, error_key: str, ok: bool, run_id: str = "", tcode: str = ""):
        """Record one encounter of a classified error key (updates success_rate)."""
        fh = self._open()
        fh.write(json.dumps(dict(
            ts=_now(), run=run_id, tcode=tcode, key=error_key,
            ok=bool(ok)), ensure_ascii=False) + "\n")
        fh.flush()
        s = self.stats.setdefault(error_key, dict(first_seen=_now(), last_seen=_now(),
                                                  hits=0, ok=0))
        s["last_seen"] = _now()
        s["hits"] += 1
        if ok:
            s["ok"] += 1
        s["success_rate"] = round(s["ok"] / s["hits"], 3)
        self._save_stats()

    def rule_summary(self) -> dict:
        return {k: dict(v) for k, v in self.stats.items()}

    # ---------------------------------------------------------------- review queue
    def propose_unknown(self, entry: dict):
        """Add an unmatched error to the human review queue (§7.2 fields)."""
        pending = self._load_json(self.root / "pending.json", default=[])
        if not isinstance(pending, list):
            pending = []
        dedupe = f"{entry.get('tcode','')}|{entry.get('text','')}"
        if any(x.get("_dedupe") == dedupe for x in pending):
            return
        pending.append({
            "_dedupe": dedupe,
            "error_key": entry.get("error_key", ""),
            "text": entry.get("text", ""),
            "transaction": entry.get("tcode", ""),
            "screen": entry.get("screen", ""),
            "classification": entry.get("classification", "UNKNOWN"),
            "root_cause": entry.get("root_cause", ""),
            "remediation": entry.get("remediation", ""),
            "auto_fix_allowed": entry.get("auto_fix_allowed", False),
            "risk_level": entry.get("risk_level", "High"),
            "approved_by": entry.get("approved_by", ""),
            "first_seen": entry.get("first_seen", _now()),
            "last_seen": entry.get("last_seen", _now()),
            "run_id": entry.get("run_id", ""),
            "evidence": entry.get("evidence", ""),
        })
        self._save_pending(pending)

    def pending(self) -> list[dict]:
        rows = self._load_json(self.root / "pending.json", default=[])
        return rows if isinstance(rows, list) else []

    def promote(self, error_key: str, rule: dict):
        """Consultant approval: move a pending unknown into error_rules (manual, CLI)."""
        pending = [p for p in self.pending() if p.get("error_key") != error_key]
        self._save_pending(pending)
        # note: appending to error_rules/*.yaml is a deliberate, reviewed edit

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
