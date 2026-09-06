"""Adapter protocol: one uniform interface over SAP execution channels.

Design: SAP Adapter component (design doc §3) shields orchestrator/handlers from the
concrete channel. Phase 1 = SAP GUI Scripting (Windows). A mock driver implements the
same protocol for offline development/tests. Later channels (RFC / API / ABAP report /
Transport) only need to implement this protocol.

The protocol is screen-action based with *semantic* fields — handlers map business
params to screen field ids, the driver maps those to actual GUI controls (or mock).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class SapAutomationError(Exception):
    """Base for SAP operation errors."""


class StepMessageError(SapAutomationError):
    """A real SAP status/popup message that blocked a step.

    Carries the fields the classifier (§6) keys on. `text` is the raw message text;
    msg_class/msg_number mirror SAP's message class + number when available.
    """

    def __init__(self, text: str, tcode: str = "", msg_class: str = "",
                 msg_number: str = "", popup: str = "", context: dict | None = None):
        super().__init__(text)
        self.text = text
        self.tcode = tcode
        self.msg_class = msg_class
        self.msg_number = msg_number
        self.popup = popup
        self.context = context or {}

    @property
    def error_key(self) -> str:
        if self.msg_class and self.msg_number:
            return f"{self.msg_class}/{self.msg_number}"
        return self.text


class RetryableError(SapAutomationError):
    """Transient, whitelisted, safe to retry (legacy alias; prefer StepMessageError)."""


class HumanRequiredError(SapAutomationError):
    """Unknown / high-risk situation: route to human queue."""


class ConnectionError_(SapAutomationError):
    pass


@dataclass
class Screen:
    """Current GUI screen state (visual snapshot for evidence & console rendering)."""
    title: str = ""
    tcode: str = ""
    system: str = ""
    client: str = ""
    user: str = ""
    fields: list[dict[str, Any]] = field(default_factory=list)   # {id,label,value,kind,ro}
    buttons: list[str] = field(default_factory=list)
    status: str = ""                                             # SAP status bar message
    table: Optional[list[dict[str, Any]]] = field(default_factory=list)


class SapGuiAdapter(ABC):
    """Uniform execution channel API."""

    name: str = "base"

    # -- lifecycle ----------------------------------------------------------
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    # -- navigation ---------------------------------------------------------
    @abstractmethod
    def start_transaction(self, tcode: str) -> Screen: ...

    @abstractmethod
    def fill_key(self, field_id: str, value: str) -> None:
        """Fill the (single) key field to display / select an existing entry."""

    @abstractmethod
    def enter(self) -> Screen:
        """Press Enter: drill into an existing entry (read-back)."""

    # -- data entry ----------------------------------------------------------
    @abstractmethod
    def fill(self, field_id: str, value: Any) -> None: ...

    @abstractmethod
    def select_dropdown(self, field_id: str, value: str) -> None: ...

    @abstractmethod
    def save(self) -> str:
        """Save; returns status-bar message text."""

    # -- read-back ------------------------------------------------------------
    @abstractmethod
    def read_config(self, table: str, key: str) -> Optional[dict]:
        """Read an existing config entry by its key (verification source)."""

    # -- status / error -------------------------------------------------------
    @abstractmethod
    def last_message(self) -> str: ...

    @abstractmethod
    def status_class(self) -> str:  # 'success' | 'error' | 'warning' | 'info'
        ...

    # -- evidence --------------------------------------------------------------
    @abstractmethod
    def capture_screen(self) -> dict:
        """Machine-readable visual snapshot (rendered to SVG evidence by caller)."""
