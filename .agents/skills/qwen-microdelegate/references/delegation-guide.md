# Delegation guide

## Choose a microtask

The lead agent reads the parent ticket and owns design, interfaces, integration, and verification. Delegate a known one-file edit only after behavior is settled. Good examples include a guard clause, a small validation, a simple field mapping, or a focused test. Keep security, permissions, schema changes, concurrency, and ambiguous logic with the lead agent. Qwen proposals are untrusted code suggestions.

## Local setup

Install Ollama on the machine that runs the agent, then download `qwen2.5-coder:7b` and start Ollama. The helper calls `http://localhost:11434/api/chat` by default. It uses only the Python standard library and sends code only to a loopback HTTP address.

Optional environment variables: `QWEN_MODEL` (default `qwen2.5-coder:7b`), `OLLAMA_HOST` (default `http://localhost:11434`; a loopback base URL or full `/api/chat` URL), and `QWEN_TIMEOUT` (seconds, default `90`). The HTTP call is isolated in `request_edits`, so another local backend can replace it later.

## Propose, inspect, apply

From the repository root, make `.qwen-delegations` for local proposals. This example targets an existing test file in this repository and asks for one additional rejection case:

```text
python .agents/skills/qwen-microdelegate/scripts/delegate.py propose --task "Add a unit test that rejects a non-loopback OLLAMA_HOST" --expected "A configured https://example.com host returns a DelegationError without sending a request" --file .agents/skills/qwen-microdelegate/tests/test_delegate.py --output .qwen-delegations/task-001.json
python .agents/skills/qwen-microdelegate/scripts/delegate.py check --proposal .qwen-delegations/task-001.json
python .agents/skills/qwen-microdelegate/scripts/delegate.py apply --proposal .qwen-delegations/task-001.json
```

On Windows PowerShell, use `py` in place of `python` if that is how Python is installed. These are separate commands; the lead agent should inspect the displayed diff before `apply`. `propose` and `check` do not edit source. `apply` verifies the original source hash and exact old text again. A proposal becomes stale after any source change; request a fresh proposal instead of forcing it.

Use `--start-line N --end-line M` for a large source file. The selected excerpt must contain the code to change and stay under 12,000 characters. Each replacement must match exactly once in both the excerpt and the full file. The helper accepts at most five localized replacements in one file. Keep proposal files out of version control if they contain source excerpts.

Run the relevant tests, lint, or typecheck after applying. If the proposal is wrong or verification fails, the lead agent fixes or reverts it and completes the ticket. Retry Qwen at most once when a small clarification is likely to help.

The saved JSON and `check` diff are suitable inputs for a later local `gpt-oss:20b` review step. This skill does not run that reviewer; final verification remains with the lead agent.

## Antigravity

Open this repository in Antigravity and ask it to use `qwen-microdelegate` while implementing a ticket. If Antigravity does not discover repository skills automatically, point it to `.agents/skills/qwen-microdelegate/SKILL.md`. It can invoke the same Python commands in its terminal. The lead agent still chooses and verifies every edit.

## Parallel work

Run proposals sequentially by default. Independent tasks may be queued for later parallel execution, but dependent tasks and tasks touching the same file must remain sequential. The current helper processes one proposal at a time and sets no GPU concurrency.
