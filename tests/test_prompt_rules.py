from app.llm.prompts import SYSTEM_PROMPT_RU


def test_prompt_contains_time_dash_rule() -> None:
    assert "10-30" in SYSTEM_PROMPT_RU
    assert "create_reminders" in SYSTEM_PROMPT_RU
    assert "list_reminders" in SYSTEM_PROMPT_RU
