# AiStockCN User Guide

AiStockCN provides one authenticated workflow for AI company research, verification, quantitative analysis, portfolios and controlled execution in US stocks and China A-shares.

**Audience:** investors, analysts and product users

**Product:** [aistockcn.com](https://aistockcn.com)

## Sign in and choose a market

After sign-in, AiStockCN opens the A-share Overview. Use the market switcher to move between:

- **A-Shares** — official-disclosure research, signals, portfolio state and controlled execution in RMB and Shanghai time.
- **US Stocks** — cited company research, US signals, research portfolios and execution-readiness gates in USD and New York time.

Market currencies, model artifacts and execution rules remain separate. Switching the interface never combines the two portfolios.

## Unified navigation

Both markets use one persistent navigation rail:

| Page | Use it for |
| --- | --- |
| **Overview** | Market and account context for the selected market |
| **Research** | Company evidence, filings, cited Q&A, changes and comparison |
| **Quant** | Signals, methodology, walk-forward validation and Explorer |
| **Portfolio** | A-share holdings or US research and validated target baskets |
| **Execution** | A-share orders and controls or US readiness gates |

Operational pages such as Data Jobs, Models, Monitoring and Research Operations are available only from the administrator area and are absent from investor navigation.

![AiStockCN unified product homepage](assets/product-home.png)

## Research a company

Open **Research**, then search by ticker or company name. Selecting a US company opens its full research workspace. Selecting an A-share company lets the user sync official filings and inspect their source state.

The security header shows the latest available price context, P/E, EPS and volume. Company research is organized into six tasks:

| Task | Purpose |
| --- | --- |
| **Summary** | Financial highlights, recent filings and the latest saved filing comparison |
| **Ask AI** | Ask a focused question and inspect its evidence and reasoning boundary |
| **Financials** | Review normalized SEC financial facts, periods, units and filing lineage |
| **Filings** | Open original filings and manage source documents |
| **Changes** | Compare annual filings and review material disclosure changes |
| **Compare** | Analyse two or three companies through the same evidence workflow |

## Ask a source-grounded question

Good questions are specific about the subject and period, for example:

- How did revenue, operating margin and free cash flow change in the latest fiscal year?
- What risks did management strengthen or add between the last two annual reports?
- What evidence supports the current margin trend?
- Compare the latest revenue growth and risk disclosures of AAPL, MSFT and NVDA.

While the request runs, the page shows the current research stage. A completed answer is separated into:

- **Document evidence** — filing passages with original source links and locators;
- **Financial and market evidence** — typed facts and deterministic calculations with as-of dates;
- **Model inference** — interpretation based on the supplied evidence;
- **Limitations** — scope and timing context needed to read the answer correctly;
- **How this answer was produced** — the approved tools executed by the agent.

For PDFs, citations use the original page number. SEC HTML has no stable native pagination, so it uses an explicit passage locator.

## Review filing changes

Open **Changes**, choose the older and newer annual filings, then run change detection.

The workflow identifies candidate additions, deletions, strengthened language, weakened language and material rewrites. Each result preserves both original excerpts and both source locators.

Review decisions are explicit:

- **Confirm** — the candidate represents a material disclosure change;
- **Reject** — the candidate should not be treated as a material change;
- **Needs edit** — the paired evidence is useful but the classification or wording needs revision.

Rerunning a comparison creates a linked historical run instead of overwriting the earlier record.

## Compare companies

Open **Compare** from a selected company, add one or two peers, then enter a common research question. Use comparable periods and units when interpreting financial values. The result uses the same document, financial and calculation boundaries for every company.

## A-share workflow

The established A-share interface provides:

- **Overview** — market and account summary;
- **Research** — company lookup and official report synchronization;
- **Quant** — ranked signals, model methodology, walk-forward records and Explorer;
- **Portfolio** — P&L, holdings and target weights;
- **Execution** — planned orders, order history and daemon controls.

## Capability status

All five stages remain visible. A small status indicator is returned by `GET /api/markets/{market}/capabilities` and means:

- **Live** — the server currently permits the listed customer actions;
- **In validation** — evidence or model validation is active, with restricted actions;
- **Planned** — the page explains the intended workflow but exposes no fake action or empty operational table.

US Execution is readiness-only: it does not connect a Futu US account and cannot generate or submit broker orders.

Administrator-only pages expose pipeline control, model validation, activation history and system monitoring.

## Reading financial information responsibly

- Check the as-of date before comparing prices or market metrics.
- Open cited filings before relying on a qualitative claim.
- Treat model inference as analysis, not documentary fact.
- Do not interpret research rankings or paper results as a promise of future returns.
- Use original filings and regulated professional advice when making financial decisions.
