"""W3C trace-context propagation without requiring an exporter at runtime."""

from __future__ import annotations

import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass

_TRACEPARENT = re.compile(r"^[\da-f]{2}-([\da-f]{32})-([\da-f]{16})-[\da-f]{2}$")
_current: ContextVar[TraceContext | None] = ContextVar("trustfl_trace", default=None)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str

    @property
    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-01"


def trace_context(header: str | None = None) -> TraceContext:
    if header:
        match = _TRACEPARENT.match(header.strip().lower())
        if match:
            context = TraceContext(match.group(1), secrets.token_hex(8))
            _current.set(context)
            return context
    context = TraceContext(secrets.token_hex(16), secrets.token_hex(8))
    _current.set(context)
    return context


def current_trace() -> TraceContext | None:
    return _current.get()
