# Phase009 independent Security/Reliability evidence

STATUS: PASS for the bounded Security/Reliability review after independent repair closure. Both reproduced defects below are closed. Full acceptance gates and remote CI remain separate Director/QA claims. This reviewer made no production changes or publication.

## Findings

### SEC009-1 — High, CLOSED: future cancellation lifecycle evidence suppresses execution and releases funds early

`runtime/engine.py:330-339` checks broker fill history and calls accounting boundary validation before execution. `accounting/engine.py:125-128` validates accounting time but does not compare broker cancellation times with that boundary. `_validate_orders` at lines 459-465 removes status/cancellation metadata while comparing activation facts. `_release_terminal` at lines 425-427 subsequently trusts CANCELLED status to release funding.

Concrete public composition: activate funded BUY MARKET at 00:00; call `rt.broker.cancel(order_id, timestamp(10))`; call `rt.step()` at 00:01. The runtime remains RUNNING, produces no Fill, and appends reservation release at 00:01 even though the broker order records cancellation at 00:10. An eligible interval preceding cancellation is suppressed. This is a source-of-truth/time-boundary failure without private attribute writes. Cancelling both OCO peers at the same future timestamp is also accepted.

Initial regression: `tests/unit/accounting/test_phase009_security_boundary.py`, `test_future_external_cancellation_rejected_before_execution_or_release`, parameterized normal/OCO. Both expected fail-closed assertions failed before repair; temporary strict xfails preserved the reproduced defect. Their bodies now pass unchanged, with the xfail decorators removed.

Minimal repair: validate cancellation lifecycle timestamps against the supplied current accounting/runtime boundary before market processing or release. Reject invalid future lifecycle evidence without financial mutation, and verify normal, partial, and OCO terminal states. Do not modify the sealed broker semantics.

### SEC009-2 — Medium, CLOSED: accounting accepts financial settlement from both mutually exclusive OCO peers

`accounting/engine.py:448-480` validates per-order activation facts and cumulative Fill quantities but does not enforce group exclusivity across historical/new Fill facts. The settlement loop at lines 293 onward consumes one shared reservation for either peer.

Concrete accounting API: SELL OCO quantity 1 backed by initial holding 2; construct real-broker-provenance partial Fill facts of 0.5 for each peer, distinct FillIds, and matching PARTIALLY_FILLED order snapshots. `apply_fill_batch` accepts both, posts two financial settlements, consumes the entire shared reservation, and leaves both peer snapshots partially active. Quantity and fee evidence reconcile, so ordinary reconciliation does not detect the invalid exclusive lifecycle.

Initial regression: `test_accounting_rejects_two_oco_peer_fills_atomically` in the same probe file; its rejection assertion failed before repair. Its body now passes unchanged, with the temporary xfail decorator removed. This was an accounting-input boundary defect. The real sealed SimulatedBroker selects one peer and cancels its sibling, so this probe does not establish that unmodified runtime/broker execution emits such facts.

Minimal repair: for every shared reservation/OCO group, reject settlement facts covering more than one distinct peer across previously applied plus new Fill facts. Preserve legitimate multiple partial fills of the single chosen peer and whole-batch rollback.

## Independent evidence

Read repository AGENTS.md, the full Phase009 specification and implementation evidence, and targeted accounting/runtime source and existing tests. Reviewed ownership/ledger replay, staging/commit ordering, resource checks, fees, FIFO, immutable histories, ProductSpec normalization, canonical marks, arithmetic, and exposed broker bypasses. No provider credentials, live authority, risk implementation, or strategy runtime was introduced in the reviewed surface.

Focused execution used the existing native Python 3.14 virtual environment:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/accounting/test_phase009_security_boundary.py tests/unit/accounting/test_spot_accounting.py::test_initial_deposits_immutable_views_ids_and_replay tests/unit/accounting/test_spot_accounting.py::test_fifo_partial_exit_preserves_original_lots_gross_pnl_and_fees tests/unit/accounting/test_spot_accounting.py::test_invalid_fill_rejected_atomically tests/unit/accounting/test_spot_accounting.py::test_duplicate_fill_and_bad_batch_have_no_financial_mutation tests/integration/accounting/test_runtime_financial_authority.py::test_external_order_and_fill_paths_fail_closed tests/integration/accounting/test_runtime_financial_authority.py::test_oco_single_peer_cancel_rejects_and_whole_group_restores_availability -q -p no:cacheprovider --basetemp=.qa-phase009-security-final
```

Result: **15 passed, 3 xfailed in 0.55s**. The three xfails are the two normal/OCO future-cancellation reproductions and the double-peer Fill reproduction; they are failures of required rejection behavior, not evidence of acceptance. Positive probes establish stale/future mark rejection without mutation and context-independent financial state under precision 1, Emax 2/Emin -2, and Inexact/Rounded traps. Targeted existing tests independently establish duplicate/hostile Fill atomicity, immutable history/replay, FIFO partial exit/fee separation, unaccounted order/fill rejection, and safe whole-OCO cancellation.

Owned probe file Ruff lint and formatting: **All checks passed; 1 file already formatted**. The initial narrow mypy invocation could not resolve the source package and reported installed-package stub errors; the corrected invocation uses `MYPYPATH=src` to resolve local source rather than the editable-install search path.

Corrected strict mypy on the owned probe: **Success: no issues found in 1 source file** after explicitly typing the normal/OCO tuple union. No production code changed for static checks.

## Decisions, risks, and blockers

Only a bounded security regression file and this evidence document were added by the reviewer. Production files, dependencies, lockfile, user-owned untracked phase specifications, and other QA artifacts were preserved. The owner repaired only `accounting/engine.py` and removed the temporary strict xfails; the original rejection test bodies were preserved.

UNPROVEN: full acceptance gates and remote Python 3.13/3.14 CI (owned by QA/Director, not duplicated here). Restart/persistence/concurrency/live reconciliation are outside this in-memory deterministic phase.

Known environment ledger: default uv cache access denied at `C:\Users\TradeStation\AppData\Local\uv\cache\sdists-v9\.git` in native Windows sandbox. The blocked path was not retried. Direct existing `.venv` probes executed successfully; no new environment blocker occurred.

## Independent repair closure

Targeted reinspection confirms `accounting/engine.py:128`, `:283-285`, and `:303` propagate the supplied boundary timestamp before runtime execution and accounting staging. Validation at `:474-494` checks creation/activation/cancellation chronology and rejects Fill execution after cancellation. Binding also checks creation before activation at `:244`. Invalid cancellation inputs fail without financial mutation; the runtime converts the pre-execution failure into FAILED lifecycle.

The shared reservation check at `accounting/engine.py:462-471` examines prior plus new Fill facts and rejects more than one distinct covered peer before staging. It preserves successive partial fills for the same chosen peer.

Independent closure command:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/accounting/test_phase009_security_boundary.py tests/unit/accounting/test_lifecycle_repair.py tests/integration/accounting/test_runtime_financial_authority.py::test_oco_single_peer_cancel_rejects_and_whole_group_restores_availability tests/integration/accounting/test_runtime_financial_authority.py::test_runtime_one_unaffordable_same_time_fill_rolls_back_whole_batch -q -p no:cacheprovider --basetemp=.qa-phase009-security-closure
```

Result: **14 passed in 0.36s; no xfails/skips**. Original normal/OCO future-cancellation and simultaneous-peer probes pass. Additional owner regressions independently executed: future cancellation of active/partial orders; cancellation before an applied Fill; malformed creation chronology; second peer settlement in a successive batch rejected atomically; repeated same-peer partials accepted. Whole-OCO cancellation and unaffordable same-time batch rollback also remain valid. No additional concrete defect was found in this bounded repair review.

RECOMMENDATION: bounded Security/Reliability gate PASS; Director may assess acceptance using independent QA and remaining required gates.
