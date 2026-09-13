"""
tests/test_data_integrity.py
=============================
Automated data integrity test suite for the SaaS Revenue Leakage database.

Test coverage
-------------
  Test 1  · Referential integrity   – zero orphan records in fact tables
  Test 2  · SCD Type 2 integrity    – no overlapping valid_from/valid_to intervals
  Test 3  · Status consistency      – churned subscriptions backed by invoice evidence
  Test 4  · Constraint spot-checks  – amount >= 0, attempt_number BETWEEN 1 AND 4
  Test 5  · Churn taxonomy ratios   – involuntary churn ~60-70%, voluntary ~30-40%
  Test 6  · Operational flaw signal – debit+insufficient_funds fast-retry fail rate
  Test 7  · SCD version uniqueness  – no duplicate surrogate keys

Run with:
  pytest tests/test_data_integrity.py -v

Author  : Lead Data Engineer / QA
Created : 2026-09-13
"""

import os
import sys
from pathlib import Path

import pytest
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ── load .env from project root ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST",  "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME",  "saas_revenue"),
    "user":     os.getenv("DB_USER",  "postgres"),
    "password": os.getenv("DB_PASS",  ""),
}


# ══════════════════════════════════════════════════════════════════════════════
# SESSION-SCOPED FIXTURE: one connection for the whole test session
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def db_conn():
    """Provide a read-only session-scoped database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def cur(db_conn):
    """Return a RealDictCursor for convenience."""
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        yield cursor


# ══════════════════════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════════════════════

def query_scalar(cur, sql: str, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return list(row.values())[0] if row else None


def query_rows(cur, sql: str, params=None) -> list[dict]:
    cur.execute(sql, params)
    return cur.fetchall()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 · Referential Integrity (Zero Orphan Records)
# ══════════════════════════════════════════════════════════════════════════════

class TestReferentialIntegrity:
    """Fact table rows must always resolve to existing dimension rows."""

    def test_no_orphan_subscriptions_by_customer(self, cur):
        """Every fact_subscriptions.customer_id must exist in dim_customers."""
        orphan_count = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_subscriptions fs
            WHERE  NOT EXISTS (
                SELECT 1 FROM dim_customers dc
                WHERE  dc.customer_id = fs.customer_id
            );
        """)
        assert orphan_count == 0, (
            f"{orphan_count:,} subscriptions reference non-existent customers."
        )

    def test_no_orphan_subscriptions_by_plan(self, cur):
        """Every fact_subscriptions.plan_surrogate_key must exist in dim_plans_scd."""
        orphan_count = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_subscriptions fs
            WHERE  NOT EXISTS (
                SELECT 1 FROM dim_plans_scd dp
                WHERE  dp.plan_surrogate_key = fs.plan_surrogate_key
            );
        """)
        assert orphan_count == 0, (
            f"{orphan_count:,} subscriptions reference non-existent plan surrogate keys."
        )

    def test_no_orphan_invoices_by_subscription(self, cur):
        """Every fact_invoices.subscription_id must exist in fact_subscriptions."""
        orphan_count = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_invoices fi
            WHERE  NOT EXISTS (
                SELECT 1 FROM fact_subscriptions fs
                WHERE  fs.subscription_id = fi.subscription_id
            );
        """)
        assert orphan_count == 0, (
            f"{orphan_count:,} invoices reference non-existent subscriptions."
        )

    def test_no_orphan_invoices_by_customer(self, cur):
        """Every fact_invoices.customer_id must exist in dim_customers."""
        orphan_count = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_invoices fi
            WHERE  NOT EXISTS (
                SELECT 1 FROM dim_customers dc
                WHERE  dc.customer_id = fi.customer_id
            );
        """)
        assert orphan_count == 0, (
            f"{orphan_count:,} invoices reference non-existent customers."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 · SCD Type 2 Integrity (No Overlapping Intervals)
# ══════════════════════════════════════════════════════════════════════════════

class TestSCDType2Integrity:
    """For each plan_id, version intervals must be contiguous and non-overlapping."""

    def test_no_overlapping_plan_intervals(self, cur):
        """
        Detect any two rows for the same plan_id where intervals overlap:
          row A: [valid_from_A, valid_to_A)
          row B: [valid_from_B, valid_to_B)
        Overlap condition: valid_from_A < COALESCE(valid_to_B, 'infinity')
                      AND valid_from_B < COALESCE(valid_to_A, 'infinity')
        """
        overlap_count = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   dim_plans_scd p1
            JOIN   dim_plans_scd p2
                ON p1.plan_id   = p2.plan_id
               AND p1.plan_sk  <> p2.plan_sk
               AND p1.valid_from < COALESCE(p2.valid_to, 'infinity'::TIMESTAMPTZ)
               AND p2.valid_from < COALESCE(p1.valid_to, 'infinity'::TIMESTAMPTZ);
        """)
        assert overlap_count == 0, (
            f"{overlap_count} overlapping [valid_from, valid_to] pairs found in dim_plans_scd."
        )

    def test_exactly_one_current_row_per_plan(self, cur):
        """Each plan_id must have exactly one row with is_current = TRUE."""
        violations = query_rows(cur, """
            SELECT plan_id, COUNT(*) AS current_row_count
            FROM   dim_plans_scd
            WHERE  is_current = TRUE
            GROUP  BY plan_id
            HAVING COUNT(*) <> 1;
        """)
        assert len(violations) == 0, (
            f"Plans with != 1 current row: {[dict(r) for r in violations]}"
        )

    def test_scd_versions_cover_full_range(self, cur):
        """
        For each plan_id, the union of all version intervals should cover
        from the earliest valid_from to 'infinity' without gaps.
        Verified by checking that the closed version (valid_to IS NOT NULL)
        of each plan has a successor that starts on the same timestamp.
        """
        gaps = query_rows(cur, """
            WITH ordered_versions AS (
                SELECT
                    plan_id,
                    valid_from,
                    valid_to,
                    LEAD(valid_from) OVER (
                        PARTITION BY plan_id ORDER BY valid_from
                    ) AS next_valid_from
                FROM dim_plans_scd
            )
            SELECT plan_id, valid_from, valid_to, next_valid_from
            FROM   ordered_versions
            WHERE  valid_to IS NOT NULL
              AND  next_valid_from IS NOT NULL
              AND  valid_to <> next_valid_from;
        """)
        assert len(gaps) == 0, (
            f"Gaps detected between SCD versions: {[dict(r) for r in gaps]}"
        )

    def test_no_duplicate_surrogate_keys(self, cur):
        """plan_surrogate_key must be globally unique."""
        dupes = query_scalar(cur, """
            SELECT COUNT(*) FROM (
                SELECT plan_surrogate_key
                FROM   dim_plans_scd
                GROUP  BY plan_surrogate_key
                HAVING COUNT(*) > 1
            ) AS dupes;
        """)
        assert dupes == 0, f"{dupes} duplicate plan_surrogate_key values found."


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 · Status Consistency (Churn Evidence)
# ══════════════════════════════════════════════════════════════════════════════

class TestStatusConsistency:
    """
    Churned subscriptions must be backed by invoice evidence.
    - Voluntary churn: at least one 'paid' invoice exists for the subscription
      (customer was active and then cancelled intentionally).
    - Involuntary churn: at least one 'failed' invoice exists at attempt 4
      (dunning exhausted).
    """

    def test_involuntary_churned_have_exhausted_dunning(self, cur):
        """
        All subscriptions with status='past_due_churned' must have at least
        one invoice with attempt_number=4 and status='failed'.
        """
        violations = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_subscriptions fs
            WHERE  fs.status = 'past_due_churned'
              AND  NOT EXISTS (
                SELECT 1
                FROM   fact_invoices fi
                WHERE  fi.subscription_id = fs.subscription_id
                  AND  fi.attempt_number  = 4
                  AND  fi.status          = 'failed'
              );
        """)
        assert violations == 0, (
            f"{violations:,} involuntary-churned subscriptions lack a 4th-attempt "
            f"failed invoice (dunning should be exhausted)."
        )

    def test_voluntary_churned_have_prior_payment(self, cur):
        """
        All subscriptions with churn_type='voluntary' (status='cancelled') must
        have at least one 'paid' invoice – confirming the customer was genuinely active.
        """
        violations = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_subscriptions fs
            WHERE  fs.churn_type = 'voluntary'
              AND  NOT EXISTS (
                SELECT 1
                FROM   fact_invoices fi
                WHERE  fi.subscription_id = fs.subscription_id
                  AND  fi.status          = 'paid'
              );
        """)
        assert violations == 0, (
            f"{violations:,} voluntary-churned subscriptions have no paid invoices "
            f"(customers should have been active before cancelling)."
        )

    def test_active_subscriptions_have_no_churn_type(self, cur):
        """Active subscriptions must not carry a churn_type label."""
        violations = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_subscriptions
            WHERE  status     = 'active'
              AND  churn_type IS NOT NULL;
        """)
        assert violations == 0, (
            f"{violations:,} active subscriptions incorrectly have a churn_type set."
        )

    def test_failure_code_null_for_paid_invoices(self, cur):
        """failure_code must be NULL on all paid invoices."""
        violations = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_invoices
            WHERE  status       = 'paid'
              AND  failure_code IS NOT NULL;
        """)
        assert violations == 0, (
            f"{violations:,} paid invoices have a non-NULL failure_code."
        )

    def test_failure_code_set_for_failed_invoices(self, cur):
        """failure_code must NOT be NULL on failed invoices."""
        violations = query_scalar(cur, """
            SELECT COUNT(*)
            FROM   fact_invoices
            WHERE  status       = 'failed'
              AND  failure_code IS NULL;
        """)
        assert violations == 0, (
            f"{violations:,} failed invoices are missing a failure_code."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 · Constraint Spot-Checks
# ══════════════════════════════════════════════════════════════════════════════

class TestConstraintSpotChecks:
    """Verify key numeric and categorical constraints hold across all rows."""

    def test_invoice_amount_non_negative(self, cur):
        violations = query_scalar(cur, "SELECT COUNT(*) FROM fact_invoices WHERE amount < 0;")
        assert violations == 0, f"{violations:,} invoices have amount < 0."

    def test_attempt_number_range(self, cur):
        violations = query_scalar(cur, """
            SELECT COUNT(*) FROM fact_invoices
            WHERE attempt_number NOT BETWEEN 1 AND 4;
        """)
        assert violations == 0, f"{violations:,} invoices have attempt_number outside [1, 4]."

    def test_invoice_status_values(self, cur):
        violations = query_scalar(cur, """
            SELECT COUNT(*) FROM fact_invoices
            WHERE status NOT IN ('paid', 'failed');
        """)
        assert violations == 0, f"{violations:,} invoices have invalid status."

    def test_subscription_status_values(self, cur):
        violations = query_scalar(cur, """
            SELECT COUNT(*) FROM fact_subscriptions
            WHERE status NOT IN (
                'active', 'cancelled', 'past_due_churned', 'upgraded', 'downgraded'
            );
        """)
        assert violations == 0, f"{violations:,} subscriptions have invalid status."

    def test_card_type_values(self, cur):
        violations = query_scalar(cur, """
            SELECT COUNT(*) FROM fact_invoices
            WHERE card_type NOT IN ('credit', 'debit');
        """)
        assert violations == 0, f"{violations:,} invoices have invalid card_type."

    def test_mrr_positive(self, cur):
        violations = query_scalar(cur, "SELECT COUNT(*) FROM fact_subscriptions WHERE mrr <= 0;")
        assert violations == 0, f"{violations:,} subscriptions have MRR <= 0."


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 · Churn Taxonomy Ratios
# ══════════════════════════════════════════════════════════════════════════════

class TestChurnTaxonomyRatios:
    """Churn split should respect the 65% involuntary / 35% voluntary target (±10%)."""

    def test_involuntary_churn_ratio_in_range(self, cur):
        ratios = query_rows(cur, """
            SELECT
                churn_type,
                COUNT(*)                                 AS n,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
            FROM   fact_subscriptions
            WHERE  churn_type IS NOT NULL
            GROUP  BY churn_type;
        """)
        ratio_map = {r["churn_type"]: float(r["pct"]) for r in ratios}

        inv_pct = ratio_map.get("involuntary", 0.0)
        vol_pct = ratio_map.get("voluntary",   0.0)

        # Allow ±10% tolerance around target (65% / 35%)
        assert 55.0 <= inv_pct <= 75.0, (
            f"Involuntary churn is {inv_pct:.1f}% (expected 55–75%)."
        )
        assert 25.0 <= vol_pct <= 45.0, (
            f"Voluntary churn is {vol_pct:.1f}% (expected 25–45%)."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 · Operational Flaw Signal (Debit + Insufficient Funds)
# ══════════════════════════════════════════════════════════════════════════════

class TestOperationalFlawSignal:
    """
    The embedded operational anomaly must be measurably detectable in the data.
    Debit card + prior_failure_code='insufficient_funds' retries should exhibit:
      - Fast retry (1–2d):   fail rate ~84%  (tolerance ±10%)
      - Payroll window (5–7d): fail rate ~48% (tolerance ±10%)
    """

    def test_fast_retry_high_fail_rate(self, cur):
        result = query_rows(cur, """
            SELECT
                COUNT(*)                                                     AS total,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)          AS failed,
                ROUND(
                    SUM(CASE WHEN status = 'failed' THEN 1.0 ELSE 0.0 END)
                    / NULLIF(COUNT(*), 0) * 100, 1
                )                                                            AS fail_pct
            FROM fact_invoices
            WHERE card_type            = 'debit'
              AND prior_failure_code   = 'insufficient_funds'
              AND attempt_number       > 1
              AND retry_gap_days BETWEEN 1 AND 2;
        """)
        row = result[0] if result else {}
        total    = int(row.get("total",    0))
        fail_pct = float(row.get("fail_pct", 0) or 0)

        assert total >= 100, f"Insufficient sample size for fast-retry test: n={total}."
        assert 74.0 <= fail_pct <= 94.0, (
            f"Fast-retry fail rate is {fail_pct:.1f}% (expected 74–94%)."
        )

    def test_payroll_window_lower_fail_rate(self, cur):
        result = query_rows(cur, """
            SELECT
                COUNT(*)                                                     AS total,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)          AS failed,
                ROUND(
                    SUM(CASE WHEN status = 'failed' THEN 1.0 ELSE 0.0 END)
                    / NULLIF(COUNT(*), 0) * 100, 1
                )                                                            AS fail_pct
            FROM fact_invoices
            WHERE card_type            = 'debit'
              AND prior_failure_code   = 'insufficient_funds'
              AND attempt_number       > 1
              AND retry_gap_days BETWEEN 5 AND 7;
        """)
        row = result[0] if result else {}
        total    = int(row.get("total",    0))
        fail_pct = float(row.get("fail_pct", 0) or 0)

        assert total >= 100, f"Insufficient sample size for payroll-retry test: n={total}."
        assert 38.0 <= fail_pct <= 58.0, (
            f"Payroll-window fail rate is {fail_pct:.1f}% (expected 38–58%)."
        )

    def test_fast_retry_higher_than_payroll(self, cur):
        """Fast retry must have a meaningfully higher fail rate than payroll-window retry."""
        result = query_rows(cur, """
            SELECT
                ROUND(
                    SUM(CASE WHEN retry_gap_days BETWEEN 1 AND 2 AND status = 'failed'
                             THEN 1.0 ELSE 0.0 END)
                    / NULLIF(SUM(CASE WHEN retry_gap_days BETWEEN 1 AND 2 THEN 1 ELSE 0 END), 0) * 100, 2
                ) AS fast_fail_pct,
                ROUND(
                    SUM(CASE WHEN retry_gap_days BETWEEN 5 AND 7 AND status = 'failed'
                             THEN 1.0 ELSE 0.0 END)
                    / NULLIF(SUM(CASE WHEN retry_gap_days BETWEEN 5 AND 7 THEN 1 ELSE 0 END), 0) * 100, 2
                ) AS payroll_fail_pct
            FROM fact_invoices
            WHERE card_type          = 'debit'
              AND prior_failure_code = 'insufficient_funds'
              AND attempt_number     > 1;
        """)
        row          = result[0] if result else {}
        fast_pct    = float(row.get("fast_fail_pct",    0) or 0)
        payroll_pct = float(row.get("payroll_fail_pct", 0) or 0)

        # Fast-retry must be at least 20 percentage points worse than payroll window
        assert fast_pct - payroll_pct >= 20, (
            f"Expected fast retry ({fast_pct:.1f}%) to exceed payroll-window "
            f"({payroll_pct:.1f}%) by ≥20pp. Gap = {fast_pct - payroll_pct:.1f}pp."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7 · Row-Count Sanity Checks
# ══════════════════════════════════════════════════════════════════════════════

class TestRowCountSanity:
    """Verify the database was fully loaded (not partially)."""

    def test_customer_count(self, cur):
        n = query_scalar(cur, "SELECT COUNT(*) FROM dim_customers;")
        assert n == 25_000, f"Expected 25,000 customers; found {n:,}."

    def test_plan_scd_rows(self, cur):
        n = query_scalar(cur, "SELECT COUNT(*) FROM dim_plans_scd;")
        # 4 plans × 2 versions each = 8 rows
        assert n == 8, f"Expected 8 SCD plan rows (4 plans × 2 versions); found {n}."

    def test_invoice_count_exceeds_400k(self, cur):
        n = query_scalar(cur, "SELECT COUNT(*) FROM fact_invoices;")
        assert n >= 400_000, (
            f"Expected ≥400,000 invoice rows; found {n:,}. "
            f"Re-run data_generator.py to refresh the source CSVs."
        )

    def test_subscription_count_reasonable(self, cur):
        n = query_scalar(cur, "SELECT COUNT(*) FROM fact_subscriptions;")
        # Must be at least as many as customers (some customers have multiple versions)
        assert n >= 25_000, f"Expected ≥25,000 subscription rows; found {n:,}."
