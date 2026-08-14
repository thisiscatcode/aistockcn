# AiStockCN Documentation

This documentation describes the live AiStockCN financial research product, its evidence controls, quantitative workflows and operating model.

**Documentation baseline:** 14 August 2026

## Start here

| Audience | Document | Purpose |
| --- | --- | --- |
| Investors and product users | [User Guide](USER_GUIDE.md) | Navigate A-shares, US Intelligence and Research Copilot |
| Product and engineering | [Research Copilot](RESEARCH_COPILOT.md) | Understand cited answers, financial tools, RAG and filing-change detection |
| Engineers and reviewers | [System Design](SYSTEM_DESIGN_SPEC.md) | Review services, data boundaries, security and reliability |
| Operators | [System Manual](SYSTEM_MANUAL.md) | Build, start, validate and troubleshoot the platform |
| Quantitative research | [Model Evaluation Record](RESULTS.md) | Interpret saved training and walk-forward artifacts correctly |
| Quantitative research | [A-Share Medium 10D V2](A_SHARE_MEDIUM_10D_V2.md) | Profile definition, execution assumptions and governance |

## Product scope

AiStockCN combines:

- a production universe of 5,000+ China A-shares and 5,000+ US-listed equities;
- market-data ingestion, feature engineering, model training and walk-forward evaluation;
- rules-based and model-derived selection workflows;
- source-grounded company research over SEC filings and standardized financial facts;
- cited natural-language answers, company comparison and filing-change detection;
- portfolio and paper-execution controls with explicit model lineage;
- separate customer and administrator surfaces.

## Documentation standards

The repository follows four rules:

1. Product claims must map to a live route, service or persisted artifact.
2. Financial facts, document evidence and model inference must remain visibly distinct.
3. Model metrics must include the run ID, evaluation window and execution assumptions.
4. Secrets, customer data, uploaded documents and runtime logs must never appear in committed documentation.

## Live product

- Product: [aistockcn.com](https://aistockcn.com)
- Research Copilot: [aistockcn.com/research](https://aistockcn.com/research)
- Current server runtime: Docker Compose with separate API, worker and frontend services

AiStockCN is a research and evidence-navigation product. It does not provide individualized investment advice or guarantee investment outcomes.
