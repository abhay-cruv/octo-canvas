"""User-agent event filter — slice 8 §calls #5.

Re-exports the routing decision from `event_store` so the user-agent
package owns its filter rule explicitly. Anything outside this set is
NOT forwarded to the user agent (would burn its context for no
decision benefit).
"""

from orchestrator.services.event_store import is_important_for_user_agent

__all__ = ["is_important_for_user_agent"]
