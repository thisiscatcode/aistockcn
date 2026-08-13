# Documentation Index

Start with the document that matches what you want to evaluate.

## Research Copilot

- [RESEARCH_COPILOT.md](RESEARCH_COPILOT.md)
- Product scope, source-grounding contract, RAG and agent architecture, user workflow, local runtime and deployment boundaries
- Use this document to operate, maintain or extend the AI research system

## Quant Platform User Guide

- [USER_GUIDE.md](USER_GUIDE.md)
- Product surface and operator workflow

## System Design Spec

- [SYSTEM_DESIGN_SPEC.md](SYSTEM_DESIGN_SPEC.md)
- Architecture, boundaries, runtime model and operational controls

## System Manual

- [SYSTEM_MANUAL.md](SYSTEM_MANUAL.md)
- Step-by-step explanation of the quant pipeline and artifact flow

## Results and model profiles

- [RESULTS.md](RESULTS.md) — saved production research and model results
- [A_SHARE_MEDIUM_10D_V2.md](A_SHARE_MEDIUM_10D_V2.md) — the additive 10-day A-share profile and its paper-only deployment gate

Suggested reading order:

1. `RESEARCH_COPILOT.md`
2. `USER_GUIDE.md`
3. `SYSTEM_DESIGN_SPEC.md`
4. `SYSTEM_MANUAL.md`

## Deployment status

- `aistockcn.com` is live, including the authenticated Research Copilot at `/research`.
- The Research API and background worker currently run on the existing host with Docker Compose.
