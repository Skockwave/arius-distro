"""ARIUS - Adaptive Responsive Intelligent User System.

A JARVIS-style local AI assistant with role-based access control (RBAC),
persistent memory/learning, an extensible skill system, and pluggable
LLM backends.

The whole core runs on the Python standard library alone (offline "echo"
backend), so it works out of the box. Add an API key and the optional
``anthropic`` package to unlock a real conversational model.
"""

from arius.config import AriusConfig, load_config
from arius.core import Arius

__all__ = ["Arius", "AriusConfig", "load_config", "__version__"]

__version__ = "0.1.0"
