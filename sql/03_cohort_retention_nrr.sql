-- =============================================================================
-- sql/03_cohort_retention_nrr.sql
-- Monthly Acquisition Cohort Net Revenue Retention (NRR) & GRR Matrix
-- =============================================================================
-- Creates materialized view:  mvw_cohort_retention_matrix
-- Methodology:
--   Cohort    = calendar month of first subscription start
--   T0 MRR    = cohort's aggregate MRR in their first active month
--   T+N MRR   = cohort's aggregate MRR N months after entry
--   NRR %     = (T+N MRR / T0 MRR) × 100  [may exceed 100% via expansion]
--   GRR %     = (MIN(T+N per customer, T0 per customer) summed / T0) × 100
--               [capped at 100% — no expansion credit]
--   Logo Ret. = % of cohort customers with any MRR at T+N
-- Tenure window: T0 → T12 (12 months of cohort tracking)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. Supporting indexes (idempotent)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_sub_cust_start_price
    ON fact_subscriptions (customer_id, start_date)
    INCLUDE (monthly_price, monthly_price_at_end, end_date, version);

-- ---------------------------------------------------------------------------
-- 1. Materialized view: mvw_cohort_retention_matrix
-- ---------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS mvw_cohort_retention_matrix CASCADE;

CREATE MATERIALIZED VIEW mvw_cohort_retention_matrix AS

WITH

-- ── 1. Date Spine (shared with waterfall queries) ────────────────────────────
date_spine AS (
    SELECT gs::DATE AS calendar_month
    FROM generate_series(
        (SELECT DATE_TRUNC('month', MIN(signup_date))::DATE FROM dim_customers),
        (SELECT DATE_TRUNC('month', MAX(charge_date))::DATE  FROM fact_invoices),
        '1 month'::INTERVAL
    ) AS gs
),

-- ── 2. Cohort assignment: first subscription month per customer ───────────────
customer_cohorts AS (
    SELECT
        customer_id,
        DATE_TRUNC('month', MIN(start_date))::DATE AS cohort_month
    FROM fact_subscriptions
    GROUP BY customer_id
),

-- ── 3. Point-in-time MRR per customer per calendar month ────────────────────
-- Mirrors the waterfall logic: DISTINCT ON for mid-month upgrades,
-- point-in-time price respecting Month-18 increase.
-- Only tracks months T0 … T+12 per customer (tenure ≤ 12).
customer_monthly_mrr AS (
    SELECT DISTINCT ON (cc.customer_id, ds.calendar_month)
        cc.customer_id,
        cc.cohort_month,
        ds.calendar_month,
        -- Compute integer tenure (months since cohort entry)
        (   (DATE_PART('year',  ds.calendar_month) - DATE_PART('year',  cc.cohort_month)) * 12
          + (DATE_PART('month', ds.calendar_month) - DATE_PART('month', cc.cohort_month))
        )::INT                                          AS tenure_months,
        COALESCE(
            CASE
                WHEN ds.calendar_month >= DATE '2024-07-01'
                THEN fs.monthly_price_at_end
                ELSE fs.monthly_price
            END,
            0::NUMERIC
        )                                               AS monthly_mrr
    FROM customer_cohorts cc
    -- Only generate tenure months 0..12
    JOIN date_spine ds
      ON ds.calendar_month >= cc.cohort_month
     AND ds.calendar_month <= (cc.cohort_month + INTERVAL '12 months')::DATE
    -- Left-join active subscription at this month-end
    LEFT JOIN fact_subscriptions fs
           ON  fs.customer_id = cc.customer_id
           AND fs.start_date  <= (ds.calendar_month + INTERVAL '1 month - 1 day')::DATE
           AND (fs.end_date IS NULL OR fs.end_date > ds.calendar_month)
    ORDER BY cc.customer_id, ds.calendar_month,
             fs.version    DESC NULLS LAST,
             fs.start_date DESC NULLS LAST
),

-- ── 4. T0 MRR per customer (cohort entry month) ──────────────────────────────
-- Only customers who generated positive MRR at T0 are included
-- (excludes sign-ups who never activated a paid subscription).
t0_mrr_per_customer AS (
    SELECT
        customer_id,
        cohort_month,
        monthly_mrr AS t0_mrr
    FROM customer_monthly_mrr
    WHERE tenure_months = 0
      AND monthly_mrr   > 0
),

-- ── 5. Cohort-level T0 totals ────────────────────────────────────────────────
cohort_t0 AS (
    SELECT
        cohort_month,
        COUNT(DISTINCT customer_id)     AS cohort_size,
        SUM(t0_mrr)                     AS total_t0_mrr
    FROM t0_mrr_per_customer
    GROUP BY cohort_month
    HAVING SUM(t0_mrr) > 0             -- exclude cohorts with no paid entry
),

-- ── 6. Cohort MRR at each tenure month (T0 → T12) ───────────────────────────
-- NRR numerator  : actual MRR from cohort members (may include expansion > T0)
-- GRR numerator  : actual MRR capped at each customer's T0 MRR (no expansion credit)
-- Logo retention : count of cohort members with any positive MRR at T+N
cohort_tenure_agg AS (
    SELECT
        t0.cohort_month,
        cmm.tenure_months,
        COUNT(DISTINCT t0.customer_id)                                AS cohort_customers,
        -- NRR: unbounded actual MRR
        SUM(cmm.monthly_mrr)                                          AS nrr_mrr_at_tn,
        -- GRR: each customer contribution capped at their T0 MRR
        SUM(LEAST(cmm.monthly_mrr, t0.t0_mrr))                       AS grr_mrr_at_tn,
        -- Logo: customers still paying anything
        COUNT(DISTINCT CASE WHEN cmm.monthly_mrr > 0 THEN cmm.customer_id END) AS retained_logos
    FROM t0_mrr_per_customer          t0
    JOIN customer_monthly_mrr         cmm
      ON  cmm.customer_id  = t0.customer_id
     AND  cmm.tenure_months BETWEEN 0 AND 12
    GROUP BY t0.cohort_month, cmm.tenure_months
),

-- ── 7. Compute retention rates ───────────────────────────────────────────────
cohort_rates AS (
    SELECT
        cta.cohort_month,
        ct.cohort_size,
        ct.total_t0_mrr,
        cta.tenure_months,
        cta.nrr_mrr_at_tn,
        cta.grr_mrr_at_tn,
        cta.retained_logos,
        -- NRR %
        ROUND(100.0 * cta.nrr_mrr_at_tn  / NULLIF(ct.total_t0_mrr, 0), 2) AS nrr_pct,
        -- GRR % (capped at 100% conceptually; actual formula naturally caps since
        --        LEAST(monthly_mrr, t0_mrr) ≤ t0_mrr for each customer)
        ROUND(100.0 * cta.grr_mrr_at_tn  / NULLIF(ct.total_t0_mrr, 0), 2) AS grr_pct,
        -- Logo retention %
        ROUND(100.0 * cta.retained_logos  / NULLIF(ct.cohort_size,   0), 2) AS logo_ret_pct
    FROM cohort_tenure_agg cta
    JOIN cohort_t0         ct  USING (cohort_month)
)

-- ── 8. Pivot: one row per cohort, columns T0 → T12 ─────────────────────────
SELECT
    cr.cohort_month,
    ct.cohort_size,
    ROUND(ct.total_t0_mrr, 2)                                        AS t0_mrr,
    ROUND(ct.total_t0_mrr / NULLIF(ct.cohort_size, 0), 2)           AS avg_t0_mrr_per_customer,

    -- ── NRR at each tenure month ──────────────────────────────────────────────
    MAX(CASE WHEN tenure_months =  0 THEN nrr_pct END)               AS t0_nrr_pct,
    MAX(CASE WHEN tenure_months =  1 THEN nrr_pct END)               AS t1_nrr_pct,
    MAX(CASE WHEN tenure_months =  2 THEN nrr_pct END)               AS t2_nrr_pct,
    MAX(CASE WHEN tenure_months =  3 THEN nrr_pct END)               AS t3_nrr_pct,
    MAX(CASE WHEN tenure_months =  4 THEN nrr_pct END)               AS t4_nrr_pct,
    MAX(CASE WHEN tenure_months =  5 THEN nrr_pct END)               AS t5_nrr_pct,
    MAX(CASE WHEN tenure_months =  6 THEN nrr_pct END)               AS t6_nrr_pct,
    MAX(CASE WHEN tenure_months =  7 THEN nrr_pct END)               AS t7_nrr_pct,
    MAX(CASE WHEN tenure_months =  8 THEN nrr_pct END)               AS t8_nrr_pct,
    MAX(CASE WHEN tenure_months =  9 THEN nrr_pct END)               AS t9_nrr_pct,
    MAX(CASE WHEN tenure_months = 10 THEN nrr_pct END)               AS t10_nrr_pct,
    MAX(CASE WHEN tenure_months = 11 THEN nrr_pct END)               AS t11_nrr_pct,
    MAX(CASE WHEN tenure_months = 12 THEN nrr_pct END)               AS t12_nrr_pct,

    -- ── GRR at key checkpoints ───────────────────────────────────────────────
    MAX(CASE WHEN tenure_months =  1 THEN grr_pct END)               AS t1_grr_pct,
    MAX(CASE WHEN tenure_months =  3 THEN grr_pct END)               AS t3_grr_pct,
    MAX(CASE WHEN tenure_months =  6 THEN grr_pct END)               AS t6_grr_pct,
    MAX(CASE WHEN tenure_months = 12 THEN grr_pct END)               AS t12_grr_pct,

    -- ── Logo (customer headcount) retention at key checkpoints ──────────────
    MAX(CASE WHEN tenure_months =  1 THEN logo_ret_pct END)           AS t1_logo_ret_pct,
    MAX(CASE WHEN tenure_months =  3 THEN logo_ret_pct END)           AS t3_logo_ret_pct,
    MAX(CASE WHEN tenure_months =  6 THEN logo_ret_pct END)           AS t6_logo_ret_pct,
    MAX(CASE WHEN tenure_months = 12 THEN logo_ret_pct END)           AS t12_logo_ret_pct,

    -- ── MRR retained / lost dollar amounts at key checkpoints ───────────────
    ROUND(MAX(CASE WHEN tenure_months =  3 THEN nrr_mrr_at_tn END), 2) AS t3_mrr_retained,
    ROUND(MAX(CASE WHEN tenure_months =  6 THEN nrr_mrr_at_tn END), 2) AS t6_mrr_retained,
    ROUND(MAX(CASE WHEN tenure_months = 12 THEN nrr_mrr_at_tn END), 2) AS t12_mrr_retained,
    ROUND(MAX(CASE WHEN tenure_months = 12 THEN grr_mrr_at_tn END), 2) AS t12_grr_mrr

FROM cohort_rates    cr
JOIN cohort_t0       ct  USING (cohort_month)
GROUP BY cr.cohort_month, ct.cohort_size, ct.total_t0_mrr
ORDER BY cr.cohort_month;

-- Unique index for fast cohort lookup / REFRESH CONCURRENTLY compatibility
CREATE UNIQUE INDEX idx_cohort_retention_month
    ON mvw_cohort_retention_matrix (cohort_month);

COMMENT ON MATERIALIZED VIEW mvw_cohort_retention_matrix IS
'Monthly acquisition cohort NRR / GRR retention matrix (T0–T12). '
'NRR includes expansion upsell and can exceed 100%. '
'GRR caps each customer contribution at T0 MRR — purely measures revenue preservation. '
'Refresh: REFRESH MATERIALIZED VIEW CONCURRENTLY mvw_cohort_retention_matrix;';
