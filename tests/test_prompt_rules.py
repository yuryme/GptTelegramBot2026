from app.llm.prompts import SEMANTIC_DRAFT_PROMPT_RU, SYSTEM_PROMPT_RU


def test_prompt_contains_time_dash_rule() -> None:
    assert "10-30" in SYSTEM_PROMPT_RU
    assert "create_reminders" in SYSTEM_PROMPT_RU
    assert "list_reminders" in SYSTEM_PROMPT_RU


def test_prompt_contains_delete_contract_fields() -> None:
    assert "pending/done/deleted" in SYSTEM_PROMPT_RU
    assert "reminder_id" in SYSTEM_PROMPT_RU
    assert "confirm_delete_all=true" in SYSTEM_PROMPT_RU


def test_semantic_prompt_contains_list_delete_range_contract() -> None:
    assert "list_reminders" in SEMANTIC_DRAFT_PROMPT_RU
    assert "delete_reminders" in SEMANTIC_DRAFT_PROMPT_RU
    assert "from_dt" in SEMANTIC_DRAFT_PROMPT_RU
    assert "to_dt" in SEMANTIC_DRAFT_PROMPT_RU
    assert "confirm_delete_all=true" in SEMANTIC_DRAFT_PROMPT_RU
    assert "сегодня после 21 часа" in SEMANTIC_DRAFT_PROMPT_RU
    assert "сегодня до 21 часа" in SEMANTIC_DRAFT_PROMPT_RU
    assert "Combined list filters" in SEMANTIC_DRAFT_PROMPT_RU
    assert "на сегодня в статусе ожидании" in SEMANTIC_DRAFT_PROMPT_RU
    assert '"status":"pending"' in SEMANTIC_DRAFT_PROMPT_RU
    assert "после <date>" in SEMANTIC_DRAFT_PROMPT_RU
    assert "с <date>" in SEMANTIC_DRAFT_PROMPT_RU
    assert "включительно" in SEMANTIC_DRAFT_PROMPT_RU
    assert "после 27 мая 2026 года" in SEMANTIC_DRAFT_PROMPT_RU


def test_semantic_prompt_keeps_llm_only_contract() -> None:
    assert "passthrough_command" in SEMANTIC_DRAFT_PROMPT_RU
    assert "Use ISO datetimes with timezone offset" in SEMANTIC_DRAFT_PROMPT_RU
    assert "Never use legacy keys" in SEMANTIC_DRAFT_PROMPT_RU
    assert "Do not rely on Python phrase parsing" in SEMANTIC_DRAFT_PROMPT_RU
    assert "never output final command fields" in SEMANTIC_DRAFT_PROMPT_RU
    assert "prefer schedule with normalized ISO datetimes" in SEMANTIC_DRAFT_PROMPT_RU
    assert "Do not generate an occurrences array" in SEMANTIC_DRAFT_PROMPT_RU


def test_semantic_prompt_contains_search_and_recurrence_disambiguation() -> None:
    assert "Search vs date/time" in SEMANTIC_DRAFT_PROMPT_RU
    assert "где упоминается" in SEMANTIC_DRAFT_PROMPT_RU
    assert "каждые N минут" in SEMANTIC_DRAFT_PROMPT_RU
    assert "каждые полчаса" in SEMANTIC_DRAFT_PROMPT_RU
    assert "frequency=\"minutely\"" in SEMANTIC_DRAFT_PROMPT_RU
    assert "до следующей недели" in SEMANTIC_DRAFT_PROMPT_RU
