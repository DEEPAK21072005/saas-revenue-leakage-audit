# Power BI / Fabric Semantic Model: Production DAX Reference Manual
**Project:** SaaS Revenue Leakage & Subscription Lifecycle Reconciliation  
**Target Platform:** Microsoft Power BI / Microsoft Fabric / Analysis Services  
**Author:** Principal Business Intelligence Architect  
**Version:** 2.0 (Production Release)  
**Schema Architecture:** Star Schema with Kimball Dimensional Modeling  

---

## 1. Enterprise Semantic Model Architecture

```
                                  ┌───────────────────────┐
                                  │       dim_date        │
                                  └──────────┬────────────┘
                                             │ 1
                                             │
                                             │ * (calendar_month)
┌──────────────────────┐  1        * ┌───────┴───────────────┐ *        1 ┌──────────────────────┐
│    dim_customers     ├────────────┤   fact_mrr_monthly    ├────────────┤      dim_plans       │
└──────────┬───────────┘             └───────────────────────┘            └──────────────────────┘
           │ 1
           │
           │ * (customer_id)
┌──────────┴───────────┐
│ fact_dunning_events  │
└──────────────────────┘
```

### Table Dictionary
1. **`fact_mrr_monthly`**: Monthly customer-grain recurring revenue ledger. Grain: `(customer_id, calendar_month)`.
2. **`dim_customers`**: Customer account dimension containing industry, size tier, and acquisition source.
3. **`dim_plans`**: Plan and pricing catalog (SCD Type 2 enabled).
4. **`fact_dunning_events`**: Transactional invoice failure and dunning attempt event log.
5. **`agg_cohort_nrr`**: 12-month tenure cohort retention table for cohort heatmaps.
6. **`dim_date`**: Continuous calendar date spine table.

---

## 2. Core Financial Measures (MRR Waterfall)

### `[Starting MRR]`
Calculates total active recurring revenue contracted at the beginning of the selected calendar period.

```dax
[Starting MRR] = 
/*
    Summary: Contracted Monthly Recurring Revenue at period open.
    Grain  : Fact table customer-month starting_mrr.
    Display: Currency ($#,##0)
*/
VAR _StartingAmount = 
    SUM(fact_mrr_monthly[starting_mrr])
RETURN
    COALESCE(_StartingAmount, 0)
```

---

### `[New MRR]`
Quantifies revenue gained from newly acquired customers entering paid subscriptions within the period ($Starting = 0 \to Ending > 0$).

```dax
[New MRR] = 
/*
    Summary: Organic new subscription revenue from freshly activated customers.
    Logic  : starting_mrr = 0 AND ending_mrr > 0
    Display: Currency ($#,##0)
*/
VAR _NewAmount = 
    CALCULATE(
        SUM(fact_mrr_monthly[new_mrr]),
        KEEPFILTERS(fact_mrr_monthly[mrr_movement_type] = "New MRR")
    )
RETURN
    COALESCE(_NewAmount, 0)
```

---

### `[Expansion MRR]`
Measures expansion uplift from existing customers upgrading plan tiers or adding seat capacity ($Starting > 0 \land Ending > Starting$).

```dax
[Expansion MRR] = 
/*
    Summary: Upgrades, expansion tiers, and scheduled pricing adjustments.
    Logic  : starting_mrr > 0 AND ending_mrr > starting_mrr
    Display: Currency ($#,##0)
*/
VAR _ExpansionAmount = 
    CALCULATE(
        SUM(fact_mrr_monthly[expansion_mrr]),
        KEEPFILTERS(fact_mrr_monthly[mrr_movement_type] = "Expansion MRR")
    )
RETURN
    COALESCE(_ExpansionAmount, 0)
```

---

### `[Contraction MRR]`
Captures contracted revenue decrease from existing customers downgrading tiers while remaining active ($Starting > 0 \land 0 < Ending < Starting$). Represented as a negative financial flow.

```dax
[Contraction MRR] = 
/*
    Summary: Downgrade movements where customer remains active at lower ACV.
    Logic  : starting_mrr > 0 AND ending_mrr > 0 AND ending_mrr < starting_mrr
    Display: Currency ($#,##0); displays negative or enclosed in parentheses.
*/
VAR _ContractionAmount = 
    CALCULATE(
        SUM(fact_mrr_monthly[contraction_mrr]),
        KEEPFILTERS(fact_mrr_monthly[mrr_movement_type] = "Contraction MRR")
    )
RETURN
    COALESCE(_ContractionAmount, 0)
```

---

### `[Voluntary Churn MRR]`
Captures revenue lost when a customer intentionally terminates their subscription via account cancellation settings. Represented as a negative financial flow.

```dax
[Voluntary Churn MRR] = 
/*
    Summary: Intentional customer cancellation (product fit, budget cut, competitor).
    Logic  : starting_mrr > 0 AND ending_mrr = 0 AND cancel_reason = 'voluntary'
    Display: Currency ($#,##0)
*/
VAR _VoluntaryAmount = 
    CALCULATE(
        SUM(fact_mrr_monthly[voluntary_churn_mrr]),
        KEEPFILTERS(fact_mrr_monthly[mrr_movement_type] = "Voluntary Churn MRR")
    )
RETURN
    COALESCE(_VoluntaryAmount, 0)
```

---

### `[Involuntary Leakage MRR]`
Quantifies **pure revenue leakage**: recurring dollars lost when customers wanted to remain subscribed, but payment processing repeatedly failed through dunning exhaustion. Represented as an absolute loss or signed negative flow.

```dax
[Involuntary Leakage MRR] = 
/*
    Summary: Revenue leakage from payment processing failures & exhausted dunning.
    Logic  : starting_mrr > 0 AND ending_mrr = 0 AND cancel_reason = 'involuntary_dunning_exhausted'
    Display: Currency ($#,##0)
*/
VAR _InvoluntaryAmount = 
    CALCULATE(
        SUM(fact_mrr_monthly[involuntary_churn_mrr]),
        KEEPFILTERS(fact_mrr_monthly[mrr_movement_type] = "Involuntary Churn MRR")
    )
RETURN
    COALESCE(_InvoluntaryAmount, 0)
```

---

### `[Net New MRR]`
The algebraic net sum of all expansion, acquisition, contraction, and churn components.

```dax
[Net New MRR] = 
/*
    Summary: Algebraic net monthly expansion/contraction across ledger.
    Formula: [New MRR] + [Expansion MRR] + [Contraction MRR] + [Voluntary Churn MRR] + [Involuntary Leakage MRR]
    Display: Currency ($#,##0)
*/
[New MRR] + [Expansion MRR] + [Contraction MRR] + [Voluntary Churn MRR] + [Involuntary Leakage MRR]
```

---

### `[Ending MRR]`
Total recurring revenue active at the close of the calendar period.

```dax
[Ending MRR] = 
/*
    Summary: Contracted Monthly Recurring Revenue at period close.
    Formula: [Starting MRR] + [Net New MRR]
    Display: Currency ($#,##0)
*/
VAR _EndingFromLedger = 
    SUM(fact_mrr_monthly[ending_mrr])
RETURN
    COALESCE(_EndingFromLedger, [Starting MRR] + [Net New MRR])
```

---

### `[Reconciliation Check (Discrepancy $)]`
Auditing measure enforcing zero discrepancy across the financial ledger.

```dax
[Reconciliation Check (Discrepancy $)] = 
/*
    Summary: Internal audit check. Must equal 0.00 in all slicer combinations.
    Tolerance: Flags any divergence exceeding 1 cent ($0.01).
*/
VAR _ReconciledEnding = [Starting MRR] + [Net New MRR]
VAR _ReportedEnding   = [Ending MRR]
VAR _Diff             = ABS(_ReportedEnding - _ReconciledEnding)
RETURN
    IF(_Diff > 0.01, _ReportedEnding - _ReconciledEnding, 0.00)
```

---

## 3. Retention & Revenue Quality Ratios

### `[Net Revenue Retention % (NRR)]`
Measures the percentage of recurring revenue retained from existing customers over a period, factoring in expansion, contraction, and churn. Can exceed 100%.

```dax
[Net Revenue Retention % (NRR)] = 
/*
    Summary: Cohort / customer revenue preservation including upgrades.
    Formula: (Starting MRR + Expansion + Contraction + All Churn) / Starting MRR
    Display: Percentage (0.0%)
*/
VAR _StartingMRR = [Starting MRR]
VAR _RetainedAndExpanded = 
    _StartingMRR 
    + [Expansion MRR] 
    + [Contraction MRR] 
    + [Voluntary Churn MRR] 
    + [Involuntary Leakage MRR]
RETURN
    DIVIDE(_RetainedAndExpanded, _StartingMRR, BLANK())
```

---

### `[Gross Revenue Retention % (GRR)]`
Strictly measures preservation of existing revenue, completely eliminating any expansion/upsell credit. Capped at 100% per customer.

```dax
[Gross Revenue Retention % (GRR)] = 
/*
    Summary: Revenue preservation efficiency without expansion masking churn.
    Formula: (Starting MRR + Contraction + All Churn) / Starting MRR
    Display: Percentage (0.0%)
*/
VAR _StartingMRR = [Starting MRR]
VAR _PreservedRevenue = 
    _StartingMRR 
    + [Contraction MRR] 
    + [Voluntary Churn MRR] 
    + [Involuntary Leakage MRR]
RETURN
    DIVIDE(_PreservedRevenue, _StartingMRR, BLANK())
```

---

### `[Involuntary Churn Ratio %]`
The single most critical operational efficiency KPI: isolates the proportion of total churn that was **preventable revenue leakage** vs. intentional customer abandonment.

```dax
[Involuntary Churn Ratio %] = 
/*
    Summary: Involuntary Churn as a percentage of Total Gross Churn dollars.
    Benchmark: Healthy SaaS is < 20%; flawed payment ops exhibit > 60%.
    Display: Percentage (0.0%)
*/
VAR _InvoluntaryLoss = ABS([Involuntary Leakage MRR])
VAR _VoluntaryLoss   = ABS([Voluntary Churn MRR])
VAR _TotalGrossChurn = _InvoluntaryLoss + _VoluntaryLoss
RETURN
    DIVIDE(
        _InvoluntaryLoss,
        _TotalGrossChurn,
        0.00
    )
```

---

### `[Involuntary Churn Rate % (MRR Base)]`
Measures the monthly speed of revenue leakage against the starting customer asset base.

```dax
[Involuntary Churn Rate % (MRR Base)] = 
/*
    Summary: Monthly revenue lost to failed billing as % of opening MRR.
    Display: Percentage (0.00%)
*/
VAR _InvoluntaryLoss = ABS([Involuntary Leakage MRR])
VAR _StartingMRR     = [Starting MRR]
RETURN
    DIVIDE(
        _InvoluntaryLoss,
        _StartingMRR,
        0.00
    )
```

---

## 4. Dynamic What-If Financial Simulation Modeling

### A. What-If Slicer Parameter Table
Create a disconnected calculated table in Power BI via DAX:

```dax
dunning_efficiency_parameter = 
GENERATESERIES(0.00, 0.50, 0.05)
```

Column formatting: `dunning_efficiency_parameter[Value]` formatted as `0%`.

---

### B. `[Dunning Optimization Efficiency %]`
Harvests the user's interactive what-if slicer selection.

```dax
[Dunning Optimization Efficiency %] = 
/*
    Summary: Harvested slicer value for recovery engine efficiency improvement.
    Default: 25.0% if no slicer selection is made.
    Display: Percentage (0.0%)
*/
SELECTEDVALUE(
    dunning_efficiency_parameter[Value],
    0.25
)
```

---

### C. `[Projected Monthly Leakage Recaptured]`
Calculates the recurring monthly revenue saved by applying the smart dunning recovery algorithm.

```dax
[Projected Monthly Leakage Recaptured] = 
/*
    Summary: Dollar amount of monthly involuntary churn rescued.
    Formula: Involuntary Leakage MRR * Efficiency %
    Display: Currency ($#,##0)
*/
VAR _InvoluntaryLoss = ABS([Involuntary Leakage MRR])
VAR _Efficiency      = [Dunning Optimization Efficiency %]
RETURN
    _InvoluntaryLoss * _Efficiency
```

---

### D. `[Projected ARR Recaptured]`
Annualizes the recaptured recurring revenue across the enterprise customer base.

```dax
[Projected ARR Recaptured] = 
/*
    Summary: Annualized Recurring Revenue (ARR) preserved by intelligent dunning.
    Formula: [Projected Monthly Leakage Recaptured] * 12
    Display: Currency ($#,##0)
*/
[Projected Monthly Leakage Recaptured] * 12
```

---

### E. `[Projected Post-Optimization Churn Rate %]`
Simulates the resulting monthly involuntary churn rate once the optimization is deployed.

```dax
[Projected Post-Optimization Churn Rate %] = 
/*
    Summary: Residual involuntary churn rate under Policy B.
    Display: Percentage (0.00%)
*/
VAR _CurrentRate = [Involuntary Churn Rate % (MRR Base)]
VAR _Efficiency  = [Dunning Optimization Efficiency %]
RETURN
    _CurrentRate * (1.0 - _Efficiency)
```

---

### F. `[What-If Implementation ROI Multiple]`
Calculates the capital return multiple of deploying an algorithmic retry engine (\$85,000 annualized platform and engineering cost).

```dax
[What-If Implementation ROI Multiple] = 
/*
    Summary: Year-1 ROI multiple on $85k platform expenditure.
    Display: Decimal (0.0x)
*/
VAR _RecapturedARR   = [Projected ARR Recaptured]
VAR _AnnualEngBudget = 85000
RETURN
    DIVIDE(
        _RecapturedARR,
        _AnnualEngBudget,
        0.0
    )
```

---

## 5. Model Display Folders & Measure Taxonomy

| Folder | Measure Name | Format String | Description |
| :--- | :--- | :--- | :--- |
| **`1. MRR Waterfall`** | `[Starting MRR]` | `$#,##0` | Contracted opening MRR |
| **`1. MRR Waterfall`** | `[New MRR]` | `$#,##0` | Organic new activations |
| **`1. MRR Waterfall`** | `[Expansion MRR]` | `$#,##0` | Tier upgrades & price changes |
| **`1. MRR Waterfall`** | `[Contraction MRR]` | `$#,##0;($#,##0)` | Plan downgrades |
| **`1. MRR Waterfall`** | `[Voluntary Churn MRR]`| `$#,##0;($#,##0)` | User-initiated drop |
| **`1. MRR Waterfall`** | `[Involuntary Leakage MRR]`| `$#,##0;($#,##0)` | Failed billing drop |
| **`1. MRR Waterfall`** | `[Net New MRR]` | `$#,##0;($#,##0)` | Net periodic expansion |
| **`1. MRR Waterfall`** | `[Ending MRR]` | `$#,##0` | Contracted closing MRR |
| **`2. Retention Ratios`** | `[Net Revenue Retention % (NRR)]` | `0.0%` | Revenue retention + expansion |
| **`2. Retention Ratios`** | `[Gross Revenue Retention % (GRR)]` | `0.0%` | Pure revenue preservation |
| **`2. Retention Ratios`** | `[Involuntary Churn Ratio %]` | `0.0%` | Involuntary as % of gross churn |
| **`2. Retention Ratios`** | `[Involuntary Churn Rate %]` | `0.00%` | Involuntary as % of starting MRR |
| **`3. What-If Simulation`** | `[Dunning Optimization Efficiency %]` | `0.0%` | Interactive slider input |
| **`3. What-If Simulation`** | `[Projected Monthly Leakage Recaptured]` | `$#,##0` | MRR saved per month |
| **`3. What-If Simulation`** | `[Projected ARR Recaptured]` | `$#,##0` | ARR preserved per year |
| **`3. What-If Simulation`** | `[What-If Implementation ROI Multiple]` | `0.0"x"` | Capital return multiple |
| **`9. Data Governance`** | `[Reconciliation Check (Discrepancy $)]` | `$#,##0.00` | Automated zero-check audit |
