-- EXPLAIN ANALYZE for query backing mvw_monthly_mrr_waterfall
EXPLAIN (ANALYZE, BUFFERS, TIMING)
WITH

-- ── 1. Date Spine ───────────────────────────────────────────────────────────
date_spine AS (
    SELECT gs::DATE AS calendar_month
    FROM generate_series(
        (SELECT DATE_TRUNC('month', MIN(signup_date))::DATE FROM dim_customers),
        (SELECT DATE_TRUNC('month', MAX(charge_date))::DATE  FROM fact_invoices),
        '1 month'::INTERVAL
    ) AS gs
),

-- ── 2. Customer first active month (ledger entry point) ─────────────────────
customer_first_month AS (
    SELECT
        customer_id,
        DATE_TRUNC('month', MIN(start_date))::DATE AS first_active_month
    FROM fact_subscriptions
    GROUP BY customer_id
),

-- ── 3. Customer × Date Spine presence matrix ─────────────────────────────────
customer_month_grid AS (
    SELECT
        cfm.customer_id,
        ds.calendar_month
    FROM customer_first_month cfm
    CROSS JOIN date_spine ds
    WHERE ds.calendar_month >= cfm.first_active_month
),

-- ── 4. Point-in-time active subscription per customer per month ──────────────
active_sub_per_month AS (
    SELECT DISTINCT ON (cmg.customer_id, cmg.calendar_month)
        cmg.customer_id,
        cmg.calendar_month,
        fs.subscription_id,
        fs.plan_key,
        fs.plan_surrogate_key,
        fs.status        AS sub_status,
        fs.churn_type,
        fs.end_date,
        CASE
            WHEN cmg.calendar_month >= DATE '2024-07-01'
            THEN fs.monthly_price_at_end    -- post-price-increase rate
            ELSE fs.monthly_price           -- original contracted rate
        END              AS effective_mrr
    FROM customer_month_grid       cmg
    LEFT JOIN fact_subscriptions   fs
           ON  fs.customer_id  = cmg.customer_id
           AND fs.start_date  <= (cmg.calendar_month + INTERVAL '1 month - 1 day')::DATE
           AND (fs.end_date IS NULL OR fs.end_date > cmg.calendar_month)
    ORDER BY
        cmg.customer_id,
        cmg.calendar_month,
        fs.version       DESC NULLS LAST,
        fs.start_date    DESC NULLS LAST
),

-- ── 5. Latest churn classification per customer ──────────────────────────────
customer_latest_churn AS (
    SELECT DISTINCT ON (customer_id)
        customer_id,
        churn_type              AS last_churn_type,
        CASE status
            WHEN 'past_due_churned' THEN 'involuntary_dunning_exhausted'
            WHEN 'cancelled'        THEN 'voluntary'
            ELSE                         'unknown'
        END                     AS cancel_reason
    FROM  fact_subscriptions
    WHERE churn_type IS NOT NULL
      AND end_date   IS NOT NULL
    ORDER BY customer_id, end_date DESC
),

-- ── 6. Effective monthly MRR per customer (0 = inactive) ────────────────────
customer_mrr_monthly AS (
    SELECT
        asp.customer_id,
        asp.calendar_month,
        COALESCE(asp.effective_mrr, 0::NUMERIC)   AS ending_mrr,
        clc.cancel_reason
    FROM active_sub_per_month  asp
    LEFT JOIN customer_latest_churn clc USING (customer_id)
),

-- ── 7. LAG window: derive starting_mrr and delta ─────────────────────────────
mrr_with_lag AS (
    SELECT
        customer_id,
        calendar_month,
        ending_mrr,
        cancel_reason,
        LAG(ending_mrr, 1, 0::NUMERIC) OVER (
            PARTITION BY customer_id
            ORDER BY     calendar_month
        )                                                AS starting_mrr
    FROM customer_mrr_monthly
),

-- ── 8. Classify every dollar movement (SaaS accounting taxonomy) ─────────────
mrr_classified AS (
    SELECT
        customer_id,
        calendar_month,
        starting_mrr,
        ending_mrr,
        ending_mrr - starting_mrr                        AS mrr_delta,

        -- Movement type label
        CASE
            WHEN starting_mrr = 0 AND ending_mrr > 0
                 THEN 'New MRR'
            WHEN starting_mrr > 0 AND ending_mrr > starting_mrr
                 THEN 'Expansion MRR'
            WHEN starting_mrr > 0 AND ending_mrr > 0 AND ending_mrr < starting_mrr
                 THEN 'Contraction MRR'
            WHEN starting_mrr > 0 AND ending_mrr = 0
                 AND cancel_reason = 'voluntary'
                 THEN 'Voluntary Churn MRR'
            WHEN starting_mrr > 0 AND ending_mrr = 0
                 AND cancel_reason = 'involuntary_dunning_exhausted'
                 THEN 'Involuntary Churn MRR'
            WHEN starting_mrr > 0 AND ending_mrr = 0
                 THEN 'Churn MRR (Unclassified)'
            WHEN starting_mrr > 0 AND ending_mrr = starting_mrr
                 THEN 'Retained MRR'
            ELSE 'Inactive'
        END                                              AS mrr_movement_type,

        -- Signed component amounts (positive = gained, negative = lost)
        CASE WHEN starting_mrr = 0 AND ending_mrr > 0
             THEN  ending_mrr                            ELSE 0 END AS new_mrr,

        CASE WHEN starting_mrr > 0 AND ending_mrr > starting_mrr
             THEN  ending_mrr - starting_mrr             ELSE 0 END AS expansion_mrr,

        CASE WHEN starting_mrr > 0 AND ending_mrr > 0 AND ending_mrr < starting_mrr
             THEN  ending_mrr - starting_mrr             ELSE 0 END AS contraction_mrr,

        CASE WHEN starting_mrr > 0 AND ending_mrr = 0
                  AND cancel_reason = 'voluntary'
             THEN -starting_mrr                          ELSE 0 END AS voluntary_churn_mrr,

        CASE WHEN starting_mrr > 0 AND ending_mrr = 0
                  AND cancel_reason = 'involuntary_dunning_exhausted'
             THEN -starting_mrr                          ELSE 0 END AS involuntary_churn_mrr,

        CASE WHEN starting_mrr > 0 AND ending_mrr = 0
                  AND (cancel_reason IS NULL
                       OR cancel_reason NOT IN ('voluntary','involuntary_dunning_exhausted'))
             THEN -starting_mrr                          ELSE 0 END AS unclassified_churn_mrr
    FROM mrr_with_lag
    WHERE starting_mrr > 0 OR ending_mrr > 0
)

-- ── Final aggregate: one row per calendar month ──────────────────────────────
SELECT
    calendar_month,
    COUNT(DISTINCT CASE WHEN ending_mrr  > 0 THEN customer_id END)::INT  AS active_customer_count,
    COUNT(DISTINCT CASE WHEN starting_mrr > 0 THEN customer_id END)::INT AS churned_candidates,
    ROUND(SUM(CASE WHEN starting_mrr > 0 THEN starting_mrr ELSE 0 END), 2) AS beginning_mrr,
    ROUND(SUM(new_mrr),                  2)                                AS new_mrr,
    ROUND(SUM(expansion_mrr),            2)                                AS expansion_mrr,
    ROUND(SUM(contraction_mrr),          2)                                AS contraction_mrr,
    ROUND(SUM(voluntary_churn_mrr),      2)                                AS voluntary_churn_mrr,
    ROUND(SUM(involuntary_churn_mrr),    2)                                AS involuntary_churn_mrr,
    ROUND(SUM(unclassified_churn_mrr),   2)                                AS unclassified_churn_mrr,
    ROUND(SUM(ending_mrr),               2)                                AS ending_mrr,
    ROUND(
          SUM(new_mrr)
        + SUM(expansion_mrr)
        + SUM(contraction_mrr)
        + SUM(voluntary_churn_mrr)
        + SUM(involuntary_churn_mrr)
        + SUM(unclassified_churn_mrr),
    2)                                                                     AS net_new_mrr,
    ROUND(
        100.0 * ABS(SUM(involuntary_churn_mrr))
        / NULLIF(SUM(CASE WHEN starting_mrr > 0 THEN starting_mrr ELSE 0 END), 0),
    2)                                                                     AS involuntary_churn_rate_pct,
    ROUND(
        100.0 * (
              SUM(CASE WHEN starting_mrr > 0 THEN starting_mrr ELSE 0 END)
            + SUM(contraction_mrr)
            + SUM(voluntary_churn_mrr)
            + SUM(involuntary_churn_mrr)
            + SUM(unclassified_churn_mrr)
        )
        / NULLIF(SUM(CASE WHEN starting_mrr > 0 THEN starting_mrr ELSE 0 END), 0),
    2)                                                                     AS grr_pct,
    ROUND(
        100.0 * SUM(CASE WHEN starting_mrr > 0 THEN ending_mrr  ELSE 0 END)
              / NULLIF(SUM(CASE WHEN starting_mrr > 0 THEN starting_mrr ELSE 0 END), 0),
    2)                                                                     AS nrr_pct
FROM mrr_classified
GROUP BY calendar_month
ORDER BY calendar_month;
