---
name: agy-ticket-simplifier
description: Simplify existing tickets routed to Antigravity into small, implementation-ready tickets after Codex resolves architecture and repository context. Use when optimizing Antigravity workload or quota, not for initial ticket generation or general routing.
---

# Antigravity Ticket Simplifier

Turn an existing `executor: antigravity` ticket into the smallest *cohesive* set of implementation tickets that preserves its specification. Codex owns the analysis and integration; Antigravity receives settled decisions and a narrow file scope. If the existing ticket is already economical, enrich it rather than splitting it.

## Analyze the source

1. Identify the source ticket and its parent specification. Read their full bodies, acceptance criteria, blockers, and relevant comments. Read the repository's issue-tracker, triage, domain, and routing conventions where present. If the source set is unclear, request the ticket reference.
2. Inspect only the repository area needed to resolve the work: structure, relevant functions/classes/interfaces, dependencies, tests, and operational configuration. Settle architecture, data contracts, compatibility, error handling, and integration risks before writing tickets. Keep security, migrations, distributed state, and uncertain cross-module integration with Codex.
3. Map **every** source acceptance criterion to one or more proposed tickets and an observable verification step. Preserve the original specification and existing blocker relationships. Make the proposed graph acyclic and give each new ticket only blockers that actually gate it. Avoid overlapping file edits unless a real dependency requires them.

## Decompose and assign

Each ticket has one independently verifiable objective and a coherent, narrow file scope. Prefer a small end-to-end behavior over a layer-only chore where practical. Split only when it reduces Antigravity's reading, reasoning, or debugging burden without adding more coordination work than it saves. A shared architecture note is useful only when several tickets need the same non-obvious decisions; otherwise put the decisions in the tickets.

Classify every proposed ticket by its *actual* work:

- **LOCAL:** deterministic, contained changes. Route with the repository's ticket-router rules, usually `qwen7b`.
- **ANTIGRAVITY:** moderate implementation with settled decisions and focused context. Route `antigravity`.
- **CODEX:** architecture, ambiguous behavior, difficult debugging, significant migration or data integrity risk, security/permissions, or integration. Route `codex`.

Only ANTIGRAVITY tickets go to Antigravity. Codex retains integration verification and any remaining decisions. Do not shrink acceptance criteria to make a ticket fit a cheaper executor. Use `ticket-router` metadata values and defaults; preserve metadata outside `## Routing`.

## Ticket body

Use the configured tracker and Matt Pocock issue conventions. For each ticket include:

- **Objective / What to build:** one observable outcome.
- **Repository context:** exact relevant paths and what each contributes.
- **Existing interfaces:** functions, classes, models, services, or commands to reuse.
- **Implementation instructions:** chosen changes, expected inputs/outputs, error handling, data fields, and compatibility constraints as applicable. Resolve choices here instead of asking Antigravity to compare alternatives.
- **Files allowed to change:** expected files; permit additional files only when strictly required for correctness and require the implementer to report them.
- **Dependencies / Blocked by:** exact ticket or issue identifiers, or none.
- **Acceptance criteria:** short, measurable checks, including the source criteria this ticket covers.
- **Verification:** the smallest relevant command, with an observable expected result. Reserve broad integration checks for the Codex ticket.
- **Stop conditions:** concrete surprises that require Antigravity to report a blocker rather than redesign the solution.
- **Routing:** exactly one valid `## Routing` section with `executor`, `complexity`, `reviewer`, `fallback`, and `risk` per `ticket-router`.

Point Antigravity to these paths and the ticket. Its normal `/implement` workflow can handle execution; the ticket should remove the need for a fresh plan, repository-wide search, unrelated documentation, or repeated full-suite runs. Do not impose token estimates.

## Deliver and publish

Show a brief architecture summary, dependency graph, proposed tickets, execution order, agent assignments, and why this reduces Antigravity's work. Include a source-criterion-to-ticket coverage map and identify the Codex integration gate. If published tracker tickets already exist, explain how the source ticket and downstream blockers will remain coherent; do not leave duplicate ready work or silently change parent issues. Follow the user's requested draft or publication scope and the tracker workflow for external edits. Read back any published tickets to verify routing fields, links, coverage, and unchanged requirements.

Stop after producing or publishing the tickets. Do not implement them.
