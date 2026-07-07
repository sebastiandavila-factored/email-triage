from types import SimpleNamespace
from unittest.mock import patch

from email_triage import deps
from email_triage.deps import assert_category_coverage, get_system_prompt
from email_triage.schemas import Category
from email_triage.services.llm import SYSTEM_PROMPT, LLMService


def test_get_system_prompt_falls_back_to_code_default() -> None:
    # Simulate Logfire having no managed variable: .get() returns the default.
    get_system_prompt.cache_clear()
    resolved = SimpleNamespace(value=SYSTEM_PROMPT, reason="code_default")
    with patch.object(deps._SYSTEM_PROMPT_VAR, "get", return_value=resolved):  # pyright: ignore[reportPrivateUsage]
        prompt = get_system_prompt()
    assert prompt == SYSTEM_PROMPT
    for category in Category:
        assert category.value in prompt
    get_system_prompt.cache_clear()


def test_system_prompt_resolved_once_per_process() -> None:
    # @lru_cache + lifespan warm-up guarantees a single resolution, never per request.
    get_system_prompt.cache_clear()
    resolved = SimpleNamespace(value="RESOLVED PROMPT", reason="label")
    with patch.object(deps._SYSTEM_PROMPT_VAR, "get", return_value=resolved) as mock_get:  # pyright: ignore[reportPrivateUsage]
        first = get_system_prompt()
        second = get_system_prompt()
    assert first == second == "RESOLVED PROMPT"
    assert mock_get.call_count == 1
    get_system_prompt.cache_clear()


def test_get_system_prompt_uses_configured_label() -> None:
    get_system_prompt.cache_clear()
    resolved = SimpleNamespace(value=SYSTEM_PROMPT, reason="label")
    with patch.object(deps._SYSTEM_PROMPT_VAR, "get", return_value=resolved) as mock_get:  # pyright: ignore[reportPrivateUsage]
        get_system_prompt()
    mock_get.assert_called_once_with(label="production")
    get_system_prompt.cache_clear()


def test_category_drift_guard_warns_and_does_not_raise() -> None:
    with patch.object(deps, "_log") as mock_log:
        assert_category_coverage("Only mentions status and refunds.")
    mock_log.warning.assert_called_once()
    missing = mock_log.warning.call_args.kwargs["missing_categories"]
    assert "availability" in missing
    assert "shipments" in missing
    assert "prices" in missing
    assert "status" not in missing


def test_category_drift_guard_silent_when_complete() -> None:
    full = " ".join(c.value for c in Category)
    with patch.object(deps, "_log") as mock_log:
        assert_category_coverage(full)
    mock_log.warning.assert_not_called()


def test_llm_service_builds_agent_with_system_prompt() -> None:
    service = LLMService(api_key="test-key", system_prompt="MARKER_PROMPT")
    assert "MARKER_PROMPT" in service._agent._system_prompts  # type: ignore[attr-defined]
