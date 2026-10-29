---
name: ticket-router
description: Route implementation tickets produced by to-tickets to qwen7b, antigravity, or codex. Use after ticket generation when executor metadata must be assigned without changing ticket requirements.
---

# Ticket Router

Route the complete set of implementation tickets produced by `to-tickets`. This skill assigns work; it does not rewrite or split tickets.

## Process

1. Identify the generated ticket set from the current handoff, parent issue, or tracker. Read **every ticket's full body**, including acceptance criteria and blockers. If the set cannot be identified reliably, ask for the ticket references before editing.
2. Assess each ticket's decision load, likely blast radius, uncertainty, and failure impact. Use repository context when the ticket alone does not reveal these. Apply the highest applicable executor tier below; when uncertain between tiers, choose the more capable executor. Do not change a ticket to make it fit a tier.
3. Add or update one `Routing` section in each ticket. Keep its title, scope, requirements, acceptance criteria, blocking relationships, status, and other existing content intact. Preserve existing metadata outside this section. Do not change the parent issue or tracker relationships.
4. Read back the complete set. Confirm every generated ticket has exactly one valid value for each routing field, no duplicate routing section, and unchanged requirements and blockers. Report ticket identifiers and assignments.

## Executor tiers

| Executor | Use when |
| --- | --- |
| `qwen7b` | Deterministic, objective work with a small blast radius, normally one or two related files: conditions, loops, validation, helpers, small tests, simple UI changes, or type fixes. No architecture choice, security or auth concern, database migration, or distributed state concern. |
| `antigravity` | Medium complexity with settled requirements. Repository navigation, several related files, debugging, or test iteration may be needed, but no major architecture decision is required. |
| `codex` | Architecture choices, broad refactors, ambiguous requirements, security, auth, permissions, significant database migrations, concurrency or distributed state, high-risk changes, or complex debugging with an unknown root cause. |

Classification is per ticket, based on the work it actually asks for. A small-looking edit with a higher-tier concern goes to the higher tier. Do not infer that a blocker or parent ticket's executor must match its dependents.

## Metadata

Append a distinct `## Routing` section outside the requirements and acceptance criteria. Use these exact keys and allowed values, one value per key:

| Key | Allowed values |
| --- | --- |
| `executor` | `qwen7b`, `antigravity`, `codex` |
| `complexity` | `xs`, `s`, `m`, `l` |
| `reviewer` | `gpt-oss-20b`, `none` |
| `fallback` | `antigravity`, `codex`, `none` |
| `risk` | `low`, `medium`, `high` |

For example, a small deterministic ticket receives:

```text
## Routing

executor: qwen7b
complexity: s
reviewer: gpt-oss-20b
fallback: antigravity
risk: low
```

Use `xs` for a trivial localized edit, `s` for a small contained change, `m` for several coordinated steps, and `l` for broad or difficult work. Assess `risk` separately from effort: `low` has limited, easily reversible impact; `medium` can affect an established workflow; `high` can cause significant data, security, availability, or cross-system harm.

Normally assign `reviewer: gpt-oss-20b` and `fallback: antigravity` to `qwen7b`; assign `reviewer: none` and `fallback: codex` to `antigravity`; assign `reviewer: none` and `fallback: none` to `codex`. Depart from a normal reviewer or fallback only when the ticket provides a concrete reason, and explain the exception in the routing report. Never assign more than one executor or fallback.
