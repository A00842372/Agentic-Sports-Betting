---
name: qwen-microdelegate
description: Consider local Qwen2.5-Coder-7B for small, low-risk, well-specified edits inside an engineering ticket while the lead agent owns design, integration, and verification.
---

# Qwen Microdelegate

Before implementing a ticket, read it and identify any small, mechanical edits with settled behavior. Delegate only when the target file or function is known, the task is local and low risk, the prompt is short, and the result can be checked. Delegation is optional when doing the work directly is faster.

Keep architecture, ambiguous behavior, security and authorization, migrations, concurrency, outage logic, broad refactors, and complex debugging with the lead agent. The ticket remains authoritative. Never change its requirements to create Qwen work.

For an eligible edit, use `scripts/delegate.py propose` to obtain a JSON proposal and diff from local Ollama. Inspect the diff and use `check` before the lead agent explicitly runs `apply`. Run relevant verification and finish the parent ticket yourself. Qwen has no command execution or repository write access through this helper.

If a request fails or its output is invalid, retry at most once when a small prompt correction is likely to help; otherwise implement directly. Use sequential delegations by default. Do not delegate dependent tasks at the same time or edit the same file concurrently.

Read [references/delegation-guide.md](references/delegation-guide.md) for setup, command examples, prompt scope, and Antigravity use.
