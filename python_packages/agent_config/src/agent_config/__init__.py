"""Static configuration consumed by the bridge / agent runtime.

Slice 7 fills in the Protocol + impls for Claude credentials, the
dev-agent prompt template, and the canonical tool allowlist. Slice 8's
bridge imports from here on every session spawn; nothing in this
package is wired to a running agent yet.
"""

from agent_config.credentials import (
    ClaudeCredentials,
    CredentialsError,
    PlatformApiKeyCredentials,
)
from agent_config.prompts import DevAgentPromptInputs, render_dev_agent_prompt
from agent_config.tools import DEV_AGENT_TOOL_ALLOWLIST

__all__ = [
    "DEV_AGENT_TOOL_ALLOWLIST",
    "ClaudeCredentials",
    "CredentialsError",
    "DevAgentPromptInputs",
    "PlatformApiKeyCredentials",
    "render_dev_agent_prompt",
]
