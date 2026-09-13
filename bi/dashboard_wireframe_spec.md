# Executive BI Suite: Dashboard Wireframe & Visual Specifications
**Project:** SaaS Revenue Leakage & Subscription Lifecycle Reconciliation  
**Target Platform:** Power BI / Microsoft Fabric / Tableau Desktop  
**Target Audience:** CFO, VP of Finance, Head of Revenue Operations, Payments Engineering Lead  
**Document Version:** 2.0 (Production Release)  

---

## 1. Design System & Global Aesthetic Guidelines

### Corporate Financial Palette
- **Canvas Background:** `#F8FAFC` (Slate 50)
- **Card Surface Background:** `#FFFFFF` (Pure White) with subtle 1px border `#E2E8F0` and `4px` corner radius.
- **Primary Text:** `#0F172A` (Slate 900)
- **Secondary Text / Labels:** `#64748B` (Slate 500)
- **Positive Inflow (New / Expansion):** `#10B981` (Emerald 500) / `#047857` (Emerald 700)
- **Contraction (Downgrade):** `#F59E0B` (Amber 500)
- **Voluntary Churn:** `#D97706` (Amber 600)
- **Involuntary Churn (Revenue Leakage):** `#E11D48` (Rose 600) / `#BE123C` (Rose 700)
- **Retained / Baseline MRR:** `#2563EB` (Blue 600) / `#1E40AF` (Blue 800)
- **Font Hierarchy:** Inter / Segoe UI (Titles: 16pt Bold; KPIs: 26pt Semi-Bold; Data Labels: 10pt Regular).

---

## 2. Page 1: "CFO Revenue Health & MRR Waterfall"

### Layout Grid Overview (1920 × 1080 Native Resolution)
```
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HEADER: SaaS Revenue Health & Monthly MRR Waterfall                [Date Slicer] [Tier] [Industry] │
├──────────────────┬──────────────────┬──────────────────┬──────────────────┬───────────────────────┤
│ KPI 1:           │ KPI 2:           │ KPI 3:           │ KPI 4:           │ KPI 5:                │
│ Ending MRR       │ Net New MRR      │ NRR %            │ GRR %            │ Involuntary Churn %   │
│ $10.18M (▲+19.8%)│ +$375.3K (▲)     │ 98.1% (Target:95)│ 96.9% (Target:90)│ 74.5% of Gross Churn  │
├──────────────────┴──────────────────┴──────────────────┴──────────────────┴───────────────────────┤
│ VISUAL 1: Monthly MRR Waterfall Bridge Chart (Starting → New → Exp → Cont → Vol → Invol → Ending)  │
│ [Waterfall visual displaying positive green inflows, amber voluntary drops, and crimson leakage]  │
├────────────────────────────────────────────────────────┬──────────────────────────────────────────┤
│ VISUAL 2: 12-Month Cohort NRR Retention Heatmap Matrix │ VISUAL 3: Churn Composition Trend        │
│ [Rows: Cohort Month | Columns: T0 → T12 | Color: NRR %] │ [Stacked Area: Voluntary vs Involuntary] │
└────────────────────────────────────────────────────────┴──────────────────────────────────────────┘
```

---

### Component Specifications: Page 1

#### A. Header & Global Slicer Bar (`Y: 0px – 70px`)
- **Title:** "SaaS Revenue Health & MRR Waterfall Ledger"
- **Subtitle:** "Dual-entry reconciled recurring revenue accounting, cohort decay, and leakage tracking"
- **Interactive Slicers:**
  1. `Date Range Slicer`: Relative date or slider on `dim_date[Date]` (Default: Last 12 Months).
  2. `Plan Tier Slicer`: Multi-select dropdown on `dim_plans[plan_name]` (Starter, Growth, Enterprise, Scale).
  3. `Industry Slicer`: Multi-select dropdown on `dim_customers[industry]`.
  4. `Customer Size Slicer`: Single-select dropdown on `dim_customers[company_size]`.

---

#### B. Executive KPI Card Strip (`Y: 85px – 185px`, 5 Cards across 12 Columns)

| Card | Primary Measure | Secondary Comparison | Color Accent | Tooltip Detail |
| :--- | :--- | :--- | :--- | :--- |
| **Card 1** | `[Ending MRR]` | `YoY Growth %` | Blue (`#2563EB`) | Breakdown by plan tier and current active customer headcount |
| **Card 2** | `[Net New MRR]` | `MoM Delta ($)` | Emerald (`#10B981`) | New MRR + Expansion - Contraction - Total Churn |
| **Card 3** | `[Net Revenue Retention % (NRR)]` | `Benchmark: 100%` | Blue (`#1D4ED8`) | LTM weighted NRR across all cohorts |
| **Card 4** | `[Gross Revenue Retention % (GRR)]`| `Benchmark: 90%` | Slate (`#475569`) | Pure revenue preservation excluding upsell credit |
| **Card 5** | `[Involuntary Churn Ratio %]` | `Historical Avg` | Crimson (`#BE123C`) | Involuntary Leakage as % of Gross Churn (Alert if > 25%) |

---

#### C. Visual 1: MRR Waterfall Bridge Chart (`Y: 200px – 580px`)
- **Visual Type:** Power BI Standard Waterfall Chart / Tableau Bridge.
- **Category Axis:** `[Starting MRR]`, `[New MRR]`, `[Expansion MRR]`, `[Contraction MRR]`, `[Voluntary Churn MRR]`, `[Involuntary Leakage MRR]`, `[Ending MRR]`.
- **Y-Axis Values:** DAX measures formatted as `$#,##0`.
- **Color Rules:**
  - Increase (New, Expansion): Emerald (`#10B981`)
  - Decrease (Contraction): Amber (`#F59E0B`)
  - Decrease (Voluntary Churn): Dark Amber (`#D97706`)
  - Decrease (Involuntary Leakage): Crimson (`#E11D48`)
  - Total Pillar (Starting, Ending): Corporate Navy (`#0F172A`)
- **Interaction:** Clicking any pillar cross-filters customer attributes (industry, size) across the page.

---

#### D. Visual 2: 12-Month Cohort NRR Retention Heatmap (`Y: 600px – 1040px`, Left 8 Columns)
- **Visual Type:** Power BI Matrix Visual with Conditional Formatting (Background Color Scale).
- **Data Source:** `agg_cohort_nrr`.
- **Rows:** `agg_cohort_nrr[cohort_month]` formatted as `MMM yyyy`.
- **Columns:** `agg_cohort_nrr[tenure_months]` (`T0` through `T12`).
- **Values:** `MAX(agg_cohort_nrr[nrr_pct])`.
- **Color Ramp (Diverging):**
  - `< 70%`: Soft Crimson (`#FEE2E2`)
  - `85%`: Neutral White (`#FFFFFF`)
  - `100%`: Soft Sky Blue (`#E0F2FE`)
  - `> 110%`: Deep Emerald (`#10B981`)
- **Row Subtotals:** Average Cohort Size (`cohort_size`) and Initial T0 MRR (`total_t0_mrr`).

---

#### E. Visual 3: Churn Breakdown: Voluntary vs. Involuntary (`Y: 600px – 1040px`, Right 4 Columns)
- **Visual Type:** 100% Stacked Bar Chart / Donut Toggle.
- **X-Axis:** `dim_date[calendar_month]`.
- **Y-Axis (Values):** `[Voluntary Churn MRR]` (Amber `#F59E0B`) and `[Involuntary Leakage MRR]` (Crimson `#E11D48`).
- **Data Callout:** Highlights the **70%+ involuntary churn ratio**, demonstrating to executives that 7 out of every 10 lost dollars are operational payment processing failures rather than product churn.

---

## 3. Page 2: "Payment Operations & Involuntary Leakage Diagnostic"

### Layout Grid Overview (1920 × 1080 Native Resolution)
```
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HEADER: Payment Operations Diagnostic & Algorithmic Dunning ROI    [Card Type] [Brand] [Attempt]   │
├──────────────────┬──────────────────┬──────────────────┬──────────────────┬───────────────────────┤
│ DIAGNOSTIC 1:    │ DIAGNOSTIC 2:    │ DIAGNOSTIC 3:    │ DIAGNOSTIC 4:    │ DIAGNOSTIC 5:         │
│ Failed Attempts  │ 1st Fail Rate    │ Recovery Rate    │ Annualized Leak  │ Debit Flaw Deficit    │
│ 218,892 attempts │ 12.0% of billings│ 80.1% recovered  │ $1.58M / yr ARR  │ +12.0% fail on debit  │
├──────────────────┴──────────────────┴──────────────────┴──────────────────┴───────────────────────┤
│ VISUAL 1: Decline Code Pareto Analysis (Loss $ & Cumul %)│ VISUAL 2: Kaplan-Meier Decay Curves    │
│ [Bar: Amount Lost by Code | Line: Cumulative % of Loss] │ [Step line: Debit vs. Credit over 14d]  │
├─────────────────────────────────────────────────────────┴─────────────────────────────────────────┤
│ VISUAL 3: Interactive What-If ARR Recapture Simulation & ROI Engine                              │
│ [Slider: Dunning Optimization Efficiency (0%–50%)] ──► [Gauge: Recaptured ARR] ──► [ROI Multiple]  │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### Component Specifications: Page 2

#### A. Diagnostic KPI Strip (`Y: 85px – 185px`)
1. **Total Failed Invoices:** `COUNTROWS(FILTER(fact_dunning_events, fact_dunning_events[status] = "failed"))`
2. **First-Time Charge Failure Rate %:** `12.0%` (Baseline initial processing decline rate).
3. **Dunning Sequence Recovery Rate %:** `80.1%` (50,573 of 63,135 failed cycles recovered).
4. **Current Involuntary Leakage (ARR):** `[Involuntary Leakage MRR] * 12` (`$1,577,556` run-rate).
5. **Debit Hazard Deficit:** `HR = 0.882` (11.8% slower recovery velocity; p < 0.0001).

---

#### B. Visual 1: Decline Code Pareto Analysis (`Y: 200px – 590px`, Left 6 Columns)
- **Visual Type:** Line and Clustered Column Chart (Pareto Chart).
- **Data Source:** `fact_dunning_events`.
- **Shared X-Axis:** `failure_code` sorted descending by unrecovered dollar volume:
  1. `insufficient_funds`
  2. `card_expired`
  3. `do_not_honor`
  4. `generic_decline`
- **Column Values (Primary Y-Axis):** Total Failed Dollars (`SUM(fact_dunning_events[amount])`) in Rose (`#E11D48`).
- **Line Values (Secondary Y-Axis):** Cumulative Percentage of Total Involuntary Loss (`0% – 100%`) in Corporate Navy (`#0F172A`).
- **Executive Takeaway:** Demonstrates that **Insufficient Funds + Card Expired** constitute **82.2%** of all involuntary leakage dollars (Pareto 80/20 rule).

---

#### C. Visual 2: Kaplan-Meier Payment Recovery Decay Curve (`Y: 200px – 590px`, Right 6 Columns)
- **Visual Type:** Custom Stepped Line Chart (or Image Integration of `reports/figures/survival_curve_by_card_type.png`).
- **X-Axis:** Elapsed Days Since Initial Failure ($0 \to 14$ days).
- **Y-Axis:** Unrecovered Probability $S(t)$ ($0\% \to 100\%$).
- **Series:**
  - `Credit Cards`: Solid Blue (`#2563EB`), Steps at Days 1, 3, 7, 14.
  - `Debit Cards`: Solid Crimson (`#E11D48`), Elevated Unrecovered Plateau.
- **Reference Shading:** Shaded vertical zone between Days 1 and 3 highlighting the **"Static 24-48h Retry Friction Window"**.

---

#### D. Visual 3: Interactive What-If ARR Recapture Simulation & ROI Engine (`Y: 610px – 1040px`, Full Width)
- **Layout:** Horizontal 3-Box Interactive Simulation Pane.
- **Box 1: What-If Parameter Slicer (`Left 3 Columns`)**
  - Single-value slider on `dunning_efficiency_parameter[Value]`.
  - Increments: `0%` to `50%` in steps of `5%` (Default: `25%`).
  - Label: *"Select Target Recovery Lift from Algorithmic Dunning"*.
- **Box 2: Recaptured Financial Impact Gauges (`Middle 5 Columns`)**
  - **KPI Gauge:** `[Projected ARR Recaptured]`. Target Max: `$3.5M`.
  - **Dynamic Card:** `[Projected Monthly Leakage Recaptured]` formatted as `+$XX,XXX / mo`.
  - **Post-Optimization Rate:** `[Projected Post-Optimization Churn Rate %]` displaying baseline `1.35%` dropping to target `0.76%`.
- **Box 3: Engineering ROI & Capital Payback (`Right 4 Columns`)**
  - **Capital Expenditure:** Fixed `$85,000` engineering investment.
  - **Net Added Value:** `[Projected ARR Recaptured] - 85000`.
  - **ROI Multiple Card:** `[What-If Implementation ROI Multiple]` (e.g. `40.1x`).
  - **Payback Time:** `0.3 Months (10 Days)`.

---

## 4. Cross-Filtering, Drill-Through & Security Specifications

### Cross-Filtering Matrix
- Clicking **"Debit Cards"** on Page 1 filters Page 2 to isolate the 969 churned debit accounts and highlights the Day 5 payroll gap.
- Selecting **"Card Expired"** on Visual 1 (Pareto) dynamically updates the What-If simulation to showcase the standalone ROI of deploying an automated Account Updater.

### Drill-Through Actions
- Right-clicking any cohort cell in Visual 2 (Page 1) enables **"Drill-Through $\to$ Cohort Member Ledger"**, displaying individual customer IDs, initial plan tier, and dunning attempt history.

### Row-Level Security (RLS) Roles
1. **`Finance_Executive`**: Unrestricted access to all measures and customer records.
2. **`Payments_Ops_Lead`**: Access to operational transaction logs and decline diagnostics (`fact_dunning_events`), with customer contact PII masked.
3. **`Enterprise_CSM`**: Filtered by `dim_customers[company_size] IN ("501-2000", "2001+")` to manage high-touch account retention.
