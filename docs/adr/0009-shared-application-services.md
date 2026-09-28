# ADR 0009 — Shared Application Services for Web, MCP, and CLI

**Status:** Accepted  
**Date:** 2026-09-28

## Context

Crypto Command Station will eventually expose web/API, MCP, and CLI interfaces. If each interface independently orchestrates backtests, datasets, strategies, or deployments, business rules and authorization behavior will diverge.

MCP is intended to let ChatGPT and Codex operate the same research system that the web command center uses.

## Decision

Web/REST, MCP, and CLI are **interface adapters over shared application services**.

Examples of application services may include:

- DatasetService;
- StrategyService;
- BacktestService;
- ComparisonService;
- ResearchService;
- OptimizationService;
- future DeploymentService;
- future TradingControlService.

Interfaces translate external requests into application commands and format responses. They do not implement a second copy of trading or research orchestration.

MCP tools must not directly query or mutate persistence when an application service owns the use case.

## Consequences

### Positive

- one behavior path for all clients;
- simpler authorization and validation;
- MCP and web results remain consistent;
- application services become testable without transport layers.

### Negative

- an application-service layer must be maintained;
- interfaces may require response shaping rather than exposing repository models directly.

## Rejected alternatives

### Direct SQL from MCP tools

Rejected because business rules, validation, permissions, and formatting would become inconsistent.

### Business logic inside FastAPI routes or CLI commands

Rejected because behavior would diverge across interfaces.

## Revisit when

Transport-specific optimizations may be added later, but the authoritative use-case logic remains in shared application services.
