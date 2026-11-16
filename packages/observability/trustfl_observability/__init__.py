"""Optional, dependency-free observability primitives for TrustFL."""

from .metrics import metrics
from .tracing import TraceContext, trace_context

__all__ = ["TraceContext", "metrics", "trace_context"]
