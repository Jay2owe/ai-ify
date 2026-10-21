"""Framework-independent access to the shared chat panel's public assets."""
from pathlib import Path


def static_asset(name: str) -> Path:
    """Return a shipped panel asset; hosts serve it using their own authentication.

    This does not import the agent engine or start a web server. Only the panel
    and native launch controls are exposed here.
    """
    if name not in ("panel.js", "panel.css", "launch-controls.js"):
        raise ValueError(f"unknown panel asset: {name}")
    return Path(__file__).with_name("static") / name
