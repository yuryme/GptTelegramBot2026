# Iteration 2 Semantic Draft Layer Task

- Date: `2026-03-10`
- From: `manager`
- To: `architect`
- Status: `approved`
- Topic: `iteration_02_semantic_draft_layer`
- Goal: `Introduce a strict JSON semantic draft layer between LLM understanding and the final executable command JSON`

## Context

Iteration 1 centralized temporal normalization and reduced scattered date/time heuristics. The next architectural bottleneck remains unchanged: the LLM is still expected to both understand a natural-language Russian phrase and immediately produce the final strict command JSON. This makes the system fragile on complex phrases where reminder text, temporal markers, recurrence hints, and contextual words are mixed together.

We need to separate:
- natural-language understanding;
- deterministic compilation into the final command JSON.

## Decision / Task

Introduce a new internal schema-first layer called `semantic draft`.

The LLM must be called once per user phrase and must return only a strict JSON object that represents extracted meaning, not the final executable command.

After that, regular deterministic Python code must:
- validate the semantic draft;
- normalize temporal data;
- compile the draft into the current final command JSON;
- pass the compiled command into the existing execution flow.

No second LLM call is allowed for `draft -> final command` compilation.

## Scope

- Design a strict JSON schema for the semantic draft of create-reminder scenarios.
- Implement a new internal draft model, for example `SemanticCommandDraft` / `CreateReminderDraft`.
- The semantic draft must remain JSON-only and schema-first.
- Update the LLM pipeline so that the model returns the semantic draft JSON instead of the final executable create-command JSON.
- Implement deterministic Python compilation from semantic draft JSON into the current final command JSON.
- Keep the external bot behavior and public command contract backward compatible.
- Reuse the temporal normalization layer from iteration 1 as part of the draft compilation pipeline.
- Focus this iteration on `create_reminders` scenarios first.
- Prepare the architecture for future recurrence/display-policy expansion without implementing the full redesign yet.

## Required Semantic Draft Properties

The draft must be a strict JSON response with a fixed schema.

At minimum, it must separate:
- `intent`
- `reminder_text`
- `day_expression`
- `time_expression`
- `date_expression`
- `recurrence_expression`
- `raw_context` or equivalent field if needed for non-temporal fragments that should not be mistaken for scheduling data

The exact field names may differ, but the separation of meaning must exist explicitly in the schema.

## Hard Rules

- The LLM must return JSON only.
- No markdown, no explanations, no free text.
- The semantic draft must have its own explicit schema and validation layer.
- The compiler from semantic draft to final command must be deterministic Python code.
- No second LLM stage is allowed after semantic draft extraction.
- Temporal normalization must not be duplicated again inside the compiler if it already belongs to the normalizer layer.
- Existing final command JSON compatibility must be preserved for this iteration.

## Out Of Scope

- Full redesign of the external command JSON contract.
- Full recurrence engine redesign.
- Full display-policy redesign.
- Telegram UX changes.
- Full migration of list/delete flows, unless needed for safe internal abstraction boundaries.
- Rewriting the project from scratch.

## Acceptance

- A new semantic draft schema exists in code and is validated explicitly.
- The LLM is used once to produce semantic draft JSON, not the final create-command JSON directly.
- `draft -> final command` compilation is implemented in deterministic Python code.
- The existing create flow remains backward compatible at the external contract level.
- Complex Russian phrases are covered by tests where reminder text and temporal markers coexist in one phrase.
- Documentation is updated in `README.md` and `PROJECT_PLAN.md`.

## Mandatory Test Cases

- `Напомни в среду в десять утра, сегодня едем к Олегу`
- `Завтра напомни, что встреча в пятницу в 15`
- `Напомни 10 марта поздравить маму в 9 утра`
- `Напомни купить лекарства, когда буду у врача`
- `Напомни в пятницу созвон с командой, встреча в тексте не должна стать датой`

For each case, tests must verify both:
- semantic draft correctness;
- final compiled command correctness.

## Notes

- The purpose of this iteration is not to remove JSON, but to introduce two controlled JSON layers:
- semantic draft JSON for meaning extraction;
- final command JSON for execution.
- This iteration should make it easier to detect whether an error happened:
- during language understanding;
- during deterministic compilation into the final command.
- The result of this iteration should become the architectural base for iteration 3, where recurrence and display scheduling can be redesigned more safely.
