def test_imports() -> None:
    import agent_config

    assert agent_config is not None
    # Public surface: explicit re-exports stay stable so slice 8 can rely on them.
    for sym in (
        "ClaudeCredentials",
        "PlatformApiKeyCredentials",
        "DEV_AGENT_TOOL_ALLOWLIST",
        "DevAgentPromptInputs",
        "render_dev_agent_prompt",
    ):
        assert hasattr(agent_config, sym), sym
