import ipaddress
import os
import re
from urllib.parse import urlsplit


def normalize_origin(value, require_https=False):
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except (AttributeError, ValueError):
        return None
    scheme = parsed.scheme.lower()
    if (
        scheme not in ("http", "https")
        or (require_https and scheme != "https")
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    hostname = hostname.lower()
    if ":" in hostname:
        try:
            hostname = str(ipaddress.IPv6Address(hostname))
        except ipaddress.AddressValueError:
            return None
        hostname = "[" + hostname + "]"
    elif not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*",
        hostname,
    ):
        return None
    if port is not None and port != (443 if scheme == "https" else 80):
        hostname += ":" + str(port)
    return scheme + "://" + hostname


def vercel_origin(domain):
    domain = domain.strip().lower()
    if (
        not domain
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain)
        or ".." in domain
    ):
        return None
    return "https://" + domain


def secure_cookie_attribute():
    return (
        os.environ.get("VERCEL_ENV") in ("production", "preview")
        or os.environ.get("HRIS_DEPLOYMENT", "").strip().lower() == "render"
    )


def validate_render_allowed_origins(value=None):
    if value is None:
        value = os.environ.get("HRIS_ALLOWED_ORIGINS", "")
    configured = [item.strip() for item in value.split(",")]
    if not configured or any(not item for item in configured):
        raise ValueError(
            "HRIS_ALLOWED_ORIGINS must contain HTTPS origins for Render."
        )
    if any(normalize_origin(item, require_https=True) is None for item in configured):
        raise ValueError(
            "HRIS_ALLOWED_ORIGINS must contain only exact HTTPS origins for Render."
        )
    return tuple(normalize_origin(item, require_https=True) for item in configured)


def is_valid_origin(origin, host, port):
    if not origin:
        return False
    is_render_deployment = (
        os.environ.get("HRIS_DEPLOYMENT", "").strip().lower() == "render"
    )
    is_vercel_deployment = not is_render_deployment and any(
        os.environ.get(name)
        for name in (
            "VERCEL",
            "VERCEL_URL",
            "VERCEL_PROJECT_PRODUCTION_URL",
        )
    )
    normalized_origin = normalize_origin(
        origin, require_https=is_vercel_deployment or is_render_deployment
    )
    if not normalized_origin:
        return False

    configured_origins = [
        item.strip()
        for item in os.environ.get("HRIS_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    ]
    allowed_origins = set()
    for configured_origin in configured_origins:
        normalized = normalize_origin(
            configured_origin,
            require_https=is_vercel_deployment or is_render_deployment,
        )
        if normalized:
            allowed_origins.add(normalized)

    if is_vercel_deployment:
        deployment_origin = vercel_origin(os.environ.get("VERCEL_URL", ""))
        if deployment_origin:
            allowed_origins.add(deployment_origin)
        if os.environ.get("VERCEL_ENV") == "production":
            production_origin = vercel_origin(
                os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "")
            )
            if production_origin:
                allowed_origins.add(production_origin)
    elif not is_render_deployment and not configured_origins:
        local_origin = normalize_origin("http://{}:{}".format(host, port))
        if local_origin:
            allowed_origins.add(local_origin)
    return normalized_origin in allowed_origins
