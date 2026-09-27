"""
TrustFL Client Application Package.
"""

try:
    from .client import TrustFLClient, create_client_app
except ImportError:
    try:
        from apps.client.client import TrustFLClient, create_client_app
    except ImportError:
        # Network layer only — FL core may not be on path
        TrustFLClient = None       # type: ignore[assignment,misc]
        create_client_app = None   # type: ignore[assignment]

__all__ = ["TrustFLClient", "create_client_app"]
