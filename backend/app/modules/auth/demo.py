import os

from ...core.exceptions import DemoConfigurationError


def demo_mode_enabled():
    enabled = os.environ.get("HRIS_DEMO_MODE", "").strip().lower() in (
        "1", "true", "yes", "on"
    )
    vercel_environment = os.environ.get("VERCEL_ENV", "").strip().lower()
    if vercel_environment or os.environ.get("VERCEL"):
        return enabled and vercel_environment in ("preview", "production")
    return enabled


def demo_session_secret():
    secret = os.environ.get("HRIS_DEMO_SESSION_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise DemoConfigurationError(
            "HRIS_DEMO_SESSION_SECRET must contain at least 32 bytes when demo mode is enabled."
        )
    return secret
