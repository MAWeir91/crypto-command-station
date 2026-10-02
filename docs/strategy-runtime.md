# Strategy runtime v1

Strategies are trusted application code subject to ADR 0008. The API does not
sandbox arbitrary Python. Supported mutable strategy state lives in the explicit
scalar schema; hidden globals and mutable strategy instance state are unsupported.

Definitions contain immutable sorted subscriptions, parameter/state schemas and
built-in indicator specs. Exactly one completed-bar stream drives decisions.
Trading start must match its close in the accepted feed. Warmup counts include the
bar closing at trading start, as specified in Phase 011. Preflight counts actual
accepted bars, never inferred intervals. Warmup publishes and calculates indicators
without callbacks. A runner attaches once and cannot be reused, even before replay.

SMA is `math.fsum(last N float closes) / N`. EMA seeds from the first N-close SMA,
then uses `alpha = 2 / (N + 1)` and `alpha * close + (1 - alpha) * prior`.
Both expose `None` before N source bars. Conversion from Decimal closes occurs
only inside the indicator engine. Nonfinite sources/results fail the run.
No indicator state is shared or persisted.

Each callback receives new clock, subscribed-market, indicator and financial value
snapshots. History is positive-limit published-bar history. Undeclared streams
raise `StrategyContractError`; ProductSpecs are restricted to subscribed products.
Only schema state is shared between callbacks. The order capability contains a
local queue and immutable prior order/action snapshots, with no runtime reference
or closure. It seals when the callback exits, preventing retained capabilities
from queuing commands later. Fill and stop callbacks cannot queue commands.

Callbacks commit commands only after returning normally. Escaping callback errors
discard their queue, record failure audit, and fail the runtime without subsequent
callbacks. State updates already made by the failed callback remain inspectable.

The command commit policy is sequential, following the Director's Phase 011
decision, and requires independent QA review. Before any financial mutation from
a callback batch, all entry products/timestamps/shapes and normalizations are
validated, and all cancellations are checked for ownership, active lifecycle,
reservation and duplicate cancellation. Then commands commit in ID order against
the latest financial state. Each goes through the existing risk/reservation/broker
pipeline. Risk rejections are ordinary immutable results. No arbitrary activation
failure or invariant failure is claimed to roll back earlier successful commands.
Their financial truth and action audit remain intact and the runtime fails.
Start commands commit before the fresh first bar context, so that context sees
start reservations and results. Orders activated at T interact only with later
canonical intervals, preserving the existing Phase 008 eligibility rule.

External runtime activation and cancellation are blocked when a runner is attached.
Internal runtime activation still requires risk authority; attribution and financial
bindings are rechecked on later boundaries. A strategy can cancel only its own
active orders, and an OCO must be cancelled as a whole group.

Definition fingerprints identify metadata, not code. Strategy-run fingerprints
include resolved parameters, initial state, trading start, callback/command/action
audit, final state and indicator readings, excluding nondeterministic metadata.
Phase 012 will add complete experiment/code/dataset provenance.
