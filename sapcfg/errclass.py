"""Error classification engine (design §6).

Rules-first, whitelist-bounded. The engine decides what MAY happen for an SAP status
message -- never the LLM, never free clicking.

§6.2 decision order:
  1. Message Class + Number  (strongest key)
  2. tcode / screen context + text
  3. text matching only (multi-language supplement)
  4. else -> UNKNOWN (stop step, human queue, propose to Error Knowledge Base)

Retry constraints (§6.3): LOCK/TRANSIENT/NAVIGATION may auto-retry (default budget 2);
PERMISSION / INPUT / BUSINESS_CONFLICT / UNKNOWN never retry; same error repeating
after the budget stops the retry loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .gui.base import StepMessageError

RULES_PATH = Path(__file__).resolve().parent.parent / "error_rules" / "default_rules.yaml"


class ErrorKind(str, Enum):
    TRANSIENT = "TRANSIENT"            # GUI timeout / session busy / brief disconnect
    NAVIGATION = "NAVIGATION"          # unexpected back to start / window level change
    ALREADY_EXISTS = "ALREADY_EXISTS"  # object already created -> compare, skip or conflict
    PRECONDITION = "PRECONDITION"      # company code / plant etc. not yet created
    INPUT = "INPUT"                    # length / format / domain violation
    PERMISSION = "PERMISSION"          # no tcode / object authorization (SU53)
    LOCK = "LOCK"                      # object locked by another user
    BUSINESS_CONFLICT = "BUSINESS_CONFLICT"  # existing value differs from template
    UNKNOWN = "UNKNOWN"                # not in knowledge base

# default behaviour per kind (a rule may override retry_max / auto_fix_allowed)
KIND_DEFAULT = {
    ErrorKind.TRANSIENT:   dict(action="retry", retry_max=2, risk="low"),
    ErrorKind.NAVIGATION:  dict(action="retry", retry_max=2, risk="low"),
    ErrorKind.LOCK:        dict(action="retry", retry_max=2, risk="low"),
    ErrorKind.ALREADY_EXISTS: dict(action="verify", retry_max=0, risk="low"),
    ErrorKind.PRECONDITION:   dict(action="human", retry_max=0, risk="medium"),
    ErrorKind.INPUT:          dict(action="human", retry_max=0, risk="medium"),
    ErrorKind.PERMISSION:     dict(action="human", retry_max=0, risk="high"),
    ErrorKind.BUSINESS_CONFLICT: dict(action="human", retry_max=0, risk="high"),
    ErrorKind.UNKNOWN:        dict(action="human", retry_max=0, risk="high"),
}


@dataclass
class Rule:
    id: str
    classification: ErrorKind
    action: str = "retry"                # retry | verify | human
    retry_max: int = 2
    auto_fix_allowed: bool = True
    risk: str = "low"
    msg_class: str = ""                  # optional: SAP message class
    msg_number: str = ""                 # optional: SAP message number
    tcode: str = ""                      # optional: scope to a transaction
    text_re: str = ""                    # regex on status text (multi-language friendly)
    notes: str = ""
    approved_by: str = "framework"       # who approved this rule (design §7.2)

    @property
    def error_key(self) -> str:
        if self.msg_class and self.msg_number:
            return f"{self.msg_class}/{self.msg_number}"
        return self.id


@dataclass
class Verdict:
    kind: ErrorKind
    rule: Optional[Rule]
    error_key: str
    action: str
    retry_max: int
    auto_fix_allowed: bool
    risk: str
    reason: str

    @property
    def retryable(self) -> bool:
        return self.action == "retry" and self.auto_fix_allowed


class Classifier:
    """Rule-first classifier with §6.2 priority."""

    def __init__(self, rules: Optional[list[Rule]] = None):
        self.rules = rules if rules is not None else load_rules(RULES_PATH)
        self._index()

    def _index(self):
        self._by_key: dict[str, Rule] = {}          # "class/number"
        self._by_tcode_text: list[Rule] = []        # tcode + text
        self._by_text: list[Rule] = []              # text only
        self._by_class: dict[str, list[Rule]] = {}
        for r in self.rules:
            if r.msg_class and r.msg_number:
                self._by_key[f"{r.msg_class}/{r.msg_number}"] = r
            elif r.tcode and r.text_re:
                self._by_tcode_text.append(r)
            elif r.text_re:
                self._by_text.append(r)
            elif r.msg_class:
                self._by_class.setdefault(r.msg_class, []).append(r)

    def classify(self, err: StepMessageError) -> Verdict:
        """Decision order: class+number -> tcode+text -> text -> class -> UNKNOWN."""
        key = f"{err.msg_class}/{err.msg_number}" if (err.msg_class and err.msg_number) else ""
        # 1) message class + number
        if key and key in self._by_key:
            return self._verdict(self._by_key[key], f"message key {key}")
        # 2) transaction + text
        for r in self._by_tcode_text:
            if r.tcode == err.tcode and re.search(r.text_re, err.text, re.I):
                return self._verdict(r, f"tcode {err.tcode} + text rule {r.id}")
        # 3) text only
        for r in self._by_text:
            if re.search(r.text_re, err.text, re.I):
                return self._verdict(r, f"text rule {r.id}")
        # 4) message class only
        for r in self._by_class.get(err.msg_class, []):
            return self._verdict(r, f"message class {err.msg_class}")
        # 5) unknown
        return Verdict(ErrorKind.UNKNOWN, None, f"UNK:{hash(err.text) & 0xffffffff:08x}",
                       "human", 0, False, "high",
                       f"no rule matched text={err.text!r} tcode={err.tcode!r} key={key!r}")

    @staticmethod
    def _verdict(r: Rule, reason: str) -> Verdict:
        action = r.action
        retry_max = r.retry_max
        if not r.auto_fix_allowed and action == "retry":
            action, retry_max = "human", 0
        return Verdict(r.classification, r, r.error_key, action, retry_max,
                       r.auto_fix_allowed, r.risk, reason)


def load_rules(path: Path) -> list[Rule]:
    import yaml
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    rules = []
    for d in data:
        rules.append(Rule(
            id=d["id"],
            classification=ErrorKind(d["classification"]),
            action=d.get("action", KIND_DEFAULT[ErrorKind(d["classification"])]["action"]),
            retry_max=int(d.get("retry_max", KIND_DEFAULT[ErrorKind(d["classification"])]["retry_max"])),
            auto_fix_allowed=bool(d.get("auto_fix_allowed", True)),
            risk=d.get("risk", KIND_DEFAULT[ErrorKind(d["classification"])]["risk"]),
            msg_class=d.get("msg_class", ""), msg_number=d.get("msg_number", ""),
            tcode=d.get("tcode", ""), text_re=d.get("text_re", ""),
            notes=d.get("notes", ""), approved_by=d.get("approved_by", "framework")))
    return rules
