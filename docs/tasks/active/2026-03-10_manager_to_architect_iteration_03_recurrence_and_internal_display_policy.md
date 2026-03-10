# Iteration 3 Recurrence And Internal Display Policy Task

- Date: `2026-03-10`
- From: `manager`
- To: `architect`
- Status: `approved`
- Topic: `iteration_03_recurrence_and_internal_display_policy`
- Goal: `Introduce explicit internal recurrence and display policy models without changing the external command JSON contract`

## Context

After iteration 2, the system already has:
- one LLM call for natural-language understanding;
- a strict semantic draft JSON;
- deterministic compilation into the final command JSON;
- centralized temporal normalization.

However, recurrence and delivery behavior are still architecturally weak:
- recurrence is mostly represented by `recurrence_rule`;
- pre-reminders are created by hidden runtime logic;
- delivery/show policy is not modeled as a first-class concept;
- complex recurring Russian phrases are hard to extend safely.

## Decision / Task

Create a new internal layer for:
- recurrence modeling;
- internal display policy modeling.

The system must explicitly separate:
- when the reminder should happen;
- how often it repeats;
- how it should be shown to the user.

At this stage, `display policy` must remain an internal model only.
Do not extend the external final command JSON with a new public `display_policy` field yet.

## Scope

- Design an internal recurrence model that is richer than a plain `recurrence_rule` string.
- Design an internal display policy model for reminder delivery behavior.
- Update the semantic draft pipeline so recurring intent and delivery hints can be extracted and compiled deterministically.
- Rework the deterministic compiler so it produces:
  - execution schedule data;
  - recurrence data;
  - internal display policy data.
- Preserve backward compatibility for existing external create-command behavior.
- Keep existing `run_at` / `recurrence_rule` compatibility where needed as legacy support.
- Move hidden pre-reminder behavior toward explicit internal display-policy handling.
- Focus on create-reminder scenarios.

## What Must Be Modeled Internally

At minimum, the internal domain model should explicitly represent:
- one-time reminder vs recurring reminder;
- recurrence frequency;
- recurrence interval;
- recurrence end condition;
- user-facing reminder time;
- internal pre-reminder strategy / delivery behavior.

Field names may vary, but this separation must exist in code.

## Hard Rules

- LLM is still called only once.
- LLM still returns strict JSON only.
- After the LLM response, only deterministic Python code is allowed.
- `display policy` must be implemented as an internal domain model, not a new public command field yet.
- Recurrence and delivery logic must not depend on scattered ad hoc conditionals across services.
- Runtime hidden logic should be reduced and replaced by explicit internal models.

## Supported Scenarios

The architecture must be able to support cases such as:
- `Напомни завтра в 10 купить молоко`
- `Напоминай каждый день в 9 пить воду`
- `Напоминай каждый будний день в 8 делать зарядку`
- `Напоминай каждый вторник и четверг в 19 о тренировке`
- `Напоминай каждый месяц 10 числа в 9 поздравлять коллег`
- `Напомни завтра в 18 и за час до этого`
- `Напоминай каждый день в 9 до конца месяца`
- `Напоминай по будням в 9 без преднапоминания`
- `Напоминай каждую неделю в среду в 10`

## Out Of Scope

- Public external JSON redesign for display policy.
- Full Telegram UX redesign.
- Full migration of list/delete flows.
- Enterprise-grade calendar rule coverage.
- Multi-channel delivery redesign.
- Rewriting the project from scratch.

## Acceptance

- A dedicated internal recurrence model exists in code.
- A dedicated internal display policy model exists in code.
- Pre-reminder behavior is no longer only an implicit runtime trick.
- Recurring Russian phrases are processed through a general internal model rather than narrow patches.
- Existing baseline create-reminder behavior remains backward compatible.
- Automated tests cover recurring and delivery-policy scenarios.
- `README.md` and `PROJECT_PLAN.md` are updated.

## Mandatory Test Cases

- `Напоминай каждый день в 9 пить воду`
- `Напоминай каждый будний день в 8 делать зарядку`
- `Напоминай каждый вторник и четверг в 19 о тренировке`
- `Напомни завтра в 18 и за час до этого`
- `Напоминай каждый день в 9 до конца месяца`
- `Напоминай по будням в 9 без преднапоминания`
- `Напоминай каждую неделю в среду в 10`

For each case, tests must verify:
- semantic draft correctness where relevant;
- compiled internal recurrence model correctness;
- compiled internal display policy correctness;
- final executable behavior correctness.

## Notes

- This iteration must not introduce a new public `display_policy` field in the external command JSON.
- Internal modeling comes first; public contract expansion may be considered in a later iteration.
- The purpose of this iteration is to replace hidden runtime behavior with explicit internal architecture.
