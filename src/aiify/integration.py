"""Small host adapters: configuration only; actions and science stay in the app.

The host supplies packaged, verified assets. No generation, network calls or
model starts happen here. A JSON environment option configures startup defaults;
the shared panel switches the available helpers within the running application.
"""
from __future__ import annotations

import json
import os
import ipaddress
from pathlib import Path


def helper_options(package: str | Path, *, env: str, routes=(), overrides=None) -> dict:
    """Agent kwargs for shipped assets and strictly typed, inexpensive defaults.

``env`` names an app-specific variable, e.g. ``PYMICROGLIA_AIIFY_OPTIONS``.
Its JSON object and ``overrides`` accept how/app_map/prepared/routes booleans.
Route opt-in cannot widen the host's explicitly permitted paths.
"""
    defaults = {"how": True, "app_map": True, "prepared": True, "routes": False}
    configured = json.loads(os.environ.get(env, "{}"))
    for values in (configured, overrides if overrides is not None else {}):
        if not isinstance(values, dict) or set(values) - set(defaults):
            raise ValueError(f"{env}: choose how, app_map, prepared or routes")
        if any(type(value) is not bool for value in values.values()):
            raise ValueError(f"{env}: helper values must be true or false")
        defaults.update(values)
    package = Path(package)
    bundle = package / "aiify_prepared"
    if defaults["routes"] and not routes:
        raise ValueError(f"{env}: this host has not permitted route actions")
    return {"how": defaults["how"], "app_map": package / "aiify_map.md",
            # A bundle being generated has a folder before it has a verification
            # receipt. Do not let that unfinished optional helper prevent chat.
            # Existing receipts still undergo full validation in load_prepared.
            "prepared": bundle if (bundle / "verification.json").is_file() else None, "routes": False,
            "route_options": tuple(routes), "helper_defaults": defaults}


def protect_local_assistant(app, *, prefixes=("/aiify",)) -> None:
    """Keep filesystem-capable agents local when the ordinary app serves a LAN.

Only assistant transport paths are affected; host APIs retain their own rules.
The connection peer is checked, rather than a client-supplied Host header.
"""
    class LocalAssistant:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            path = scope.get("path", "")
            protected = any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)
            peer = (scope.get("client") or ("",))[0]
            try:
                address = ipaddress.ip_address(peer)
                local = address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
            except ValueError:
                # Starlette's in-process test transport has no network peer.
                local = peer == "testclient"
            if protected and scope["type"] in ("http", "websocket") and not local:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    from starlette.responses import JSONResponse
                    await JSONResponse({"ok": False, "error": "The assistant is available on this computer only."}, status_code=403)(scope, receive, send)
                return
            await self.app(scope, receive, send)

    app.add_middleware(LocalAssistant)
