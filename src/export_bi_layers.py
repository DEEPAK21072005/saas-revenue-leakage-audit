"""
src/export_bi_layers.py
=======================
Production BI Data Layer Exporter.

Extracts, validates, and serializes clean, dimensional semantic models from
PostgreSQL into high-performance CSV and Parquet files in `data/processed/`:
  - dim_customers.csv / .parquet
  - dim_plans.csv / .parquet
  - fact_mrr_monthly.csv / .parquet
  - agg_mrr_monthly_waterfall.csv / .parquet
  - fact_dunning_events.csv / .parquet
  - agg_cohort_nrr.csv / .parquet
  - agg_cohort_matrix_pivoted.csv / .parquet

Author  : Principal Business Intelligence Architect
Created : 2026-09-13
"""

import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ── Paths & Environment ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")


def get_db_engine() -> Engine:
    """Construct resilient SQLAlchemy engine with host fallback & WSL discovery."""
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASS", "postgres_audit_2026")
    db = os.getenv("DB_NAME", "saas_revenue")
    port = int(os.getenv("DB_PORT", "5432"))

    hosts_to_try = []
    try:
        wsl_out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=8).strip().split()
        if wsl_out:
            hosts_to_try.append(wsl_out[0])
    except Exception:
        pass

    hosts_to_try.extend(["172.29.43.204", "localhost", "127.0.0.1"])

    seen = set()
    unique_hosts = [h for h in hosts_to_try if not (h in seen or seen.add(h))]

    last_err = None
    for h in unique_hosts:
        uri = f"postgresql://{user}:{password}@{h}:{port}/{db}"
        try:
            eng = create_engine(uri, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return eng
        except Exception as e:
            last_err = e

    raise ConnectionError(f"Failed to connect to PostgreSQL across {unique_hosts}: {last_err}")


def export_table(df: pd.DataFrame, base_name: str, out_dir: Path) -> Dict[str, Any]:
    """Export dataframe to both CSV and Parquet, returning file stats."""
    csv_path = out_dir / f"{base_name}.csv"
    parquet_path = out_dir / f"{base_name}.parquet"

    # Export CSV
    df.to_csv(csv_path, index=False)
    csv_size_kb = csv_path.stat().st_size / 1024.0

    # Export Parquet
    df.to_parquet(parquet_path, index=False, engine="pyarrow", compression="snappy")
    parquet_size_kb = parquet_path.stat().st_size / 1024.0

    return {
        "base_name": base_name,
        "rows": len(df),
        "cols": len(df.columns),
        "csv_path": csv_path,
        "csv_size_kb": csv_size_kb,
        "parquet_path": parquet_path,
        "parquet_size_kb": parquet_size_kb,
    }


def main():
    start_total = time.time()
    print("=" * 80)
    print("  SAAS REVENUE LEAKAGE AUDIT: BI SEMANTIC DATA LAYER EXPORTER")
    print("  Target Directory: data/processed/")
    print("=" * 80)

    print("\n[+] Connecting to PostgreSQL via SQLAlchemy...")
    engine = get_db_engine()

    exports_meta = []

    # ── 1. dim_customers ───────────────────────────────────────────────────────
    print("[1/6] Extracting dim_customers...")
    q_cust = """
    SELECT
        customer_id,
        company_name,
        contact_email,
        country,
        industry,
        company_size,
        acquisition_channel,
        signup_date,
        account_created_at
    FROM dim_customers
    ORDER BY signup_date, customer_id;
    """
    df_cust = pd.read_sql(text(q_cust), engine)
    exports_meta.append(export_table(df_cust, "dim_customers", PROCESSED_DIR))

    # ── 2. dim_plans ───────────────────────────────────────────────────────────
    print("[2/6] Extracting dim_plans (SCD Type 2)...")
    q_plans = """
    SELECT
        plan_sk,
        plan_id,
        plan_name,
        plan_surrogate_key,
        price,
        currency,
        billing_interval,
        tier_rank,
        version,
        valid_from,
        valid_to,
        is_current
    FROM dim_plans_scd
    ORDER BY tier_rank, version;
    """
    df_plans = pd.read_sql(text(q_plans), engine)
    exports_meta.append(export_table(df_plans, "dim_plans", PROCESSED_DIR))

    # ── 3. fact_mrr_monthly (Customer-Month Ledger) ───────────────────────────
    print("[3/6] Extracting fact_mrr_monthly (Customer-Month Ledger)...")
    q_mrr_monthly = """
    WITH date_spine AS (
        SELECT gs::DATE AS calendar_month
        FROM generate_series(
            (SELECT DATE_TRUNC('month', MIN(signup_date))::DATE FROM dim_customers),
            (SELECT DATE_TRUNC('month', MAX(charge_date))::DATE  FROM fact_invoices),
            '1 month'::INTERVAL
        ) AS gs
    ),
    customer_first_month AS (
        SELECT customer_id, DATE_TRUNC('month', MIN(start_date))::DATE AS first_active_month
        FROM fact_subscriptions GROUP BY customer_id
    ),
    customer_month_grid AS (
        SELECT cfm.customer_id, ds.calendar_month
        FROM customer_first_month cfm
        CROSS JOIN date_spine ds
        WHERE ds.calendar_month >= cfm.first_active_month
    ),
    active_sub_per_month AS (
        SELECT DISTINCT ON (cmg.customer_id, cmg.calendar_month)
            cmg.customer_id,
            cmg.calendar_month,
            fs.subscription_id,
            fs.plan_key,
            fs.card_type,
            fs.status AS sub_status,
            fs.churn_type,
            CASE
                WHEN cmg.calendar_month >= DATE '2024-07-01' THEN fs.monthly_price_at_end
                ELSE fs.monthly_price
            END AS effective_mrr
        FROM customer_month_grid cmg
        LEFT JOIN fact_subscriptions fs
               ON fs.customer_id = cmg.customer_id
              AND fs.start_date <= (cmg.calendar_month + INTERVAL '1 month - 1 day')::DATE
              AND (fs.end_date IS NULL OR fs.end_date > cmg.calendar_month)
        ORDER BY cmg.customer_id, cmg.calendar_month, fs.version DESC NULLS LAST, fs.start_date DESC NULLS LAST
    ),
    customer_latest_churn AS (
        SELECT DISTINCT ON (customer_id)
            customer_id,
            CASE status
                WHEN 'past_due_churned' THEN 'involuntary_dunning_exhausted'
                WHEN 'cancelled'        THEN 'voluntary'
                ELSE                         'unknown'
            END AS cancel_reason
        FROM fact_subscriptions
        WHERE churn_type IS NOT NULL AND end_date IS NOT NULL
        ORDER BY customer_id, end_date DESC
    ),
    customer_mrr_monthly AS (
        SELECT
            asp.customer_id,
            asp.calendar_month,
            asp.subscription_id,
            asp.plan_key,
            asp.card_type,
            COALESCE(asp.effective_mrr, 0::NUMERIC) AS ending_mrr,
            clc.cancel_reason
        FROM active_sub_per_month asp
        LEFT JOIN customer_latest_churn clc USING (customer_id)
    ),
    mrr_with_lag AS (
        SELECT
            customer_id,
            calendar_month,
            subscription_id,
            plan_key,
            card_type,
            ending_mrr,
            cancel_reason,
            LAG(ending_mrr, 1, 0::NUMERIC) OVER (
                PARTITION BY customer_id ORDER BY calendar_month
            ) AS starting_mrr
        FROM customer_mrr_monthly
    )
    SELECT
        customer_id,
        calendar_month,
        subscription_id,
        plan_key,
        card_type,
        starting_mrr::FLOAT AS starting_mrr,
        ending_mrr::FLOAT   AS ending_mrr,
        (ending_mrr - starting_mrr)::FLOAT AS mrr_delta,
        CASE
            WHEN starting_mrr = 0 AND ending_mrr > 0 THEN 'New MRR'
            WHEN starting_mrr > 0 AND ending_mrr > starting_mrr THEN 'Expansion MRR'
            WHEN starting_mrr > 0 AND ending_mrr > 0 AND ending_mrr < starting_mrr THEN 'Contraction MRR'
            WHEN starting_mrr > 0 AND ending_mrr = 0 AND cancel_reason = 'voluntary' THEN 'Voluntary Churn MRR'
            WHEN starting_mrr > 0 AND ending_mrr = 0 AND cancel_reason = 'involuntary_dunning_exhausted' THEN 'Involuntary Churn MRR'
            WHEN starting_mrr > 0 AND ending_mrr = 0 THEN 'Unclassified Churn MRR'
            WHEN starting_mrr > 0 AND ending_mrr = starting_mrr THEN 'Retained MRR'
            ELSE 'Inactive'
        END AS mrr_movement_type,
        CASE WHEN starting_mrr = 0 AND ending_mrr > 0 THEN ending_mrr ELSE 0 END::FLOAT AS new_mrr,
        CASE WHEN starting_mrr > 0 AND ending_mrr > starting_mrr THEN ending_mrr - starting_mrr ELSE 0 END::FLOAT AS expansion_mrr,
        CASE WHEN starting_mrr > 0 AND ending_mrr > 0 AND ending_mrr < starting_mrr THEN ending_mrr - starting_mrr ELSE 0 END::FLOAT AS contraction_mrr,
        CASE WHEN starting_mrr > 0 AND ending_mrr = 0 AND cancel_reason = 'voluntary' THEN -starting_mrr ELSE 0 END::FLOAT AS voluntary_churn_mrr,
        CASE WHEN starting_mrr > 0 AND ending_mrr = 0 AND cancel_reason = 'involuntary_dunning_exhausted' THEN -starting_mrr ELSE 0 END::FLOAT AS involuntary_churn_mrr,
        CASE WHEN starting_mrr > 0 AND ending_mrr = 0 AND (cancel_reason IS NULL OR cancel_reason NOT IN ('voluntary','involuntary_dunning_exhausted')) THEN -starting_mrr ELSE 0 END::FLOAT AS unclassified_churn_mrr
    FROM mrr_with_lag
    WHERE starting_mrr > 0 OR ending_mrr > 0
    ORDER BY calendar_month, customer_id;
    """
    df_mrr = pd.read_sql(text(q_mrr_monthly), engine)
    exports_meta.append(export_table(df_mrr, "fact_mrr_monthly", PROCESSED_DIR))

    # Also export the pre-aggregated monthly waterfall table for rapid executive visual bridge
    q_mrr_waterfall = "SELECT * FROM mvw_monthly_mrr_waterfall ORDER BY calendar_month;"
    df_waterfall = pd.read_sql(text(q_mrr_waterfall), engine)
    exports_meta.append(export_table(df_waterfall, "agg_mrr_monthly_waterfall", PROCESSED_DIR))

    # ── 4. fact_dunning_events ─────────────────────────────────────────────────
    print("[4/6] Extracting fact_dunning_events (Invoices, Retries & Declines)...")
    q_dunning = """
    SELECT
        fi.invoice_id,
        fi.subscription_id,
        fi.customer_id,
        fi.plan_key,
        fi.amount::FLOAT AS amount,
        fi.attempt_number,
        fi.charge_date,
        fi.status,
        fi.card_brand,
        fi.card_type,
        fi.failure_code,
        fi.prior_failure_code,
        fi.retry_gap_days,
        CASE WHEN fs.churn_type = 'involuntary' THEN 1 ELSE 0 END AS is_involuntary_churn
    FROM fact_invoices fi
    JOIN fact_subscriptions fs ON fs.subscription_id = fi.subscription_id
    WHERE fi.attempt_number > 1 OR fi.status = 'failed'
    ORDER BY fi.subscription_id, fi.charge_date, fi.attempt_number;
    """
    df_dunning = pd.read_sql(text(q_dunning), engine)
    exports_meta.append(export_table(df_dunning, "fact_dunning_events", PROCESSED_DIR))

    # ── 5. agg_cohort_nrr (Unpivoted Cohort Retention Table) ───────────────────
    print("[5/6] Extracting agg_cohort_nrr (Unpivoted Cohort Retention Heatmap Data)...")
    q_cohort_unpivoted = """
    WITH date_spine AS (
        SELECT gs::DATE AS calendar_month
        FROM generate_series(
            (SELECT DATE_TRUNC('month', MIN(signup_date))::DATE FROM dim_customers),
            (SELECT DATE_TRUNC('month', MAX(charge_date))::DATE  FROM fact_invoices),
            '1 month'::INTERVAL
        ) AS gs
    ),
    customer_cohorts AS (
        SELECT customer_id, DATE_TRUNC('month', MIN(start_date))::DATE AS cohort_month
        FROM fact_subscriptions GROUP BY customer_id
    ),
    customer_monthly_mrr AS (
        SELECT DISTINCT ON (cc.customer_id, ds.calendar_month)
            cc.customer_id, cc.cohort_month, ds.calendar_month,
            ((DATE_PART('year', ds.calendar_month) - DATE_PART('year', cc.cohort_month)) * 12 +
             (DATE_PART('month', ds.calendar_month) - DATE_PART('month', cc.cohort_month)))::INT AS tenure_months,
            COALESCE(CASE WHEN ds.calendar_month >= DATE '2024-07-01' THEN fs.monthly_price_at_end ELSE fs.monthly_price END, 0::NUMERIC) AS monthly_mrr
        FROM customer_cohorts cc
        JOIN date_spine ds ON ds.calendar_month >= cc.cohort_month AND ds.calendar_month <= (cc.cohort_month + INTERVAL '12 months')::DATE
        LEFT JOIN fact_subscriptions fs ON fs.customer_id = cc.customer_id AND fs.start_date <= (ds.calendar_month + INTERVAL '1 month - 1 day')::DATE AND (fs.end_date IS NULL OR fs.end_date > ds.calendar_month)
        ORDER BY cc.customer_id, ds.calendar_month, fs.version DESC NULLS LAST, fs.start_date DESC NULLS LAST
    ),
    t0_mrr_per_customer AS (
        SELECT customer_id, cohort_month, monthly_mrr AS t0_mrr
        FROM customer_monthly_mrr WHERE tenure_months = 0 AND monthly_mrr > 0
    ),
    cohort_t0 AS (
        SELECT cohort_month, COUNT(DISTINCT customer_id) AS cohort_size, SUM(t0_mrr) AS total_t0_mrr
        FROM t0_mrr_per_customer GROUP BY cohort_month HAVING SUM(t0_mrr) > 0
    ),
    cohort_tenure_agg AS (
        SELECT
            t0.cohort_month, cmm.tenure_months,
            COUNT(DISTINCT t0.customer_id) AS cohort_customers,
            SUM(cmm.monthly_mrr) AS nrr_mrr_at_tn,
            SUM(LEAST(cmm.monthly_mrr, t0.t0_mrr)) AS grr_mrr_at_tn,
            COUNT(DISTINCT CASE WHEN cmm.monthly_mrr > 0 THEN cmm.customer_id END) AS retained_logos
        FROM t0_mrr_per_customer t0
        JOIN customer_monthly_mrr cmm ON cmm.customer_id = t0.customer_id AND cmm.tenure_months BETWEEN 0 AND 12
        GROUP BY t0.cohort_month, cmm.tenure_months
    )
    SELECT
        cta.cohort_month,
        ct.cohort_size,
        ROUND(ct.total_t0_mrr, 2)::FLOAT AS total_t0_mrr,
        cta.tenure_months,
        cta.retained_logos,
        ROUND(cta.nrr_mrr_at_tn, 2)::FLOAT AS nrr_mrr_at_tn,
        ROUND(cta.grr_mrr_at_tn, 2)::FLOAT AS grr_mrr_at_tn,
        ROUND(100.0 * cta.nrr_mrr_at_tn / NULLIF(ct.total_t0_mrr, 0), 2)::FLOAT AS nrr_pct,
        ROUND(100.0 * cta.grr_mrr_at_tn / NULLIF(ct.total_t0_mrr, 0), 2)::FLOAT AS grr_pct,
        ROUND(100.0 * cta.retained_logos / NULLIF(ct.cohort_size, 0), 2)::FLOAT AS logo_ret_pct
    FROM cohort_tenure_agg cta
    JOIN cohort_t0 ct USING (cohort_month)
    ORDER BY cta.cohort_month, cta.tenure_months;
    """
    df_cohort = pd.read_sql(text(q_cohort_unpivoted), engine)
    exports_meta.append(export_table(df_cohort, "agg_cohort_nrr", PROCESSED_DIR))

    # ── 6. agg_cohort_matrix_pivoted (T0-T12 Pivoted Table) ───────────────────
    print("[6/6] Extracting agg_cohort_matrix_pivoted (Pivoted View)...")
    q_cohort_pivoted = "SELECT * FROM mvw_cohort_retention_matrix ORDER BY cohort_month;"
    df_cohort_piv = pd.read_sql(text(q_cohort_pivoted), engine)
    exports_meta.append(export_table(df_cohort_piv, "agg_cohort_matrix_pivoted", PROCESSED_DIR))

    # ── Summary Report ────────────────────────────────────────────────────────
    total_elapsed = time.time() - start_total
    print("\n" + "=" * 80)
    print(f"  BI DATA EXPORT COMPLETE ({total_elapsed:.2f}s elapsed)")
    print("=" * 80)
    print(f"  {'Table Name':<28} | {'Rows':<9} | {'Cols':<6} | {'CSV Size':<12} | {'Parquet Size':<12}")
    print("  " + "-" * 76)
    for m in exports_meta:
        csv_str = f"{m['csv_size_kb']:.1f} KB" if m['csv_size_kb'] < 1024 else f"{m['csv_size_kb']/1024.0:.2f} MB"
        pq_str = f"{m['parquet_size_kb']:.1f} KB" if m['parquet_size_kb'] < 1024 else f"{m['parquet_size_kb']/1024.0:.2f} MB"
        print(f"  {m['base_name']:<28} | {m['rows']:<9,d} | {m['cols']:<6} | {csv_str:<12} | {pq_str:<12}")
    print("  " + "-" * 76)
    print(f"  [OK] All files successfully saved to: {PROCESSED_DIR.relative_to(PROJECT_ROOT)}/")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
