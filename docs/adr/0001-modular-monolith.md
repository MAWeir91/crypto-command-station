# ADR 0001 — Modular Monolith

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Crypto Command Station will eventually include historical data ingestion, backtesting, research orchestration, strategy management, paper trading, live Coinbase execution, risk, accounting, analytics, MCP, API, and a web command center.

Those responsibilities are substantial, but the product is initially developed by a small engineering organization and the first objective is a correct Coinbase spot backtesting engine. Splitting the system into independently deployed services before domain boundaries are proven would add network contracts, deployment coordination, distributed failure modes, duplicated operational tooling, and greater debugging cost before those costs are justified.

At the same time, a single unstructured application would make later paper/live work dangerous because provider, persistence, trading-domain, and interface concerns could become tightly coupled.

## Decision

Build Crypto Command Station initially as a **modular monolith**:

- one Git repository;
- one primary Python codebase;
- explicit internal module boundaries;
- dependency rules enforced in code/tests/tooling;
- isolated worker processes where parallel research requires them;
- infrastructure adapters separated from domain logic;
- no distributed service boundary unless an accepted future ADR justifies one.

Modules communicate through explicit Python contracts and application services rather than by reaching into each other's persistence or internals.

The financial trading runtime remains an in-process deterministic state machine for a single run.

## Consequences

### Positive

- simpler local development and debugging;
- deterministic financial workflows remain easy to trace;
- fewer deployment and networking failure modes;
- lower operational burden;
- easier refactoring while domain boundaries are still maturing;
- future service extraction remains possible because module boundaries are explicit.

### Negative

- the repository and application may become large;
- internal boundary discipline must be enforced rather than delegated to network boundaries;
- some workloads may eventually require separate deployable processes.

## Rejected alternatives

### Microservices from the beginning

Rejected because current scale and team needs do not justify distributed-system complexity.

### Unstructured single application

Rejected because trading, accounting, provider, research, and interface responsibilities require strong internal ownership boundaries.

## Revisit when

Reconsider only when a demonstrated operational requirement cannot be handled cleanly by process isolation or bounded workers, such as independent scaling, fault containment, regulatory isolation, or materially different availability requirements.
