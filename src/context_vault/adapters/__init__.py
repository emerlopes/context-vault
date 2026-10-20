"""Agent adapters: install the canonical `context-vault` skill where each agent discovers skills."""

from .agents import AGENTS, AgentSpec, resolve_agents
from .installer import install, package, status, uninstall

__all__ = ["AGENTS", "AgentSpec", "install", "package", "resolve_agents", "status", "uninstall"]
