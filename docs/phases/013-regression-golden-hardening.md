# Phase 013 — Regression / Golden Hardening & Full-System Reproducibility

**Status:** Ready for implementation  
**Date:** 2026-10-02  
**Primary authority:** `AGENTS.md`, `MASTER_ENGINEERING_SPEC.md`, ADRs 0001–0009  
**Depends on:** Phase 012 fully sealed on `main` at `de09476701f609f36e14accbfa87f00ea3a51937`

## 1. Objective

Phase 013 is the deliberate hardening phase after the first complete end-to-end backtest.

Its purpose is to prove that the already-built Phase 002–012 platform behaves correctly as one system across edge cases, permutations, failures, and fresh reruns.

Phase 013 establishes:

- a systematic cross-layer golden scenario suite;
- an explicit regression-test home for every material bug;
- full-stack property/invariant tests spanning market -> runtime -> execution -> accounting -> risk -> strategy -> research;
- stronger negative-path and corruption tests;
- stronger failure-atomicity tests;
- deterministic input-order/permutation tests;
- deterministic fresh-run and separate-root reproducibility tests;
- explicit verification that Phase 012 `result_fingerprint` is the canonical semantic reproducibility identity;
- explicit verification that `ArtifactManifest.fingerprint` is the immutable artifact-bundle integrity identity;
- evidence that both identities are stable, path-independent, and complete for their intended purposes;
- cross-version CI evidence on Python 3.13 and 3.14;
- Independent QA and Security/Reliability review.

This phase is primarily **test/evidence hardening**.

No new user-facing research feature is intended.

---

## 2. Baseline

Implementation must begin from clean `main` at:

```text
de09476701f609f36e14accbfa87f00ea3a51937
```

Before changes:

```bash
git rev-parse HEAD
git status --short
```

Require:

```text
HEAD == de09476701f609f36e14accbfa87f00ea3a51937
tracked workspace clean
```

Do not use or disturb stale local workspaces.

---

## 3. Master-spec authority

Phase 013 exists specifically to harden the master-spec contracts in:

- §61 Testing strategy;
- §62 Golden execution scenarios;
- §63 Accounting invariants;
- §64 Risk invariants;
- §65 Market-data invariants;
- §66 Reproducibility contract;
- §73 Source-of-truth philosophy.

Every required system test should trace to one or more of those contracts or to a material bug previously found during Phases 004–012.

---

## 4. Test-first phase

Default implementation order:

1. inventory existing evidence;
2. identify gaps;
3. add system/regression tests;
4. run tests;
5. only if a new test reveals a real production defect, perform the smallest justified production repair;
6. add focused regression for that defect;
7. rerun all gates;
8. QA/Security independently verify.

Do not proactively refactor production code merely because Phase 013 exists.

---

## 5. Production-change rule

Expected production diff:

```text
none
```

or a very small defect repair proven necessary by a failing Phase 013 test.

A production change is acceptable only when:

- a concrete invariant/golden/regression demonstrates the defect;
- the repair preserves accepted architecture;
- the behavior is supported by master/ADR/phase authority;
- the Director accepts the change;
- the failing test becomes a permanent regression.

Do not use Phase 013 for cleanup refactors, naming changes, API redesign, or optimization.

---

## 6. Expected test surface

Add a dedicated system-hardening layer:

```text
tests/
    regression/
        __init__.py
        test_historical_regressions.py
        test_corruption_regressions.py
        test_failure_atomicity.py

    golden/
        system/
            __init__.py
            test_execution_accounting_strategy.py
            test_risk_and_reservations.py
            test_research_results.py

    property/
        system/
            __init__.py
            test_financial_invariants.py
            test_market_time_invariants.py
            test_reproducibility.py

    integration/
        system/
            __init__.py
            test_full_stack.py
```

Exact filenames may vary modestly.

Reuse existing fixtures where appropriate.

Do not duplicate large fixture frameworks unnecessarily.

---

## 7. Regression-test policy

Every material bug from accepted phases should have either:

- an existing focused regression; or
- a new Phase 013 focused regression.

At minimum inventory the known repaired classes:

- importer timestamp/order/cursor/retry edge cases;
- dataset publication immutability;
- Phase 008 runtime integration gaps;
- Phase 009 future-cancellation boundary;
- Phase 009 OCO dual-peer settlement;
- Phase 009 test collection convention;
- Phase 010 snapshot-integrity forgery;
- Phase 011 callback command atomicity / attribution boundaries;
- Phase 012 forged/incomplete artifact manifest.

Do not rewrite existing tests solely to move them.

Add coverage only where the defect is not already directly protected.

---

## 8. Golden scenario philosophy

Golden tests must use tiny hand-authored deterministic market sequences with exact expected outcomes.

Prefer direct assertions over opaque snapshot files.

A golden should make it easy to answer:

- what market events occurred;
- what order was active;
- when the fill happened;
- why it filled;
- what accounting changed;
- what risk saw;
- what strategy saw;
- what final research result recorded.

---

## 9. Required system golden — next-open market execution

Construct a strategy whose primary bar closes at T and submits a MARKET order.

Assert:

- intent `created_at == T`;
- order `activated_at == T`;
- no signal-bar price is reused;
- fill occurs on the first eligible one-minute interval after activation;
- execution reference is that interval's open;
- accounting occurs only after Fill;
- result artifacts preserve the same evidence.

This must exercise the full BacktestService path, not only broker unit tests.

---

## 10. Required system golden — signal-bar lookahead

Construct a signal bar whose high/low would have filled a newly created LIMIT order if lookahead were allowed.

Assert:

- strategy submits at T after bar publication;
- the just-completed bar cannot fill it;
- first possible fill comes from future market activity;
- runtime trace/callback/action/fill provenance all agree.

---

## 11. Required system golden — stop gap

Have an already-active STOP_MARKET order whose trigger is crossed by a gap.

Assert:

- stop triggers from future market activity;
- fill uses next executable price plus configured adverse slippage;
- fill is not magically priced at stop;
- `gap == True`;
- accounting/fees/slippage/result artifacts reconcile.

---

## 12. Required system golden — OCO same-minute ambiguity

Create an already-active LIMIT + STOP_MARKET OCO pair where both branches are reachable inside one future one-minute candle.

Assert:

- exactly one peer fills;
- resolution is conservative against strategy;
- `ambiguity == True`;
- sibling cancels;
- shared reservation settles/releases exactly once;
- one financial settlement only;
- risk/execution/accounting/result evidence agree.

---

## 13. Required system golden — existing stop before strategy decision

Create an existing protective SELL stop that fills during one-minute market activity ending at T while the primary decision bar also closes at T.

Assert:

```text
existing fill
-> accounting
-> portfolio
-> bars
-> indicators
-> on_fill
-> on_bar
```

The strategy's `on_bar` must observe the already-reduced/flat position.

---

## 14. Required system golden — reservation cancellation

Activate an order that remains untouched.

Cancel it from a later strategy callback.

Assert:

- no Fill occurs;
- unused reservation releases;
- total balances/lots remain unchanged;
- available capacity restores;
- risk on a later equivalent proposal sees restored headroom;
- cancelled order cannot fill later.

---

## 15. Required system golden — risk modification

Use BUY LIMIT with `allow_quantity_reduction=True` and cap headroom below requested commitment but above minimum executable quantity.

Assert:

- `APPROVE_WITH_MODIFICATION`;
- modified quantity is lower;
- request passes real ProductSpec re-normalization;
- reservation equals approved commitment;
- broker sees approved quantity only;
- future fill/accounting uses approved quantity;
- BacktestResult/artifacts preserve requested vs approved evidence.

---

## 16. Required system golden — risk rejection then continue

Submit a proposal rejected by risk, then later submit a valid one.

Assert:

- rejection produces no order/reservation/ledger mutation;
- runtime continues;
- later callback executes;
- later valid proposal may activate/fill;
- RiskSummary reason counts exactly match decisions.

---

## 17. Required system golden — multi-timeframe atomic decision

Use:

```text
1m canonical execution
5m primary
15m supporting
```

At a timestamp where both derived bars close:

- all same-time bars publish first;
- both indicators update first;
- primary callback runs once;
- callback sees fresh 15m supporting state;
- any new order remains future-only.

---

## 18. Required system golden — final-boundary active order

Submit an order on the final callback at `replay_end`.

Assert:

- no fabricated future Fill;
- order remains ACTIVE if otherwise valid;
- reservation remains explicit;
- final account/reservations reflect post-callback activation;
- final PortfolioSnapshot remains the sealed pre-callback market/accounting snapshot;
- result/artifact identities are deterministic.

This preserves the accepted Phase 012 final-boundary distinction.

---

## 19. Required system golden — open final position

End the replay with owned crypto.

Assert:

- no forced liquidation;
- no synthetic terminal Fill;
- unrealized PnL uses final canonical mark;
- realized PnL excludes open quantity;
- equity reconciles.

---

## 20. Partial-fill contract

The Phase 008 reference broker v1 fills the full remaining quantity when its deterministic model executes.

Do **not** alter the broker merely to force system partial fills.

Instead harden partial-fill support at the accounting/lifecycle boundary using explicit immutable Fill fixtures:

- partial fill consumes reservation proportionally;
- position/balance changes only for filled quantity;
- remaining reservation remains;
- later fill completes correctly;
- cancellation releases only unused remainder.

Document that full end-to-end partial-liquidity simulation remains out of scope until an execution model explicitly supports it.

---

## 21. Accounting invariant suite

Across generated valid scenarios prove at every financial boundary:

1. USD total is never negative.
2. Crypto total is never negative.
3. reserved amount is never negative.
4. reserved amount never exceeds total.
5. `available == total - reserved`.
6. only Fill settlement changes trading totals/positions.
7. every financial change is represented in ledger postings.
8. ledger replay reproduces AccountView.
9. cancellation releases unused reservation.
10. partial Fill consumes reservation correctly.
11. PositionView actual quantity equals open lots.
12. aggregate open-lot quantity equals account total base quantity.
13. realized PnL equals LotConsumption truth.
14. fee totals equal Fill fee totals.
15. Portfolio equity equals cash + marked asset values.
16. equivalent ledger replay produces identical balances.
17. dust is retained rather than silently zeroed.

Use exact Decimal comparisons.

---

## 22. Risk invariant suite

Across generated valid proposals/state:

1. every exposure-increasing runtime activation has a recorded risk authorization;
2. BUY pending reservations increase/retain projected exposure, never reduce it;
3. pending SELL does not reduce projected exposure before Fill;
4. OCO shared reservation counts once;
5. modification never increases quantity;
6. modification never increases commitment;
7. approved proposal satisfies all configured applicable caps;
8. exposure-reducing SELL remains possible under `trading_enabled=False`;
9. rejection mutates no broker/accounting/ledger state;
10. reasons are machine-readable and deterministically ordered;
11. stale mark-dependent state cannot approve;
12. risk fingerprint is stable for equivalent state/history.

---

## 23. Market-data invariant suite

Across generated accepted datasets/resampled streams:

1. canonical candle starts are strictly monotonic;
2. duplicates are rejected;
3. gaps are explicit;
4. no synthetic source candle is introduced;
5. resampled bar uses only source intervals inside its half-open bucket;
6. incomplete/gapped bucket is omitted rather than partially emitted;
7. exact OHLCV aggregation is context-independent;
8. equivalent source ordering yields identical derived identity/content;
9. replay cannot expose a bar with `close_time > runtime clock`;
10. replay-end clipping does not alter source DatasetVersion;
11. changing repaired dataset content changes DatasetVersion.

---

## 24. Strategy/runtime invariant suite

Prove:

1. no callback before trading_start;
2. on_start exactly once;
3. on_bar only on primary close;
4. supporting-only closes never trigger decision callback;
5. same-time subscribed bars are atomically visible;
6. indicators contain no future bars;
7. existing fills are delivered before same-time on_bar;
8. command `created_at` equals runtime timestamp;
9. callback-created orders cannot use already-completed activity;
10. failed callback activates none of its uncommitted commands;
11. on_fill/on_stop command prohibition remains enforced;
12. direct manual activation is blocked when strategy is attached;
13. fresh runner/state/indicator instances do not leak across runs.

---

## 25. Research/result invariant suite

Prove:

1. BacktestSpec logical ordering canonicalizes.
2. material spec changes alter spec/run identity.
3. same exact inputs produce identical result fingerprint.
4. artifact root path does not alter semantic result fingerprint.
5. artifact root path does not alter logical artifact contents.
6. manifest fingerprint is deterministic for identical bundle bytes/content.
7. published bundle is immutable.
8. corrupt bundle cannot be reused.
9. fatal runtime failure publishes no completed bundle.
10. warmup snapshots never enter analytics.
11. no metric emits NaN/Infinity.
12. fees/slippage reconcile to Fill evidence.
13. ClosedLotTrade quantities/PnL reconcile to accounting.
14. active final orders are represented honestly.
15. open final holdings are not liquidated.

---

## 26. Canonical reproducibility identity

Phase 012 already introduced:

```text
BacktestResult.result_fingerprint
```

Treat this as the canonical **semantic completed-run fingerprint** unless Phase 013 exposes a concrete omission.

Phase 013 must prove that it changes when any material result-affecting identity changes, including:

- strategy artifact/code identity;
- resolved parameter values;
- DatasetVersion(s);
- ProductSpec/account identity;
- RiskPolicy;
- execution spec;
- random seed;
- period;
- EngineIdentity;
- runtime/execution/accounting/risk/strategy outcomes.

Do not add another overlapping public fingerprint merely for Phase 013.

---

## 27. Artifact identity

`ArtifactManifest.fingerprint` remains the artifact-bundle integrity identity.

It is distinct from semantic `result_fingerprint`.

Prove:

```text
same semantic run + same deterministic artifact serialization
=> same result_fingerprint
=> same manifest fingerprint
```

and:

```text
artifact corruption
=> verification failure
```

Do not make absolute root paths part of either identity.

---

## 28. Separate-root reproducibility

Run an identical BacktestSpec using two independently created:

- dataset-store roots containing logically identical immutable datasets;
- artifact-store roots;
- BacktestService instances;
- Strategy instances;
- runtime components.

Require equality of:

- BacktestRunId;
- spec fingerprint;
- result fingerprint;
- component fingerprints;
- metrics;
- final account/positions/portfolio/reservations;
- RiskSummary;
- ExecutionSummary;
- canonical artifact table rows;
- canonical JSON semantic content;
- manifest fingerprint if deterministic file bytes are identical under the locked environment.

At minimum logical artifact contents must be identical.

---

## 29. Fresh-process-friendly determinism

Tests should avoid depending on:

- Python object identity;
- insertion history;
- temp paths;
- current working directory;
- process ID;
- wall clock;
- hash randomization;
- unordered set iteration.

Where feasible, add a subprocess-based reproducibility test using the same locked interpreter/environment and compare emitted canonical fingerprints.

Do not add a new dependency for this.

---

## 30. Input permutation matrix

Systematically permute semantically irrelevant input order and prove identical results.

Include applicable permutations of:

- dataset refs;
- account ProductSpecs;
- initial holdings;
- strategy subscriptions;
- indicator declarations;
- generated source ordering;
- derived stream ordering;
- equivalent parameter pair ordering.

Only permute where the accepted contract says order is non-semantic.

If order is semantically meaningful, do not canonicalize it away.

---

## 31. Decimal-context matrix

Run representative full-stack scenarios under materially different ambient Decimal contexts.

Require identical:

- normalized order requests;
- reservation plans;
- fills;
- ledger balances;
- PnL;
- risk decisions;
- result fingerprint.

No ambient context flags should be required for financial truth.

---

## 32. Failure atomicity matrix

Probe failures at each major boundary.

At minimum:

### Dataset resolution failure
No runtime begins, no artifact publication.

### Strategy artifact mismatch
No runtime begins.

### Warmup/subscription configuration failure
No financial mutation.

### Callback exception
No queued callback command activation.

### Risk rejection
Normal run continuation; no rejected-proposal financial mutation.

### Accounting invariant failure
Runtime fails; no completed research artifact published.

### Artifact serialization failure
No published final run directory.

### Artifact verification failure
Existing published run remains untouched.

---

## 33. Corruption matrix

Adversarially corrupt one piece at a time:

- canonical dataset manifest/content identity;
- derived provenance;
- strategy descriptor fingerprint/code hash format;
- result artifact JSON;
- one Parquet file;
- manifest record hash;
- manifest record count/path/schema;
- hardlink/symlink where platform permits.

Require fail-closed behavior.

Do not silently reconstruct unknown/corrupt evidence.

---

## 34. Historical regression inventory document

Create:

```text
docs/phases/013-regression-inventory.md
```

This is evidence/documentation, not a new authority source.

For each known material bug:

```text
bug/finding
phase
severity if known
repair commit
current protecting test(s)
status: COVERED / GAP CLOSED IN 013
```

Do not include speculative bugs.

---

## 35. Golden matrix evidence document

Create:

```text
docs/phases/013-golden-matrix.md
```

Map master §62 scenarios plus Phase 009–012 critical boundaries to exact test names.

Use:

```text
contract/scenario
test path::test_name
layer(s)
expected invariant
```

This prevents future “coverage by assumption.”

---

## 36. Reproducibility evidence document

Create:

```text
docs/phases/013-reproducibility-evidence.md
```

Record:

- exact baseline SHA;
- Python versions;
- same-input rerun fingerprints;
- separate-root results;
- permutation results;
- Decimal-context results;
- artifact verification evidence;
- any intentional identity distinctions.

Do not copy machine-specific absolute paths into canonical run identities.

---

## 37. System fixture discipline

Prefer tiny deterministic fixtures.

Requirements:

- explicit UTC timestamps;
- explicit Decimal prices/quantities;
- minimal number of candles;
- no external network;
- no randomness unless seed/control is explicit;
- no “latest” data;
- no hidden filesystem dependency.

---

## 38. Golden expected values

For golden tests, assert exact values for material financial facts:

- OrderId/FillId where deterministic;
- activation/fill timestamps;
- fill reference/price/slippage/fee;
- reservation amounts;
- ledger categories/postings;
- balances;
- lots/consumptions;
- realized/unrealized PnL;
- equity;
- risk status/reasons;
- final result fingerprints where stable and intentionally golden.

Do not golden-pin values whose accepted contract explicitly allows implementation freedom.

---

## 39. Fingerprint golden policy

Use exact golden fingerprints only for deliberately versioned semantic fixtures.

If a legitimate versioned semantic change occurs later, the golden must change together with:

- explicit model/schema/version change where required;
- rationale;
- updated expected financial/domain facts.

Do not “fix” a failing fingerprint golden by blindly replacing the hash.

---

## 40. Mutation resistance

Where practical, construct forged/frozen-object mutations in tests to prove public boundaries revalidate rather than trusting dataclass construction alone.

Candidate boundaries:

- dataset load;
- risk snapshot;
- artifact manifest;
- BacktestSpec/result values.

Use this technique only where there is an actual public trust boundary.

---

## 41. No performance benchmark gate yet

Do not turn Phase 013 into a performance phase.

A very small smoke timing may be collected diagnostically, but:

- no hard speed target;
- no optimized simulator;
- no NumPy/Numba/Rust rewrite;
- no semantic relaxation for speed.

Phase 019 owns simulator optimization.

---

## 42. No fuzzing dependency

Hypothesis is already present and should be used.

Do not add external fuzzing frameworks.

Keep generated examples bounded so CI remains reliable.

---

## 43. Property-test health

Property tests must:

- generate meaningful state/scenario variation;
- avoid trivial tautologies;
- assert cross-layer invariants;
- use bounded example counts;
- avoid excessive runtime;
- reproduce failures with Hypothesis examples/seeds.

Do not replace precise golden tests with broad property tests; both are required.

---

## 44. Cross-Python acceptance

GitHub CI must execute full repository tests on:

```text
Python 3.13
Python 3.14
```

Both versions must produce passing golden/property/regression suites.

Where a deterministic golden fingerprint is asserted, it must match on both supported versions.

If a float-only analytical representation causes cross-version drift, investigate and either:

- make the analytical algorithm deterministic enough for the supported versions; or
- avoid including unstable presentation-only float serialization in a financial identity.

Do not mask genuine semantic nondeterminism.

---

## 45. Security/Reliability review scope

Independent Security/Reliability review is required.

Focus on system boundaries rather than re-auditing every line.

### Lookahead / sequencing
- same-timestamp partial visibility;
- signal-bar order reuse;
- fill/accounting before strategy state;
- replay_end edge.

### Financial integrity
- negative balances;
- reservation under/over-consumption;
- OCO double settlement;
- duplicate Fill;
- ledger/result mismatch.

### Authorization
- risk bypass;
- unattributed strategy order;
- pending exposure omission;
- rejection mutation.

### Reproducibility
- path/wall-clock/PID/hash-order leakage;
- mutable instance reuse;
- same run identity differing content.

### Artifact integrity
- manifest forgery;
- path traversal;
- symlink/hardlink;
- partial publication;
- concurrent/stale lock behavior.

Return concrete findings/counterexamples.

Any valid finding requires regression coverage before PASS.

---

## 46. Independent QA scope

QA independently executes the system from a clean workspace.

Must cover:

- golden matrix;
- full-system property suite;
- regression inventory;
- separate-root rerun;
- permutation matrix;
- Decimal-context matrix;
- corruption matrix;
- failure atomicity;
- artifact inspection;
- full gates.

QA must not rely only on implementation-owner evidence.

---

## 47. Import boundaries

Phase 013 should not require production import-boundary changes.

Test code may compose across layers.

Production dependency direction remains unchanged.

If a proposed test is impossible without adding a wrong-way production import, redesign the test rather than weakening architecture.

---

## 48. No new runtime API unless defect demands it

Do not expose new mutable internals solely to make tests easier.

Tests should use:

- public immutable views;
- existing component evidence;
- accepted fixtures;
- explicit test-only constructors where already normal.

Do not weaken encapsulation for coverage.

---

## 49. Repository validation

Mandatory:

```bash
uv sync --locked
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

GitHub Actions must pass Python 3.13 and Python 3.14.

No dependency changes expected.

---

## 50. Publication workflow

Phase 013 may be developed on a clean isolated branch/worktree.

Before publication:

- Director reviews final diff;
- QA PASS;
- Security/Reliability PASS;
- local feasible gates PASS.

Then, with explicit user publication authorization:

- commit;
- push Phase 013 branch;
- open PR to `main`;
- obtain exact-commit CI;
- independently inspect before merge.

Do not merge automatically.

---

## 51. Acceptance criteria

Phase 013 is accepted only when:

1. implementation starts from exact sealed Phase 012 main.
2. no feature-scope expansion occurs.
3. known material bug inventory exists.
4. every inventoried bug has a protecting regression.
5. master §62 scenarios are mapped to exact tests.
6. next-open market golden exists.
7. signal-bar no-lookahead full-stack golden exists.
8. stop-gap full-stack golden exists.
9. same-minute OCO ambiguity golden exists.
10. existing-stop-before-decision golden exists.
11. reservation cancellation full-stack golden exists.
12. risk modification full-stack golden exists.
13. risk rejection continuation golden exists.
14. multi-timeframe atomic decision golden exists.
15. final-boundary active-order golden exists.
16. open-final-position golden exists.
17. partial-fill accounting/lifecycle evidence is explicit.
18. cash never negative across generated valid scenarios.
19. crypto quantity never negative.
20. reservations remain within totals.
21. ledger replay reproduces account.
22. positions reconcile to open lots.
23. fees reconcile to Fill evidence.
24. portfolio equity reconciles.
25. Fill-only trading mutation remains true.
26. pending BUY projected exposure invariant holds.
27. pending SELL non-netting invariant holds.
28. OCO commitment is counted once.
29. risk modification cannot increase exposure.
30. rejection causes no financial mutation.
31. stale mark-dependent risk fails closed.
32. canonical market timestamps remain monotonic.
33. gaps are never fabricated.
34. resampling half-open/gap semantics are property-tested.
35. strategy cannot see future bars.
36. same-time market state is atomic.
37. fill callback precedes same-time decision.
38. failed callback cannot partially activate commands.
39. direct strategy-runtime activation bypass remains blocked.
40. warmup excluded from analytics.
41. ClosedLotTrade reconciles to accounting.
42. metric output contains no NaN/Infinity.
43. same exact run inputs produce same result fingerprint.
44. semantic input permutations preserve identity/results where order is non-semantic.
45. material input changes alter run/result identity as appropriate.
46. separate filesystem roots do not alter semantic result fingerprint.
47. artifact logical content is path-independent.
48. manifest identity verifies deterministic artifact bundle integrity.
49. corrupted bundle cannot be reused.
50. same run ID cannot silently produce different content.
51. fatal runtime/service failure publishes no completed bundle.
52. Decimal ambient context does not alter financial outcome.
53. fresh independent runs do not share mutable state.
54. no wall-clock/PID/temp path enters semantic fingerprints.
55. Python 3.13 and 3.14 agree on intentional golden fingerprints.
56. no new dependency is added.
57. no batch/job/MCP/optimization/paper/live functionality is introduced.
58. Independent QA PASS.
59. Security/Reliability PASS.
60. `uv lock --check` PASS.
61. Ruff format PASS.
62. Ruff lint PASS.
63. strict mypy PASS.
64. import-linter PASS.
65. full pytest PASS.
66. Python 3.13 CI PASS.
67. Python 3.14 CI PASS.

---

## 52. Stop/escalate conditions

Stop and escalate rather than silently redesign if:

- a new test reveals conflict between accepted phase contracts;
- a fix would change fill/accounting/risk semantics without authority;
- result fingerprint is proven incomplete in a way requiring schema redesign;
- artifact byte determinism cannot be guaranteed across supported versions and the manifest contract must change;
- testability appears to require exposing mutable production internals;
- partial-fill system testing appears to require inventing a new liquidity model;
- a production repair grows beyond a narrow defect fix;
- a dependency addition appears necessary;
- scope drifts into batch backtests, jobs, optimization, MCP, paper, or live trading.

---

## 53. Explicitly out of scope

Do not implement:

- new strategy features;
- new indicators;
- strategy registry persistence;
- batch backtests;
- job semantics;
- result database/index;
- MCP;
- REST/API;
- CLI product surface;
- optimization;
- walk-forward;
- Monte Carlo;
- optimized simulator;
- paper/live runtimes;
- Coinbase authenticated broker;
- new liquidity/partial-fill model;
- performance rewrite;
- UI/frontend.

---

## 54. Definition of done

Phase 013 is done when the system has durable executable evidence that the sealed reference stack behaves correctly and reproducibly across edge cases:

```text
canonical datasets
      |
      v
deterministic replay/resampling
      |
      v
strategy callbacks
      |
      v
risk authorization
      |
      v
order execution
      |
      v
ledger/accounting/portfolio
      |
      v
research analytics/artifacts
      |
      v
stable result + manifest identities
```

The hardening suite must make it difficult for a future change to silently break:

- no-lookahead;
- execution semantics;
- reservations;
- accounting truth;
- risk authorization;
- strategy ordering;
- dataset identity;
- reproducibility;
- artifact integrity.

Phase 013 is evidence that the correct reference system is ready to become the foundation for Phase 014 batch execution.
