#!/bin/bash
set -euo pipefail

PROJ="/mnt/c/Users/polis/OneDrive/Desktop/Personal/.vscode/saas-revenue-leakage-audit"
DEXEC="docker exec -i saas_postgres_ledger psql -U postgres -d saas_revenue -v ON_ERROR_STOP=1"

echo "=== Step 1/2: Building mvw_monthly_mrr_waterfall ==="
${DEXEC} < "${PROJ}/sql/02_mrr_waterfall_reconciliation.sql"
echo "Done."

echo ""
echo "=== Step 2/2: Building mvw_cohort_retention_matrix ==="
${DEXEC} < "${PROJ}/sql/03_cohort_retention_nrr.sql"
echo "Done."

echo ""
echo "=== EXPLAIN ANALYZE: Waterfall backing query ==="
${DEXEC} << 'SQL'
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
WITH
date_spine AS (
    SELECT gs::DATE AS calendar_month
    FROM generate_series(
        (SELECT DATE_TRUNC('month', MIN(signup_date))::DATE FROM dim_customers),
        (SELECT DATE_TRUNC('month', MAX(charge_date))::DATE  FROM fact_invoices),
        '1 month'::INTERVAL
    ) AS gs
),
customer_first_month AS (
    SELECT customer_id,
           DATE_TRUNC('month', MIN(start_date))::DATE AS first_active_month
    FROM   fact_subscriptions
    GROUP  BY customer_id
),
customer_month_grid AS (
    SELECT cfm.customer_id, ds.calendar_month
    FROM   customer_first_month cfm
    CROSS  JOIN date_spine ds
    WHERE  ds.calendar_month >= cfm.first_active_month
),
active_sub_per_month AS (
    SELECT DISTINCT ON (cmg.customer_id, cmg.calendar_month)
        cmg.customer_id, cmg.calendar_month,
        CASE WHEN cmg.calendar_month >= DATE '2024-07-01'
             THEN fs.monthly_price_at_end ELSE fs.monthly_price END AS effective_mrr,
        CASE fs.status
            WHEN 'past_due_churned' THEN 'involuntary_dunning_exhausted'
            WHEN 'cancelled'        THEN 'voluntary'
            ELSE 'unknown' END AS cancel_reason
    FROM   customer_month_grid cmg
    LEFT   JOIN fact_subscriptions fs
           ON  fs.customer_id = cmg.customer_id
           AND fs.start_date  <= (cmg.calendar_month + INTERVAL '1 month - 1 day')::DATE
           AND (fs.end_date IS NULL OR fs.end_date > cmg.calendar_month)
    ORDER  BY cmg.customer_id, cmg.calendar_month,
              fs.version DESC NULLS LAST, fs.start_date DESC NULLS LAST
),
customer_mrr_monthly AS (
    SELECT customer_id, calendar_month,
           COALESCE(effective_mrr, 0::NUMERIC) AS ending_mrr,
           cancel_reason
    FROM   active_sub_per_month
),
mrr_with_lag AS (
    SELECT customer_id, calendar_month, ending_mrr, cancel_reason,
           LAG(ending_mrr, 1, 0::NUMERIC) OVER (
               PARTITION BY customer_id ORDER BY calendar_month
           ) AS starting_mrr
    FROM   customer_mrr_monthly
)
SELECT COUNT(*) AS rows, COUNT(DISTINCT calendar_month) AS months, COUNT(DISTINCT customer_id) AS customers
FROM   mrr_with_lag WHERE starting_mrr > 0 OR ending_mrr > 0;
SQL

echo ""
echo "=== Last 6 Months: MRR Waterfall ==="
${DEXEC} << 'SQL'
\x auto
SELECT
    TO_CHAR(calendar_month, 'Mon YYYY')              AS "Month",
    active_customer_count                             AS "Active Cust",
    TO_CHAR(beginning_mrr,          'FM$9,999,999.00') AS "Beg MRR",
    TO_CHAR(new_mrr,                'FM$9,999,999.00') AS "New",
    TO_CHAR(expansion_mrr,          'FM$9,999,999.00') AS "Expansion",
    TO_CHAR(contraction_mrr,        'FM$9,999,999.00') AS "Contraction",
    TO_CHAR(voluntary_churn_mrr,    'FM$9,999,999.00') AS "Vol Churn",
    TO_CHAR(involuntary_churn_mrr,  'FM$9,999,999.00') AS "Invol Churn",
    TO_CHAR(ending_mrr,             'FM$9,999,999.00') AS "End MRR",
    TO_CHAR(net_new_mrr,            'FM$9,999,999.00') AS "Net New",
    involuntary_churn_rate_pct                        AS "Leakage%",
    grr_pct                                           AS "GRR%",
    nrr_pct                                           AS "NRR%"
FROM mvw_monthly_mrr_waterfall
ORDER BY calendar_month DESC
LIMIT 6;
SQL

echo ""
echo "=== Last 6 Cohorts: NRR Retention Matrix ==="
${DEXEC} << 'SQL'
SELECT
    TO_CHAR(cohort_month, 'Mon YYYY')   AS "Cohort",
    cohort_size                          AS "N",
    TO_CHAR(t0_mrr, 'FM$999,999.00')    AS "T0 MRR",
    t0_nrr_pct  AS "T0%",
    t1_nrr_pct  AS "T1%",
    t2_nrr_pct  AS "T2%",
    t3_nrr_pct  AS "T3%",
    t6_nrr_pct  AS "T6%",
    t6_grr_pct  AS "T6 GRR%",
    t6_logo_ret_pct AS "T6 Logo%"
FROM mvw_cohort_retention_matrix
ORDER BY cohort_month DESC
LIMIT 6;
SQL

echo ""
echo "All done."
