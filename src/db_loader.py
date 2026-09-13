"""
src/db_loader.py
================
High-performance CSV → PostgreSQL ingestion pipeline.

Strategy
--------
Uses PostgreSQL native COPY protocol via psycopg2.copy_expert() with in-memory
io.StringIO buffers.  This bypasses SQLAlchemy row-at-a-time INSERT overhead and
achieves near-wire-speed throughput (typically 100k–500k rows/sec on local Docker).

Load order (respects FK constraints)
--------------------------------------
  1. dim_customers
  2. dim_plans_scd       (from dim_plans_historical.csv, re-mapped to schema columns)
  3. fact_subscriptions
  4. fact_invoices

Author  : Lead Data Engineer
Created : 2026-09-13
"""

import os
import io
import csv
import sys
import logging
import time
from pathlib import Path
from datetime import datetime

# ── dependency check ────────────────────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError as exc:
    sys.exit(f"Missing dependency: {exc}. Run: pip install -r requirements.txt")

# ── logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("db_loader")

# ── paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR      = PROJECT_ROOT / "data" / "raw"
SQL_DIR      = PROJECT_ROOT / "sql"

# ── load .env ─────────────────────────────────────────────────────────────────
load_dotenv(PROJECT_ROOT / ".env")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",  "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",  "saas_revenue"),
    "user":     os.getenv("DB_USER",  "postgres"),
    "password": os.getenv("DB_PASS",  ""),
}


# ══════════════════════════════════════════════════════════════════════════════
# CONNECTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_connection() -> "psycopg2.connection":
    """Return a live psycopg2 connection with autocommit OFF."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

def execute_schema_ddl(conn: "psycopg2.connection") -> None:
    """
    Execute sql/01_schema_ddl.sql inside a transaction.
    Rolls back on any error so the database stays clean.
    """
    ddl_path = SQL_DIR / "01_schema_ddl.sql"
    log.info("Executing schema DDL: %s", ddl_path.relative_to(PROJECT_ROOT))
    ddl_sql = ddl_path.read_text(encoding="utf-8")

    try:
        with conn.cursor() as cur:
            cur.execute(ddl_sql)
        conn.commit()
        log.info("  ✔ Schema created / refreshed successfully.")
    except Exception:
        conn.rollback()
        log.exception("  ✘ Schema DDL failed – rolling back.")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# CORE COPY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _build_copy_buffer(
    rows:            list[dict],
    ordered_columns: list[str],
    null_sentinel:   str = r"\N",
) -> io.StringIO:
    r"""
    Serialise a list of dicts into a tab-delimited StringIO buffer suitable
    for PostgreSQL COPY FROM STDIN WITH (FORMAT TEXT, NULL '\N').

    PostgreSQL TEXT-format COPY rules applied:
      - Fields delimited by TAB (\t)
      - NULL represented as \N
      - Backslash, TAB, and newline in values are escaped
    """
    buf = io.StringIO()
    for row in rows:
        parts = []
        for col in ordered_columns:
            val = row.get(col)
            if val is None or val == "":
                parts.append(null_sentinel)
            else:
                # Escape special characters required by PostgreSQL TEXT format
                s = str(val)
                s = s.replace("\\", "\\\\")
                s = s.replace("\t", "\\t")
                s = s.replace("\n", "\\n")
                s = s.replace("\r", "\\r")
                parts.append(s)
        buf.write("\t".join(parts) + "\n")
    buf.seek(0)
    return buf


def copy_table(
    conn:            "psycopg2.connection",
    table_name:      str,
    ordered_columns: list[str],
    rows:            list[dict],
    truncate_first:  bool = True,
) -> int:
    """
    Load *rows* into *table_name* via PostgreSQL native COPY.

    Parameters
    ----------
    conn             : active psycopg2 connection (autocommit=False)
    table_name       : target table (public schema)
    ordered_columns  : column list matching CSV and table definition
    rows             : list of dicts (from csv.DictReader)
    truncate_first   : if True, TRUNCATE table before loading (idempotent re-runs)

    Returns
    -------
    int : number of rows loaded
    """
    if not rows:
        log.warning("  No rows to load for %s – skipping.", table_name)
        return 0

    buf   = _build_copy_buffer(rows, ordered_columns)
    cols  = ", ".join(f'"{c}"' for c in ordered_columns)
    sql   = (
        f"COPY public.{table_name} ({cols}) "
        f"FROM STDIN WITH (FORMAT TEXT, NULL '\\N', DELIMITER E'\\t')"
    )

    try:
        with conn.cursor() as cur:
            if truncate_first:
                cur.execute(f"TRUNCATE TABLE public.{table_name} CASCADE;")
                log.debug("    TRUNCATE %s – done.", table_name)
            cur.copy_expert(sql, buf)
        conn.commit()
        log.info(
            "  ✔ COPY %-25s  %9s rows",
            table_name,
            f"{len(rows):,}",
        )
    except Exception:
        conn.rollback()
        log.exception("  ✘ COPY into %s failed – rolling back.", table_name)
        raise

    return len(rows)


# ══════════════════════════════════════════════════════════════════════════════
# CSV READERS
# ══════════════════════════════════════════════════════════════════════════════

def read_csv(path: Path) -> list[dict]:
    """Read a CSV into a list of dicts. Empty strings kept as-is for NULL mapping."""
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ══════════════════════════════════════════════════════════════════════════════
# TABLE-SPECIFIC LOADERS (column mapping + transformation)
# ══════════════════════════════════════════════════════════════════════════════

def load_dim_customers(conn: "psycopg2.connection", rows: list[dict]) -> int:
    columns = [
        "customer_id", "company_name", "contact_email",
        "country", "industry", "company_size", "acquisition_channel",
        "signup_date", "account_created_at",
    ]
    return copy_table(conn, "dim_customers", columns, rows)


def load_dim_plans_scd(conn: "psycopg2.connection", rows: list[dict]) -> int:
    """
    Map dim_plans_historical.csv columns to dim_plans_scd schema.

    Source CSV columns  → Target table columns
    -------------------   ----------------------
    plan_surrogate_key  → plan_surrogate_key
    plan_natural_key    → plan_id
    plan_name           → plan_name
    monthly_price       → price
    currency            → currency
    billing_interval    → billing_interval
    tier_rank           → tier_rank
    version             → version
    effective_from      → valid_from  (DATE → TIMESTAMPTZ, midnight UTC)
    effective_to        → valid_to    (DATE → TIMESTAMPTZ or NULL for open-ended)
    is_current          → is_current
    """
    mapped: list[dict] = []
    for r in rows:
        eff_to_raw = r.get("effective_to", "").strip()
        # Treat sentinel "9999-12-31" or blank as NULL (open-ended / current version)
        valid_to = None if (not eff_to_raw or eff_to_raw == "9999-12-31") else (eff_to_raw + " 00:00:00+00")

        # Normalise is_current: CSV stores 'True'/'False' strings
        is_cur_raw = r.get("is_current", "False")
        is_current = "true" if str(is_cur_raw).strip().lower() in ("true", "1", "yes") else "false"

        mapped.append({
            "plan_surrogate_key": r["plan_surrogate_key"],
            "plan_id":            r["plan_natural_key"],
            "plan_name":          r["plan_name"],
            "price":              r["monthly_price"],
            "currency":           r.get("currency", "USD"),
            "billing_interval":   r.get("billing_interval", "monthly"),
            "tier_rank":          r["tier_rank"],
            "version":            r["version"],
            "valid_from":         r["effective_from"] + " 00:00:00+00",
            "valid_to":           valid_to,
            "is_current":         is_current,
        })

    columns = [
        "plan_surrogate_key", "plan_id", "plan_name", "price",
        "currency", "billing_interval", "tier_rank", "version",
        "valid_from", "valid_to", "is_current",
    ]
    return copy_table(conn, "dim_plans_scd", columns, mapped)


def load_fact_subscriptions(conn: "psycopg2.connection", rows: list[dict]) -> int:
    columns = [
        "subscription_id", "customer_id", "plan_key", "plan_surrogate_key",
        "version", "status", "start_date", "end_date",
        "monthly_price", "monthly_price_at_end", "churn_type",
        "card_brand", "card_type", "mrr",
    ]
    return copy_table(conn, "fact_subscriptions", columns, rows)


def load_fact_invoices(conn: "psycopg2.connection", rows: list[dict]) -> int:
    columns = [
        "invoice_id", "subscription_id", "customer_id", "plan_key",
        "amount", "currency", "attempt_number", "charge_date",
        "status", "card_brand", "card_type",
        "failure_code", "prior_failure_code", "retry_gap_days",
    ]
    return copy_table(conn, "fact_invoices", columns, rows)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    t0 = time.perf_counter()
    log.info("=" * 72)
    log.info("SaaS Revenue Leakage – Database Loader (PostgreSQL COPY Protocol)")
    log.info("=" * 72)
    log.info("Target: %s:%s/%s", DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["dbname"])

    # ── Connect ───────────────────────────────────────────────────────────────
    log.info("Establishing psycopg2 connection…")
    conn = get_connection()
    log.info("  ✔ Connected to PostgreSQL.")

    try:
        # ── Step 1: Schema DDL ───────────────────────────────────────────────
        log.info("-" * 72)
        log.info("Step 1/5 · Executing schema DDL (DROP + CREATE + INDEXES)…")
        execute_schema_ddl(conn)

        # ── Step 2: Load dim_customers ────────────────────────────────────────
        log.info("-" * 72)
        log.info("Step 2/5 · Loading dim_customers…")
        t_step = time.perf_counter()
        rows_customers = read_csv(RAW_DIR / "dim_customers.csv")
        n = load_dim_customers(conn, rows_customers)
        log.info("    Elapsed: %.2fs", time.perf_counter() - t_step)

        # ── Step 3: Load dim_plans_scd ────────────────────────────────────────
        log.info("-" * 72)
        log.info("Step 3/5 · Loading dim_plans_scd (from dim_plans_historical.csv)…")
        t_step = time.perf_counter()
        rows_plans = read_csv(RAW_DIR / "dim_plans_historical.csv")
        n = load_dim_plans_scd(conn, rows_plans)
        log.info("    Elapsed: %.2fs", time.perf_counter() - t_step)

        # ── Step 4: Load fact_subscriptions ───────────────────────────────────
        log.info("-" * 72)
        log.info("Step 4/5 · Loading fact_subscriptions…")
        t_step = time.perf_counter()
        rows_subs = read_csv(RAW_DIR / "fact_subscriptions.csv")
        n = load_fact_subscriptions(conn, rows_subs)
        log.info("    Elapsed: %.2fs", time.perf_counter() - t_step)

        # ── Step 5: Load fact_invoices ────────────────────────────────────────
        log.info("-" * 72)
        log.info("Step 5/5 · Loading fact_invoices (largest table)…")
        t_step = time.perf_counter()
        rows_inv = read_csv(RAW_DIR / "fact_invoices.csv")
        n = load_fact_invoices(conn, rows_inv)
        log.info("    Elapsed: %.2fs", time.perf_counter() - t_step)

        # ── Final row count verification ──────────────────────────────────────
        log.info("-" * 72)
        log.info("Final row counts (queried from PostgreSQL):")
        total_db_rows = 0
        with conn.cursor() as cur:
            for tbl in ["dim_customers", "dim_plans_scd",
                        "fact_subscriptions", "fact_invoices"]:
                cur.execute(f"SELECT COUNT(*) FROM public.{tbl};")
                cnt = cur.fetchone()[0]
                total_db_rows += cnt
                log.info("  %-30s  %10s rows", tbl, f"{cnt:,}")
        log.info("  %-30s  %10s rows", "TOTAL (4 tables)", f"{total_db_rows:,}")

    except Exception:
        log.exception("Fatal error during loading pipeline.")
        sys.exit(1)
    finally:
        conn.close()
        log.info("-" * 72)
        log.info("Connection closed.")

    elapsed = time.perf_counter() - t0
    log.info("COMPLETED in %.2f seconds (%.0f rows/sec overall)",
             elapsed, total_db_rows / elapsed)
    log.info("=" * 72)


if __name__ == "__main__":
    main()
