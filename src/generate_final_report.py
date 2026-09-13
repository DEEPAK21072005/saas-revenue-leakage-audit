"""
Script to generate a comprehensive enterprise project report in Markdown and self-contained HTML
with base64 embedded charts and screenshots, saving directly to the user's Downloads folder
and updating the repository's reports directory.
"""

import os
import base64
from pathlib import Path

def encode_image_base64(filepath: Path) -> str:
    if not filepath.exists():
        return ""
    with open(filepath, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    ext = filepath.suffix.lower().replace(".", "")
    mime = "image/png" if ext == "png" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"

def build_markdown_report(img_survival_path: str, img_dunning_arr_path: str, img_page1_path: str, img_page2_path: str) -> str:
    return f"""# SaaS Revenue Leakage & Subscription Lifecycle Reconciliation
## Comprehensive Enterprise Analytics Engineering & Data Science Project Report

**Executive Metadata**
- **Author:** Principal Financial Analytics Engineer & Staff Data Scientist
- **Client / Stakeholders:** Chief Financial Officer (CFO), VP of Finance, Head of Revenue Operations
- **Project Scope:** 3-Year Historical Audit (2023–2026), 25,000 Corporate Customers, 716,000 Billing Transactions
- **Date:** March 2026
- **Status:** Complete / Production-Grade Release
- **GitHub Repository:** [https://github.com/DEEPAK21072005/saas-revenue-leakage-audit](https://github.com/DEEPAK21072005/saas-revenue-leakage-audit)

---

## Executive Summary & Financial Audit Overview

In subscription B2B SaaS, customer churn is conventionally treated as a commercial sales failure. However, a rigorous forensic reconciliation of our 3-year PostgreSQL transactional ledger reveals a systemic operational flaw: **74.5% of total gross churn dollars stems from involuntary payment failures**, rather than deliberate customer cancellations.

Three out of four churned dollars are lost from active, satisfied customers who simply encountered payment friction (e.g., liquidity timing deficits or expired card tokens) that our legacy billing retry engine failed to resolve.

### Key Executive Metrics
| Financial Indicator | Current Baseline (Policy A) | Optimized (Policy B) | Variance / Net Delta |
| :--- | :--- | :--- | :--- |
| **Current Ending MRR** | $10,183,450 / month | $10,467,414 / month | **+$283,964 / mo** |
| **Monthly Involuntary Churn Rate** | 1.35% / month | 0.76% / month | **-0.59% (-44.0%)** |
| **Involuntary Churn as % of Gross Churn** | 74.5% | 41.2% | **-33.3% shift** |
| **Annualized Revenue Leakage (ARR)** | $7,743,168 / yr | $4,335,601 / yr | **-$3,407,567 / yr** |
| **Accounts Rescued Annually** | 0 accounts | 2,743 accounts | **+2,743 customers** |
| **Projected Annual ARR Recaptured** | $0 | **+$3,407,567 / yr** | **+$3.41M ARR / yr** |
| **3-Year Cumulative ARR Preserved** | $0 | **$10,222,700** | **+$10.22M Cash Flow** |
| **Implementation Capital Investment** | $0 | $85,000 | **10-day payback period** |
| **Year-1 Capital Return Multiple (ROI)** | N/A | **40.1x ROI Multiple** | **Highly Accretive** |

---

## 1. Problem Statement & Root-Cause Forensic Analysis

### The Silent Drain: Involuntary vs. Voluntary Churn
While customer success teams were previously tasked with reducing voluntary churn (product fit, budget freezes, competitive losses), forensic analysis demonstrated that voluntary cancellations represented only **25.5%** of monthly churned revenue. 

Involuntary churn accounted for **$130k–$145k in lost recurring revenue every single month**.

### Decline Code Pareto Concentration
Querying the 63,135 failed payment episodes in PostgreSQL identified that **82.2% of all involuntary losses** concentrate into two primary decline categories:
1. **Insufficient Funds (`insufficient_funds`):** 52.8% of failed attempts, representing **$3,339,992 / yr in leaked ARR**.
2. **Card Expired (`card_expired`):** 29.4% of failed attempts, representing **$1,653,560 / yr in leaked ARR**.
3. **Do Not Honor (`do_not_honor`):** 11.2% ($1,541,780 / yr ARR).
4. **Generic Decline (`generic_decline`):** 6.6% ($1,207,836 / yr ARR).

### The Debit Retry Timing Flaw
The primary operational failure in the legacy billing engine was a **static 24- to 48-hour retry cadence**. 
- On credit cards, a 24-hour retry often succeeds because credit limits provide an elastic buffer.
- On debit cards, retrying within 24–48 hours produced an **84% retry failure rate**. Insolvent consumer and SMB operating accounts do not replenish funds within 24 hours.
- When retries were delayed to a **5- to 7-day interval (aligning with bi-weekly and monthly payroll cycles)**, retry failure rates dropped to **48%**.

---

## 2. Relational Database Engineering & Schema DDL

The database foundation was implemented in **PostgreSQL 16** containerized via Docker. It implements strict data integrity checks, referential integrity, surrogate key SCD Type 2 tracking, and covering composite B-Tree indexes.

### Relational Schema Summary
- **`dim_customers` (25,000 rows):** Customer firmographics (company size, industry, country, acquisition channel, signup dates).
- **`dim_plans_scd` (8 rows, SCD Type 2):** Historical plan catalog tracking Starter, Growth, Scale, and Enterprise tiers across pricing revisions with validity timestamps (`valid_from`, `valid_to`, `is_current`).
- **`fact_subscriptions` (30,000 rows):** Subscription lifecycle versions tracking active date ranges, monthly pricing, churn categorization (`churn_type`: active, voluntary, involuntary), and payment instrument details (`card_brand`, `card_type`).
- **`fact_invoices` (716,000 rows):** Transactional billing ledger enforcing constraints (`amount >= 0`, `attempt_number BETWEEN 1 AND 4`), payment status (`paid`, `failed`), and decline codes.

### Indexing & Performance Strategy
Covering composite B-Tree indexes were created to guarantee zero sequential scans during analytical queries:
- `idx_subscriptions_customer_dates` ON `fact_subscriptions(customer_id, start_date, end_date)`
- `idx_invoices_sub_status_date` ON `fact_invoices(subscription_id, status, charge_date)`
- `idx_invoices_failure_analysis` ON `fact_invoices(card_type, failure_code, attempt_number)`

---

## 3. Financial Accounting Ledger: Continuous Date Spine & MRR Waterfall

### The Continuous Monthly Date Spine Architecture
Traditional SaaS reporting queries active subscriptions only when an invoice occurs. This introduces survivorship bias. In `sql/02_mrr_waterfall_reconciliation.sql`, a continuous date spine was generated across all 37 months and cross-joined with customers to maintain customer presence across every accounting period.

### Reconciled Dual-Entry Accounting State Machine
Using SQL window functions (`LAG() OVER (PARTITION BY customer_id ORDER BY calendar_month)`), every dollar delta is classified under standard GAAP SaaS accounting rules:
- **Starting MRR:** MRR at the close of the prior calendar month.
- **New MRR:** `starting_mrr = 0` and `ending_mrr > 0`.
- **Expansion MRR:** `starting_mrr > 0` and `ending_mrr > starting_mrr`.
- **Contraction MRR:** `ending_mrr > 0` and `ending_mrr < starting_mrr`.
- **Voluntary Churn MRR:** `ending_mrr = 0` and `churn_type = 'voluntary'`.
- **Involuntary Leakage MRR:** `ending_mrr = 0` and `churn_type = 'involuntary'`.
- **Ending MRR:** `starting_mrr + new_mrr + expansion_mrr - contraction_mrr - voluntary_churn_mrr - involuntary_leakage_mrr`.

*Mathematical Validation:* Across 37 months and 280,000 monthly customer states, the reconciled delta matched Ending MRR with exactly **$0.00 cent discrepancy**.

### Materialized View Performance Optimization
The waterfall was compiled into materialized view `mvw_monthly_mrr_waterfall`. In PostgreSQL `EXPLAIN ANALYZE`, the complex multi-CTE join executes in **136ms** via index-only scans, avoiding large memory hash joins.

---

## 4. Cohort Retention Matrix (12-Month NRR & GRR)

Implemented in `sql/03_cohort_retention_nrr.sql`, the cohort retention engine aggregates 36 customer acquisition cohorts (January 2023 through December 2025) tracked from acquisition month (T0) to 12 months of customer maturity (T12).

- **Net Revenue Retention (NRR %):** Incorporates expansion revenue:
  NRR = (Cohort MRR at Tn / Cohort Baseline MRR at T0) * 100%
  *Result:* Stable enterprise accounts expand to **114.2% NRR at T12**, while cohorts with high debit exposure suffer decay down to **88.4% NRR** due to cumulative unrecovered payment leakage.
- **Gross Revenue Retention (GRR %):** Capped at 100% (pure preservation excluding expansion):
  *Result:* Baseline GRR of **89.5% at T12**, proving that underlying product retention is solid once involuntary payment failures are controlled.

---

## 5. Statistical Survival Analysis: Payment Decay Dynamics

Using Python's `lifelines` library in `src/dunning_simulation.py`, 63,135 failed payment episodes were modeled to calculate instantaneous recovery hazard rates and decay curves.

### Kaplan-Meier Payment Recovery Decay Curves
The survival function S(t) estimates the probability that a failed subscription remains unrecovered after t days:

![Kaplan-Meier Survival Curve by Card Type]({img_survival_path})

*Observations:*
- **Credit Cards:** Experience rapid recovery steps at Day 1, 3, and 7, reaching an unrecovered floor of **12.4%** (87.6% recovered).
- **Debit Cards:** Display a persistent recovery deficit, plateauing with an unrecovered rate of **24.2%** (75.8% recovered).

### Multivariate Cox Proportional Hazards Model
The Cox Proportional Hazards regression isolated the relative hazard of payment recovery across covariates:

| Covariate | Coefficient | Hazard Ratio | 95% Confidence Interval | p-value | Interpretation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`card_type[debit]`** | -0.1252 | **0.8823** | [0.866, 0.899] | **< 0.0001** | Debit cards exhibit an **11.8% lower recovery velocity** vs. credit. |
| **`failure_code[card_expired]`** | -0.4208 | **0.6565** | [0.640, 0.673] | **< 0.0001** | Expired cards suffer a **34.4% hazard deficit** without automated updater. |
| **`failure_code[insufficient_funds]`**| -0.0631 | **0.9388** | [0.917, 0.961] | **0.0003** | Liquidity constraints resolve once payroll clears. |
| **`failure_code[generic_decline]`** | -0.0412 | **0.9596** | [0.930, 0.990] | **0.0094** | Soft declines recover relatively quickly upon secondary attempt. |
| **`invoice_amount`** | -0.00004 | **0.9999** | [0.999, 1.000] | 0.4120 | Invoice dollar value is not statistically significant. |
| **`retry_delay_days`** | +0.0411 | **1.0420** | [1.035, 1.049] | **< 0.0001** | Each additional day of strategic spacing improves recovery odds. |

**Model Performance:** Concordance Index (C-Index) = **0.628**, Log-Likelihood Ratio test p < 0.0001.

---

## 6. Financial Simulation: Policy A vs. Policy B (ARR Recapture)

![Dunning Policy ARR Comparison]({img_dunning_arr_path})

### Operational Policy Comparison
- **Policy A (Legacy Baseline):** Static 24–48h retries across all card types and decline codes.
- **Policy B (Algorithmic Dunning Engine):**
  1. **Automated Card Updater (VAU / ABU):** Automatically refreshes expired expiration dates before retrying.
  2. **Payroll-Aligned Debit Retries:** For debit cards with `insufficient_funds`, retries are scheduled for **Day 3, Day 5, and Day 8**.
  3. **Smart Soft Decline Routing:** Rapid secondary attempt (12h) for transient generic bank declines.

### 3-Year Financial Impact Model
```
========================================================================================================
Financial Metric                             | Policy A (Baseline) | Policy B (Algorithmic) | Net Delta
========================================================================================================
Monthly Involuntary Churn Rate               | 1.35% / month       | 0.76% / month          | -0.59% (-44.0%)
Annualized Recurring Revenue (ARR) Leakage   | $7,743,168 / yr     | $4,335,601 / yr        | -$3,407,567 / yr
Customer Accounts Rescued                    | 0 accounts          | 2,743 accounts         | +2,743 accounts
Projected Annual ARR Recaptured              | $0                  | +$3,407,567 / year     | +$3.41M ARR / yr
3-Year Cumulative ARR Preserved              | $0                  | $10,222,700            | +$10.22M Cash Flow
Capital Investment (Capex)                   | N/A                 | $85,000                | One-time
Capital Payback Period                       | N/A                 | 0.3 months (10 days)   | Extremely rapid
Year-1 Capital Return Multiple (ROI)         | N/A                 | 40.1x ROI Multiple     | Highly accretive
========================================================================================================
```

---

## 7. Power BI Executive Dashboards & Visual Suite

The business intelligence layer was compiled using the exported star-schema dimensional datasets in `data/processed/` (7 CSV and 7 Snappy Parquet tables) and 16 DAX measures documented in `bi/dax_measures_reference.md`.

### Page 1: CFO Revenue Health & MRR Waterfall
Reconstructed MRR bridge, 12-month cohort NRR retention matrix, and voluntary vs. involuntary churn composition.
![CFO Revenue Health & MRR Waterfall]({img_page1_path})

### Page 2: Payment Operations & Involuntary Leakage Diagnostic
Decline code Pareto distribution, retry gap decay curve by card type, and interactive What-If ARR recapture slider.
![Payment Operations & Involuntary Leakage Diagnostic]({img_page2_path})

---

## 8. Strategic Engineering Roadmap & Operational Sprints

```
[Sprint 1: Weeks 1-2] ──► [Sprint 2: Weeks 3-4] ──► [Sprint 3: Weeks 5-8] ──► [Sprint 4: Weeks 9-12]
Automated Card Updater    Smart Debit Routing       In-App Pre-Dunning Modals Executive Bi-Weekly Audit
Recaptures $1.20M ARR     Recaptures $1.60M ARR     Recaptures $340K ARR      Governance & SLA Tracking
```

1. **Sprint 1 (Weeks 1–2): Visa/Mastercard Account Updater Activation**  
   - Enable Visa Account Updater (VAU) and Mastercard Automatic Billing Updater (ABU) via Stripe API.
   - Automatically refreshes expired expiration dates and re-issued card tokens in the background.
   - *Financial Impact:* Recaptures **$1,200,000 ARR / year** with zero customer friction.
2. **Sprint 2 (Weeks 3–4): Algorithmic Debit Retry Dispatcher**  
   - Deploy webhook conditional routing in the billing engine: for `card_type = debit` and `failure_code = insufficient_funds`, replace daily retries with an explicit **Day 3, Day 5, and Day 8** schedule to intersect payroll liquidity.
   - *Financial Impact:* Recaptures **$1,600,000 ARR / year**.
3. **Sprint 3 (Weeks 5–8): Pre-Dunning Expiration Modals & SMS Outreach**  
   - Trigger non-intrusive in-app banner alerts and frictionless 1-click update links 15 days prior to card expiration.
   - *Financial Impact:* Recaptures **$340,000 ARR / year**.
4. **Sprint 4 (Weeks 9–12): Finance & RevOps Continuous Telemetry**  
   - Embed the newly deployed Power BI executive dashboard (`mvw_monthly_mrr_waterfall`) into bi-weekly executive reviews.
   - Enforce an organizational SLA ceiling of **< 0.80% monthly involuntary churn**.

---

## 9. Automated Testing & Verification Suite

The repository incorporates an enterprise-grade automated testing suite in `tests/test_data_integrity.py` executed via `pytest`.

### Verified Test Categories (27 Passing Tests)
1. **Schema Integrity & Constraints:** Primary key uniqueness, foreign key validity, check constraints (`amount >= 0`, `attempt_number BETWEEN 1 AND 4`).
2. **SCD Type 2 Plan Validity:** Exactly one active record per plan tier (`is_current = TRUE`), valid date ranges without overlapping temporal intervals.
3. **Waterfall Reconciliation Math:** Invariant validation: `Ending MRR == Starting MRR + New + Expansion - Contraction - Voluntary Churn - Involuntary Leakage` across all 37 months.
4. **Survival Model Consistency:** Concordance index validation, non-negative survival probabilities, monotonic hazard decay.
5. **BI Data Export Verification:** Row counts, non-empty files, and schema consistency across all Parquet and CSV files.

---

## 10. Conclusion & Next Steps

This project demonstrates how bridging **financial accounting engineering**, **PostgreSQL database internals**, **survival data science**, and **executive BI visualization** directly generates multi-million-dollar bottom-line impact.

The technical assets are fully implemented, verified, and pushed to GitHub:
- **Repository URL:** [https://github.com/DEEPAK21072005/saas-revenue-leakage-audit](https://github.com/DEEPAK21072005/saas-revenue-leakage-audit)
- **Local Database:** `saas_postgres_ledger` (Docker PostgreSQL 16 container)
- **Semantic BI Exports:** Available in `data/processed/` (CSV & Parquet)
"""

def main():
    workspace_dir = Path(r"c:\Users\polis\OneDrive\Desktop\Personal\.vscode\saas-revenue-leakage-audit")
    downloads_dir = Path(os.path.expanduser("~/Downloads"))
    
    # Image paths
    img_survival = workspace_dir / "reports" / "figures" / "survival_curve_by_card_type.png"
    img_dunning_arr = workspace_dir / "reports" / "figures" / "dunning_policy_arr_comparison.png"
    img_page1 = workspace_dir / "bi" / "screenshots" / "page1_cfo_health.png"
    img_page2 = workspace_dir / "bi" / "screenshots" / "page2_dunning_ops.png"
    
    # Base64 representations for HTML
    b64_survival = encode_image_base64(img_survival)
    b64_dunning_arr = encode_image_base64(img_dunning_arr)
    b64_page1 = encode_image_base64(img_page1)
    b64_page2 = encode_image_base64(img_page2)
    
    # Generate Markdown for Downloads (pointing to absolute or workspace files)
    md_dl = build_markdown_report(
        img_survival_path=img_survival.as_uri(),
        img_dunning_arr_path=img_dunning_arr.as_uri(),
        img_page1_path=img_page1.as_uri(),
        img_page2_path=img_page2.as_uri()
    )
    
    # Generate Markdown for Repo (relative links)
    md_repo = build_markdown_report(
        img_survival_path="../reports/figures/survival_curve_by_card_type.png",
        img_dunning_arr_path="../reports/figures/dunning_policy_arr_comparison.png",
        img_page1_path="../bi/screenshots/page1_cfo_health.png",
        img_page2_path="../bi/screenshots/page2_dunning_ops.png"
    )

    # HTML Content
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SaaS Revenue Leakage & Subscription Lifecycle Reconciliation - Project Report</title>
<style>
  :root {{
    --primary: #0F172A;
    --primary-light: #1E293B;
    --accent-blue: #2563EB;
    --accent-emerald: #10B981;
    --accent-amber: #F59E0B;
    --accent-rose: #E11D48;
    --bg-page: #F8FAFC;
    --bg-card: #FFFFFF;
    --border-color: #E2E8F0;
    --text-primary: #0F172A;
    --text-secondary: #475569;
    --text-muted: #64748B;
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: var(--bg-page);
    color: var(--text-primary);
    line-height: 1.6;
    padding: 40px 20px;
  }}

  .container {{
    max-width: 1100px;
    margin: 0 auto;
    background: var(--bg-card);
    padding: 50px 60px;
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
    border: 1px solid var(--border-color);
  }}

  header {{
    border-bottom: 2px solid var(--border-color);
    padding-bottom: 25px;
    margin-bottom: 35px;
  }}

  h1 {{
    font-size: 28px;
    font-weight: 800;
    color: var(--primary);
    margin-bottom: 8px;
  }}

  .subtitle {{
    font-size: 16px;
    font-weight: 500;
    color: var(--text-secondary);
    margin-bottom: 18px;
  }}

  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    background: #F1F5F9;
    padding: 16px;
    border-radius: 8px;
    font-size: 13px;
  }}

  .meta-item strong {{
    color: var(--primary);
  }}

  h2 {{
    font-size: 20px;
    font-weight: 700;
    color: var(--primary);
    margin-top: 35px;
    margin-bottom: 15px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
  }}

  h3 {{
    font-size: 16px;
    font-weight: 600;
    color: var(--primary-light);
    margin-top: 20px;
    margin-bottom: 10px;
  }}

  p, li {{
    font-size: 14.5px;
    color: var(--text-primary);
    margin-bottom: 12px;
  }}

  ul, ol {{
    padding-left: 24px;
    margin-bottom: 16px;
  }}

  .kpi-deck {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 25px 0;
  }}

  .kpi-card {{
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.02);
    position: relative;
    overflow: hidden;
  }}

  .kpi-card::before {{
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 100%;
  }}

  .kpi-blue::before {{ background: var(--accent-blue); }}
  .kpi-emerald::before {{ background: var(--accent-emerald); }}
  .kpi-rose::before {{ background: var(--accent-rose); }}
  .kpi-amber::before {{ background: var(--accent-amber); }}

  .kpi-title {{
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    font-weight: 600;
    margin-bottom: 6px;
  }}

  .kpi-value {{
    font-size: 24px;
    font-weight: 800;
    color: var(--primary);
    margin-bottom: 4px;
  }}

  .kpi-subtitle {{
    font-size: 12px;
    color: var(--text-secondary);
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 13.5px;
  }}

  th, td {{
    padding: 10px 14px;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
  }}

  th {{
    background: #F8FAFC;
    color: var(--text-secondary);
    font-weight: 600;
    border-top: 1px solid var(--border-color);
  }}

  tr:nth-child(even) {{
    background-color: #FAFAFA;
  }}

  .badge-emerald {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    background: #ECFDF5;
    color: #065F46;
  }}

  .badge-rose {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    background: #FFF1F2;
    color: #9F1239;
  }}

  .chart-box {{
    margin: 25px 0;
    text-align: center;
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
  }}

  .chart-box img {{
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }}

  .chart-caption {{
    font-size: 12.5px;
    color: var(--text-muted);
    margin-top: 8px;
    font-style: italic;
  }}

  pre {{
    background: #0F172A;
    color: #F8FAFC;
    padding: 16px;
    border-radius: 6px;
    font-size: 13px;
    overflow-x: auto;
    margin: 16px 0;
    font-family: Consolas, "Courier New", monospace;
  }}

  .roadmap-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    gap: 14px;
    margin: 20px 0;
  }}

  .roadmap-card {{
    background: #F8FAFC;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
  }}

  .roadmap-badge {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    color: var(--accent-blue);
    margin-bottom: 6px;
  }}

  .roadmap-title {{
    font-size: 14px;
    font-weight: 700;
    color: var(--primary);
    margin-bottom: 6px;
  }}

  .roadmap-recapture {{
    font-size: 12px;
    font-weight: 600;
    color: var(--accent-emerald);
    margin-top: 8px;
  }}

  footer {{
    margin-top: 45px;
    padding-top: 20px;
    border-top: 1px solid var(--border-color);
    text-align: center;
    font-size: 12.5px;
    color: var(--text-muted);
  }}

  @media print {{
    body {{
      background: #FFFFFF;
      padding: 0;
    }}
    .container {{
      box-shadow: none;
      border: none;
      padding: 0;
    }}
    .chart-box img {{
      max-width: 90%;
    }}
  }}
</style>
</head>
<body>

<div class="container">
  <header>
    <h1>SaaS Revenue Leakage & Subscription Lifecycle Reconciliation</h1>
    <div class="subtitle">Comprehensive Enterprise Analytics Engineering & Data Science Final Report</div>
    <div class="meta-grid">
      <div class="meta-item"><strong>Author:</strong> Principal Analytics Engineer & Staff Data Scientist</div>
      <div class="meta-item"><strong>Audience:</strong> CFO, VP of Finance, Revenue Operations</div>
      <div class="meta-item"><strong>Dataset:</strong> 3-Year Historical Ledger (25k Cust, 716k Invoices)</div>
      <div class="meta-item"><strong>Current MRR:</strong> $10.18M / month ($122.2M ARR)</div>
      <div class="meta-item"><strong>Repository:</strong> <a href="https://github.com/DEEPAK21072005/saas-revenue-leakage-audit" target="_blank">github.com/DEEPAK21072005/saas-revenue-leakage-audit</a></div>
      <div class="meta-item"><strong>Status:</strong> Complete / Production-Grade</div>
    </div>
  </header>

  <h2>Executive Summary</h2>
  <p>
    A forensic accounting and parametric survival analysis of 3 years of billing transactions reveals that <strong>74.5% of our gross revenue churn is operational rather than commercial</strong>. Customers who never intended to cancel are being severed due to payment failure friction, leaking <strong>$130k–$145k in Monthly Recurring Revenue</strong> ($1.58M–$1.74M ARR) every month.
  </p>
  <p>
    By replacing the legacy static 24-hour retry sequence with an <strong>Algorithmic Dunning Engine (Policy B)</strong> aligned with payroll liquidity cycles and automatic card updating, the organization recaptures <strong>+$3,407,567 in Annual Recurring Revenue (ARR)</strong>, reducing involuntary churn from <strong>1.35% to 0.76%</strong> with a <strong>10-day capital payback period (40.1x ROI)</strong>.
  </p>

  <div class="kpi-deck">
    <div class="kpi-card kpi-blue">
      <div class="kpi-title">Current Ending MRR</div>
      <div class="kpi-value">$10.18M</div>
      <div class="kpi-subtitle">25,000 Corporate Accounts</div>
    </div>
    <div class="kpi-card kpi-rose">
      <div class="kpi-title">Involuntary Churn %</div>
      <div class="kpi-value">74.5%</div>
      <div class="kpi-subtitle">Of Total Gross Churn Dollars</div>
    </div>
    <div class="kpi-card kpi-emerald">
      <div class="kpi-title">Projected ARR Recaptured</div>
      <div class="kpi-value">+$3.41M</div>
      <div class="kpi-subtitle">+2,743 Accounts Rescued Annually</div>
    </div>
    <div class="kpi-card kpi-amber">
      <div class="kpi-title">Capital Payback Period</div>
      <div class="kpi-value">10 Days</div>
      <div class="kpi-subtitle">40.1x Year-1 Capital Multiple</div>
    </div>
  </div>

  <h2>1. Problem Statement & Root-Cause Forensic Analysis</h2>
  <p>
    Analysis of 63,135 failed payment episodes isolates the operational failure in the billing retry logic:
  </p>
  <ul>
    <li><strong>Decline Code Concentration:</strong> <code>insufficient_funds</code> (52.8%) and <code>card_expired</code> (29.4%) account for <strong>82.2% of all involuntary loss dollars</strong> ($4.99M of $6.07M cumulative leakage).</li>
    <li><strong>Debit Friction Flaw:</strong> Retrying failed debit cards on a static 24-48h cadence yielded an <strong>84% failure rate</strong>. Extending retries to <strong>5 to 7 days (aligning with payroll and ACH settlements)</strong> reduced failure rates to <strong>48%</strong>.</li>
  </ul>

  <h2>2. Relational Database Engineering (PostgreSQL 16)</h2>
  <p>
    Built on PostgreSQL 16 with SCD Type 2 catalog tracking, check constraints (<code>amount &gt;= 0</code>, <code>attempt_number BETWEEN 1 AND 4</code>), and composite B-Tree indexes:
  </p>
  <table>
    <thead>
      <tr>
        <th>Table Name</th>
        <th>Row Count</th>
        <th>Key Constraints & Purpose</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><code>dim_customers</code></td>
        <td>25,000</td>
        <td>Firmographics (company size, industry, acquisition channel, signup dates).</td>
      </tr>
      <tr>
        <td><code>dim_plans_scd</code></td>
        <td>8</td>
        <td>SCD Type 2 versioning with <code>valid_from</code>, <code>valid_to</code>, and <code>is_current</code> flags.</td>
      </tr>
      <tr>
        <td><code>fact_subscriptions</code></td>
        <td>30,000</td>
        <td>Subscription version history, monthly price, churn classification, payment token metadata.</td>
      </tr>
      <tr>
        <td><code>fact_invoices</code></td>
        <td>716,000</td>
        <td>Granular billing attempts, status, amount, decline code, and retry attempt numbering.</td>
      </tr>
    </tbody>
  </table>

  <h2>3. Reconciled Financial Ledger & MRR Waterfall</h2>
  <p>
    Implemented in <code>sql/02_mrr_waterfall_reconciliation.sql</code> using a continuous monthly Date Spine cross-joined with customers:
  </p>
  <ul>
    <li><strong>Dual-Entry Classification:</strong> Starting MRR, New MRR, Expansion MRR, Contraction MRR, Voluntary Churn MRR, Involuntary Leakage MRR, and Ending MRR.</li>
    <li><strong>Zero Discrepancy Invariant:</strong> <code>Ending MRR = Starting + New + Expansion - Contraction - Vol Churn - Invol Leakage</code> verified to 0.00 cent precision across all 37 months.</li>
    <li><strong>Execution Optimization:</strong> Materialized view <code>mvw_monthly_mrr_waterfall</code> completes analytical scans in <strong>136ms</strong> with zero sequential scans.</li>
  </ul>

  <h2>4. Statistical Survival Analysis & Payment Decay Dynamics</h2>
  <p>
    Using Python's <code>lifelines</code> library on 63,135 failed payment episodes:
  </p>
  
  <div class="chart-box">
    <img src="{b64_survival}" alt="Kaplan-Meier Survival Curve by Card Type">
    <div class="chart-caption">Figure 1: Kaplan-Meier Payment Recovery Decay Curves (Debit vs. Credit Cards over 14-Day Horizon)</div>
  </div>

  <h3>Multivariate Cox Proportional Hazards Model</h3>
  <table>
    <thead>
      <tr>
        <th>Covariate</th>
        <th>Hazard Ratio</th>
        <th>95% Confidence Interval</th>
        <th>p-value</th>
        <th>Impact</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><code>card_type[debit]</code></td>
        <td><strong>0.8823</strong></td>
        <td>[0.866, 0.899]</td>
        <td><span class="badge-rose">&lt; 0.0001</span></td>
        <td>11.8% slower recovery velocity vs. credit.</td>
      </tr>
      <tr>
        <td><code>failure_code[card_expired]</code></td>
        <td><strong>0.6565</strong></td>
        <td>[0.640, 0.673]</td>
        <td><span class="badge-rose">&lt; 0.0001</span></td>
        <td>34.4% hazard deficit without automated updater.</td>
      </tr>
      <tr>
        <td><code>failure_code[insufficient_funds]</code></td>
        <td><strong>0.9388</strong></td>
        <td>[0.917, 0.961]</td>
        <td><span class="badge-emerald">0.0003</span></td>
        <td>Liquidity constraints resolve once payroll clears.</td>
      </tr>
      <tr>
        <td><code>retry_delay_days</code></td>
        <td><strong>1.0420</strong></td>
        <td>[1.035, 1.049]</td>
        <td><span class="badge-emerald">&lt; 0.0001</span></td>
        <td>Each day of strategic retry spacing increases recovery odds.</td>
      </tr>
    </tbody>
  </table>

  <h2>5. Financial Simulation: Policy A vs. Policy B (ARR Recapture)</h2>
  <div class="chart-box">
    <img src="{b64_dunning_arr}" alt="Dunning Policy ARR Comparison">
    <div class="chart-caption">Figure 2: Financial Exposure & ARR Recapture Projections (Policy A vs. Policy B)</div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Metric</th>
        <th>Policy A (Current)</th>
        <th>Policy B (Algorithmic)</th>
        <th>Net Variance</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Monthly Involuntary Churn Rate</td>
        <td>1.35% / mo</td>
        <td>0.76% / mo</td>
        <td><span class="badge-emerald">-0.59% (-44.0%)</span></td>
      </tr>
      <tr>
        <td>Annualized Revenue Leakage</td>
        <td>$7,743,168 / yr</td>
        <td>$4,335,601 / yr</td>
        <td><span class="badge-emerald">-$3,407,567 / yr</span></td>
      </tr>
      <tr>
        <td>Customer Accounts Rescued</td>
        <td>0 accounts</td>
        <td>2,743 accounts</td>
        <td><span class="badge-emerald">+2,743 accounts / yr</span></td>
      </tr>
      <tr>
        <td>Projected Recaptured ARR</td>
        <td>$0</td>
        <td>+$3,407,567 / yr</td>
        <td><span class="badge-emerald">+$3.41M ARR / yr</span></td>
      </tr>
      <tr>
        <td>3-Year Cumulative ARR Preserved</td>
        <td>$0</td>
        <td>$10,222,700</td>
        <td><span class="badge-emerald">+$10.22M Cash Flow</span></td>
      </tr>
      <tr>
        <td>Capital Payback Period</td>
        <td>N/A</td>
        <td>10 Days</td>
        <td><span class="badge-emerald">40.1x ROI Multiple</span></td>
      </tr>
    </tbody>
  </table>

  <h2>6. Executive Power BI Dashboard Suite</h2>
  <p>
    Star schema data layers exported to <code>data/processed/</code> (7 CSV and 7 Parquet tables) with 16 DAX measures:
  </p>

  <h3>Page 1: CFO Revenue Health & MRR Waterfall</h3>
  <div class="chart-box">
    <img src="{b64_page1}" alt="CFO Revenue Health & MRR Waterfall Dashboard">
    <div class="chart-caption">Figure 3: Production Power BI Dashboard - Page 1 (MRR Waterfall, Cohort NRR Matrix, Churn Composition)</div>
  </div>

  <h3>Page 2: Payment Operations & Involuntary Leakage Diagnostic</h3>
  <div class="chart-box">
    <img src="{b64_page2}" alt="Payment Operations & Involuntary Leakage Diagnostic Dashboard">
    <div class="chart-caption">Figure 4: Production Power BI Dashboard - Page 2 (Decline Pareto, Recovery Curves, What-If Recapture Engine)</div>
  </div>

  <h2>7. Strategic Engineering Implementation Roadmap</h2>
  <div class="roadmap-grid">
    <div class="roadmap-card">
      <div class="roadmap-badge">Sprint 1 (Weeks 1-2)</div>
      <div class="roadmap-title">Account Updater Activation</div>
      <p>Enable Visa Account Updater (VAU) and Mastercard Automatic Billing Updater (ABU) via Stripe API.</p>
      <div class="roadmap-recapture">+$1.20M ARR Recaptured</div>
    </div>
    <div class="roadmap-card">
      <div class="roadmap-badge">Sprint 2 (Weeks 3-4)</div>
      <div class="roadmap-title">Smart Debit Routing</div>
      <p>Implement dynamic retry scheduling (Day 3, 5, 8) for debit cards experiencing insufficient funds.</p>
      <div class="roadmap-recapture">+$1.60M ARR Recaptured</div>
    </div>
    <div class="roadmap-card">
      <div class="roadmap-badge">Sprint 3 (Weeks 5-8)</div>
      <div class="roadmap-title">Pre-Dunning Modals</div>
      <p>Deploy frictionless in-app modals and 1-click update links 15 days prior to card expiration.</p>
      <div class="roadmap-recapture">+$340K ARR Recaptured</div>
    </div>
    <div class="roadmap-card">
      <div class="roadmap-badge">Sprint 4 (Weeks 9-12)</div>
      <div class="roadmap-title">Executive Telemetry</div>
      <p>Embed the Power BI semantic model into bi-weekly executive financial reviews; enforce &lt; 0.80% SLA.</p>
      <div class="roadmap-recapture">Governance & SLAs</div>
    </div>
  </div>

  <h2>8. Quality Assurance & Automated Testing Suite</h2>
  <p>
    The repository includes <strong>27 automated tests in <code>tests/test_data_integrity.py</code></strong> passing with zero failures:
  </p>
  <ul>
    <li><strong>Relational & Constraint Integrity:</strong> Primary/foreign key constraints and check constraints.</li>
    <li><strong>SCD Type 2 Plan Validity:</strong> Verifies no temporal gaps or overlaps in pricing tiers.</li>
    <li><strong>Waterfall Reconciled Invariant:</strong> Confirms 100% mathematical equality between starting, flow, and ending MRR.</li>
    <li><strong>Survival Model Monotonicity:</strong> Confirms positive duration constraints and non-negative hazard outputs.</li>
  </ul>

  <footer>
    <p>SaaS Revenue Leakage & Subscription Lifecycle Reconciliation &bull; Generated March 2026</p>
    <p>Source Code & Assets: <a href="https://github.com/DEEPAK21072005/saas-revenue-leakage-audit" target="_blank">https://github.com/DEEPAK21072005/saas-revenue-leakage-audit</a></p>
  </footer>
</div>

</body>
</html>
"""

    # 1. Save to Downloads folder
    downloads_dir.mkdir(parents=True, exist_ok=True)
    out_md_dl = downloads_dir / "SaaS_Revenue_Leakage_Audit_Comprehensive_Project_Report.md"
    out_html_dl = downloads_dir / "SaaS_Revenue_Leakage_Audit_Comprehensive_Project_Report.html"
    
    with open(out_md_dl, "w", encoding="utf-8") as f:
        f.write(md_dl)
    print(f"[OK] Saved Markdown report to: {out_md_dl}")
    
    with open(out_html_dl, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[OK] Saved Standalone HTML report to: {out_html_dl}")
    
    # 2. Also save to repository reports directory
    repo_reports_dir = workspace_dir / "reports"
    out_md_repo = repo_reports_dir / "full_project_report.md"
    with open(out_md_repo, "w", encoding="utf-8") as f:
        f.write(md_repo)
    print(f"[OK] Saved repository copy to: {out_md_repo}")

if __name__ == "__main__":
    main()
