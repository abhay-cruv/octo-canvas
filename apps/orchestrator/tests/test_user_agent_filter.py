"""User-agent filter rule — slice 8 §calls #5."""

from orchestrator.services.event_store import is_important_for_user_agent


def test_finalized_assistant_message_is_important() -> None:
    # The user agent reads finalized assistant blocks to decide whether
    # the dev agent ended on a question worth auto-answering.
    assert is_important_for_user_agent("assistant.message") is True


def test_streaming_deltas_are_filtered_out() -> None:
    # Streaming chunks would burn the user agent's context.
    assert is_important_for_user_agent("assistant.delta") is False


def test_thinking_filtered_out() -> None:
    assert is_important_for_user_agent("thinking") is False


def test_tool_calls_filtered_out() -> None:
    assert is_important_for_user_agent("tool.started") is False
    assert is_important_for_user_agent("tool.finished") is False


def test_file_edits_filtered_out() -> None:
    assert is_important_for_user_agent("file.edit") is False


def test_result_and_error_pass_through() -> None:
    assert is_important_for_user_agent("result") is True
    assert is_important_for_user_agent("error") is True


def test_unknown_types_default_to_filtered_out() -> None:
    # Forward-compat — a future bridge type the orchestrator hasn't
    # learned about yet shouldn't accidentally route to the user agent.
    assert is_important_for_user_agent("future.unknown") is False
