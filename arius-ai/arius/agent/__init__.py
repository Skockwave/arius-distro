"""The autonomous agent: observe the machine and the Minecraft server, think with
the LLM, act through a small, bounded set of tools.

Safety by construction:
  * no tool can run arbitrary shell commands, write or delete files;
  * console (RCON) commands are limited to an allowlist;
  * every state change asks for confirmation unless the user explicitly
    allowed that tool for autonomous runs (agent.auto_allow);
  * RBAC still applies on top — the agent never exceeds the logged-in role.

    tools.py      - the tool registry and what each tool may touch
    loop.py       - the think/act loop and the autonomy gate
    heartbeat.py  - periodic self-check driven by the user's standing policies
"""

from arius.agent.loop import AgentLoop, AgentResult, parse_action
from arius.agent.tools import Refused, Tool, ToolContext, build_registry

__all__ = ["AgentLoop", "AgentResult", "parse_action", "Refused", "Tool", "ToolContext", "build_registry"]
