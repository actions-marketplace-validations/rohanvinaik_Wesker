# Execution and monitoring repair checkpoint

The shared plan and test-preservation ledger live in Detective's
`docs/EVIDENCE_FLOW_REPAIR_PLAN.md` and
`docs/REPAIR_REVIEW_LEDGER_2026-10-23.md`.

This checkpoint incorporates the reviewed earlier worktree changes: isolated
CLI/converged worker wiring and cleanup; timeout outcomes outside the scored
denominator; preserved execution facts during equivalence marking; policy 8
annotation exclusions; authoritative package globals; live patch-owner discovery;
and one original TCE key per converged pass.

Owned monitoring subscriptions replace the legacy coverage hooks. Observations
filter ownership before requesting a frame, retain faults for their owner, and
retire with the run token. Delivery admission is inside its cleanup boundary;
an interrupt after reservation cannot strand an in-flight entry. The aggregate
trace allowance bounds the current test as well as the untraced tail.

The pure measurement-entry decision was pinned on an unchanged function in a
renamed package copy: two-sign COMPLETE, 10/10 mutants killed, with fresh isolated
reproducibility confirmed. That synthesized pin characterizes the decision;
the handwritten baseline tests supply the separate intended behavior, including
the zero-valued active owner and both nested public-runner directions.

No W#32 closure is claimed. The before/after SAME matrix, supported interpreter
matrix and full cancellation/registry-lock audit remain open. Sampling and other
execution variants still need acceptance against the shared evidence contract.
W#40/W#42 scanning/allocation performance wins remain unmeasured; live rescanning
and copying are correctness choices here. Empirical mutant groups never justify
pruning the proof universe. No broad test-purge batch was accepted.

The full local pair was verified under each managed environment. Exact source
bases, command outcomes and complete logs are bound by Detective's checkpoint
results artifact. The local Sonar push gate is unavailable: its copied embedded
database cannot be upgraded by the installed server. Publishing and version
changes remain outside this work.
