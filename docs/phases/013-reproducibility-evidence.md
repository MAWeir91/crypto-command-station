# Phase 013 implementation reproducibility evidence

Baseline: `de09476701f609f36e14accbfa87f00ea3a51937`. Scope: tests/evidence only;
production, dependencies and lockfile unchanged. Publication remains unperformed.
This is implementation readiness, not independent acceptance or CI evidence.

## Identities and comparisons

`BacktestResult.result_fingerprint` remains semantic completed-run identity.
`ArtifactManifest.fingerprint` remains fixed artifact-bundle integrity identity.
No overlapping public identity was introduced.

| Required claim | Exact new test |
| --- | --- |
| Independent dataset/artifact roots and component instances | `tests/integration/system/test_full_stack.py::test_separate_roots_complete_results_and_artifact_content` compares complete frozen results, including run/spec/result and every component provenance fingerprint, metrics, final account/positions/portfolio/reservations, execution/risk summaries, manifest; all JSON content, all Parquet rows and all bundle bytes also match. Both manifests are verified. |
| Decimal context | `tests/integration/system/test_full_stack.py::test_full_stack_decimal_context_matrix`: precision2/ROUND_DOWN,7/ROUND_UP,50/ROUND_DOWN versus default. Complete result and logical bundle equality includes orders, reservations, fills, balances, PnL, risk and strategy outcomes. |
| Fresh process / hash randomization | `tests/integration/system/test_full_stack.py::test_fresh_process_hash_seed_and_root_independence`: separate processes using `sys.executable`, separate roots, PYTHONHASHSEED1/987; exact run/result/manifest fingerprints match; bounded30s timeout, no dependency. |
| Input-order matrix | `tests/integration/system/test_full_stack.py::test_dataset_refs_and_product_specs_permutation`; `tests/property/system/test_reproducibility.py::test_generated_full_service_declaration_and_input_permutations` generates ordering/seed variations across dataset refs, product specs, holdings, subscriptions, indicators and parameter pairs, including multiple products/derived streams. Complete result and bundle match. |
| Source and stream input order | Existing `tests/property/market_data/test_dataset_properties.py::test_source_page_permutation_preserves_dataset_identity`, `::test_candle_input_permutation_is_canonicalized`; generated system declaration permutation composes canonicalized subscriptions into derived streams; `tests/integration/research/test_backtest_service.py::test_multi_product_ordering` independently covers product input order. |
| Every material input identity | `tests/integration/system/test_full_stack.py::test_material_input_changes_run_and_result_identity`: strategy code hash, resolved parameter, dataset candle/version, ProductSpec increment, initial cash, risk policy, execution fees, seed, period and engine commit each independently change run and result identity. |
| Final boundary identity | `tests/golden/system/test_research_results.py::test_final_active_order_preserves_sealed_portfolio_distinction`: separate roots preserve the post-callback account versus pre-callback portfolio distinction and identical bundle. |
| Corruption / immutable publication | Every one of nine bundle members independently corrupted; rerun fails and preserves all existing bytes. Hardlinks and pre-existing publication lock fail. Exact tests in regression inventory. |
| Failure atomicity | Dataset/artifact-reference/parameter failures precede runtime construction; insufficient warmup precedes settlement/binding; callback and injected accounting invariant fail without completion; serializer failure removes only owned staging directory. Exact tests in regression inventory. |

## Readiness checks

Locked setup completed with the explicit installed CPython3.14.6 executable:

```powershell
$env:UV_CACHE_DIR=Join-Path (Get-Location) '.uv-cache'
uv sync --locked --python C:\Users\TradeStation\AppData\Roaming\uv\python\cpython-3.14.6-windows-x86_64-none\python.exe
```

Focused terminating test command (elevated execution environment):

```powershell
.venv\Scripts\python.exe -m pytest tests/golden/system tests/property/system tests/integration/system tests/regression -q -p no:cacheprovider --tb=short
```

Implementation owner observed **48 passed in 16.42 s** after fixture repairs. The
generated financial suite was subsequently strengthened to inspect public accounting
settlement boundaries and represent generated quantity in typed strategy metadata;
its exact final test passed separately (**1 passed in 3.94 s**):

```powershell
.venv\Scripts\python.exe -m pytest tests/property/system/test_financial_invariants.py::test_generated_service_financial_risk_and_trade_reconciliation -q -p no:cacheprovider --tb=short
```
Hypothesis examples are bounded (6–12), use precise goldens alongside generators,
and rely on native reproduction of counterexamples.

Changed-surface checks:

```powershell
.venv\Scripts\python.exe -m ruff check tests/system_fixtures.py tests/golden/system tests/property/system tests/integration/system tests/regression
$env:MYPYPATH='src'
.venv\Scripts\python.exe -m mypy tests/system_fixtures.py tests/golden/system tests/property/system tests/integration/system tests/regression
```

Both passed (14 source files for strict mypy), and the final boundary-observer
file independently passed Ruff and strict mypy after strengthening. Normal focused
mypy without the source search path treated the editable installation as untyped;
the source search path establishes strict types without changing project files.

## Independent QA observed identities

On CPython **3.14.6**, independent QA created two separate dataset/artifact roots,
constructed two services with the accepted default `tests.research_fixtures.setup`
scenario, ran both, asserted complete result equality, read every Parquet table
and JSON member through `tests.system_fixtures.bundle`, and verified both manifests.
Both runs produced these exact values:

```text
run_id=0715ba3c7601b622bcec8721d528c32f0830a2c364709b7a8dd13fd9c571a3c7
spec_fingerprint=fc69de4f4ef32f5df40da5ae9ca9139ab4ccf172556a53b8aa0b7ac9f98b9c9d
result_fingerprint=0d03c4972e8d8e56e6abfbefe6d9ef00bfbc9f8f8b384289f631b6fb1e7c31ce
manifest_fingerprint=fa3212ffd2a0974ad0dcf0d36fa410c2147f093f7ea9d7a53e94616772fda067
separate_root_result_and_verified_bundle_equal=True
```

These are observed fixture evidence, not newly pinned golden hash requirements.
Independent gate commands, results and unproven claims are recorded in
`013-qa-evidence.md`. Python 3.13 was not executed locally; exact-commit Python
3.13/3.14 GitHub CI remains pending publication authorization.

## Recorded implementation infrastructure

Default sandbox `uv sync --locked` could not write the global cache `.git`;
workspace-local cache then hit the managed interpreter `.lock`; elevated sync
through the minor-version link reported a missing target. Explicit executable
setup succeeded. Sandbox pytest default temporary `.lock` failed; a single
workspace basetemp alternative also failed with WinError5. Elevated pytest
successfully exercised the tests. No production workaround was introduced.

Owner exceeded six validation invocations to repair concrete fixture failures,
establish strict changed-surface type health, and overcome the recorded setup/temp
infrastructure paths; no broad acceptance sweep was performed.

Independent QA owns full collection, historical regression homes, lock/format/lint/
type/import/full-pytest gates. Independent Security/Reliability review passed; see `013-security-evidence.md`. Python3.13
and3.14 exact-commit CI is pending; local Python3.14 equality alone does not establish
cross-version acceptance. Symlink coverage retains the existing platform-dependent
test limitation; hardlink coverage runs without a skip. Artifact byte equality is
established within the locked local PyArrow25.0.1 environment; cross-version CI
must independently establish its supported environment claim.

