#!/usr/bin/env bash
# =============================================================================
# scripts/run_analytics_sql.sh
# Execute MRR waterfall + cohort retention SQL, then benchmark and preview.
# Usage: bash scripts/run_analytics_sql.sh
# =============================================================================
set -euo pipefail

# ── Connection ────────────────────────────────────────────────────────────────
export PGPASSWORD="${DB_PASS:-postgres_audit_2026}"
PSQL_OPTS=(
  -h "${DB_HOST:-localhost}"
  -p "${DB_PORT:-5432}"
  -U "${DB_USER:-postgres}"
  -d "${DB_NAME:-saas_revenue}"
  -v ON_ERROR_STOP=1
)

echo "========================================================================"
echo "  SaaS Revenue Leakage – Analytics SQL Runner"
echo "  Target: ${DB_HOST:-localhost}:${DB_PORT:-5432}/${DB_NAME:-saas_revenue}"
echo "========================================================================"

# ── Step 1: MRR Waterfall ─────────────────────────────────────────────────────
echo ""
echo "► Step 1/2 · Building mvw_monthly_mrr_waterfall …"
START=$(date +%s%N)
psql "${PSQL_OPTS[@]}" -f sql/02_mrr_waterfall_reconciliation.sql
END=$(date +%s%N)
echo "  ✔ Completed in $(( (END - START) / 1000000 ))ms"

# ── Step 2: Cohort Retention ──────────────────────────────────────────────────
echo ""
echo "► Step 2/2 · Building mvw_cohort_retention_matrix …"
START=$(date +%s%N)
psql "${PSQL_OPTS[@]}" -f sql/03_cohort_retention_nrr.sql
END=$(date +%s%N)
echo "  ✔ Completed in $(( (END - START) / 1000000 ))ms"

# ── Step 3: EXPLAIN ANALYZE on the waterfall backing query ───────────────────
echo ""
echo "========================================================================"
echo "  EXPLAIN ANALYZE: mvw_monthly_mrr_waterfall backing query"
echo "========================================================================"
psql "${PSQL_OPTS[@]}" <<'SQL'
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
        fs.churn_type,
        CASE fs.status
            WHEN 'past_due_churned' THEN 'involuntary_dunning_exhausted'
            WHEN 'cancelled'        THEN 'voluntary'
            ELSE 'unknown' END AS cancel_reason
    FROM   customer_month_grid  cmg
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
SELECT COUNT(*) AS total_customer_month_rows,
       COUNT(DISTINCT calendar_month) AS months,
       COUNT(DISTINCT customer_id)    AS customers
FROM   mrr_with_lag
WHERE  starting_mrr > 0 OR ending_mrr > 0;
SQL

# ── Step 4: Last 6 months of MRR waterfall ────────────────────────────────────
echo ""
echo "========================================================================"
echo "  MRR Waterfall – Last 6 Months"
echo "========================================================================"
psql "${PSQL_OPTS[@]}" <<'SQL'
SELECT
    TO_CHAR(calendar_month, 'Mon YYYY')       AS month,
    active_customer_count,
    TO_CHAR(beginning_mrr,    'FM$999,999,999.00') AS beg_mrr,
    TO_CHAR(new_mrr,           'FM$999,999,999.00') AS new_mrr,
    TO_CHAR(expansion_mrr,     'FM$999,999,999.00') AS expansion,
    TO_CHAR(contraction_mrr,   'FM$999,999,999.00') AS contraction,
    TO_CHAR(voluntary_churn_mrr,   'FM$999,999,999.00') AS vol_churn,
    TO_CHAR(involuntary_churn_mrr, 'FM$999,999,999.00') AS invol_churn,
    TO_CHAR(ending_mrr,        'FM$999,999,999.00') AS end_mrr,
    TO_CHAR(net_new_mrr,       'FM$999,999,999.00') AS net_new,
    involuntary_churn_rate_pct                AS leakage_pct,
    grr_pct,
    nrr_pct
FROM mvw_monthly_mrr_waterfall
ORDER BY calendar_month DESC
LIMIT 6;
SQL

# ── Step 5: Cohort matrix preview (last 6 cohorts, T0-T6 NRR) ────────────────
echo ""
echo "========================================================================"
echo "  Cohort Retention – Last 6 Cohorts (NRR %, T0→T6)"
echo "========================================================================"
psql "${PSQL_OPTS[@]}" <<'SQL'
SELECT
    TO_CHAR(cohort_month, 'Mon YYYY')  AS cohort,
    cohort_size                        AS n,
    TO_CHAR(t0_mrr, 'FM$999,999.00')   AS t0_mrr,
    t0_nrr_pct                         AS "T0%",
    t1_nrr_pct                         AS "T1%",
    t2_nrr_pct                         AS "T2%",
    t3_nrr_pct                         AS "T3%",
    t6_nrr_pct                         AS "T6%",
    t6_grr_pct                         AS "T6 GRR%",
    t6_logo_ret_pct                    AS "T6 Logo%"
FROM mvw_cohort_retention_matrix
ORDER BY cohort_month DESC
LIMIT 6;
SQL

echo ""
echo "========================================================================"
echo "  ✔ Analytics pipeline complete."
echo "========================================================================"
