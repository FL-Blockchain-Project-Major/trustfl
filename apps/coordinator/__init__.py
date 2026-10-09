"""
TrustFL Coordinator Application Package.
"""

try:
    from .coordinator import create_server_app, run_simulation
except ImportError:
    try:
        from apps.coordinator.coordinator import create_server_app, run_simulation
    except ImportError:
        # Network layer only — FL core may not be on path
        create_server_app = None  # type: ignore[assignment]
        run_simulation = None  # type: ignore[assignment]

__all__ = ["create_server_app", "run_simulation"]
