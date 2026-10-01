"""ai-ify: embed a subscription-backed AI agent inside any app.

Install name ``ai-ify``, import name ``aiify``. Importing this package starts
nothing: no port, no agent process, no web routes.

    from aiify import Agent, Profile, When, Launch
"""
__version__ = "0.1.0"

__all__ = ["__version__", "Agent", "Profile", "When", "Launch", "Turn", "Policy"]


def __getattr__(name):
    if name == "Agent":
        from .agent import Agent
        return Agent
    if name in ("Profile", "When", "Launch", "Turn"):
        from . import profile
        return getattr(profile, name)
    if name == "Policy":
        from .policy import Policy
        return Policy
    raise AttributeError(f"module 'aiify' has no attribute {name!r}")
