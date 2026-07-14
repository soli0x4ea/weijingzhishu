"""DLC Protocol v1.0 — Shared Constants.

Single source of truth for module definitions used across
loader.py, resolver.py, and context.py.
"""
from __future__ import annotations

# Module → sub-keys that map to config file paths
MODULE_SUBKEYS = {
    "identity":    ["profile", "personality", "speech"],
    "body":        ["anatomy", "zones"],
    "engine":      ["entities", "modifiers", "thresholds", "narratives"],
    "memory":      [],
    "behavior":    ["lws_rules"],
    "interaction": ["commands", "items"],
    "vault":       ["secrets"],
}

# Module → required modules that must be enabled
MODULE_DEPENDENCIES = {
    "engine":      ["body"],
    "memory":      ["engine"],
    "behavior":    ["engine"],
    "interaction": ["engine"],
}

# Minimum modules required for each complexity level (ascending)
MODULE_LEVELS = [
    ("L0", {"identity"}),
    ("L1", {"identity", "body", "engine"}),
    ("L2", {"identity", "body", "engine", "memory", "behavior"}),
    ("L3", {"identity", "body", "engine", "memory", "behavior",
            "interaction"}),
]
