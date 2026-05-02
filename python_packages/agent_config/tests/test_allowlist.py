from agent_config import DEV_AGENT_TOOL_ALLOWLIST


def test_allowlist_is_frozen_tuple_with_expected_members() -> None:
    assert isinstance(DEV_AGENT_TOOL_ALLOWLIST, tuple)
    assert "Bash" in DEV_AGENT_TOOL_ALLOWLIST
    assert "ask_user_clarification" in DEV_AGENT_TOOL_ALLOWLIST
    # Frozen — no surprise duplicates.
    assert len(DEV_AGENT_TOOL_ALLOWLIST) == len(set(DEV_AGENT_TOOL_ALLOWLIST))
