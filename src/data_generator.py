"""
src/data_generator.py
=====================
Industrial-strength synthetic event generator for:
  "SaaS Revenue Leakage & Subscription Lifecycle Reconciliation"

Produces 4 BI-ready CSVs in data/raw/:
  - dim_customers.csv           : 25,000 unique customer accounts
  - dim_plans_historical.csv    : SCD Type 2 plan/price history (Month-18 price increase)
  - fact_subscriptions.csv      : One row per subscription version per customer
  - fact_invoices.csv           : 400,000+ transactional billing events with retry mechanics

Author  : Staff Data Architect
Created : 2026-09-13
"""

import os
import sys
import csv
import uuid
import math
import random
import logging
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

# ── dependency check ────────────────────────────────────────────────────────
try:
    from faker import Faker
    import numpy as np
except ImportError as exc:
    sys.exit(f"Missing dependency: {exc}. Run: pip install -r requirements.txt")

# ── logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("data_generator")

# ── reproducibility ──────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker("en_US")
Faker.seed(SEED)

# ── simulation constants ──────────────────────────────────────────────────────
SIM_START          = date(2023, 1, 1)
SIM_END            = date(2025, 12, 31)
SIM_MONTHS         = 36
PRICE_INCREASE_MONTH = 18          # Month 18 from SIM_START = July 2024
N_CUSTOMERS        = 25_000

# ── product tier catalog (SCD Type 2) ───────────────────────────────────────
# Each entry: (plan_key, name, price_v1, price_v2_after_month18)
PLAN_CATALOG = [
    ("starter",    "Starter",    49.00,   59.00),
    ("growth",     "Growth",    199.00,  249.00),
    ("enterprise", "Enterprise",799.00,  849.00),
    ("scale",      "Scale",   1_999.00, 2_199.00),
]

PLAN_KEYS        = [p[0] for p in PLAN_CATALOG]
PLAN_WEIGHTS     = [0.38, 0.34, 0.18, 0.10]   # acquisition distribution

# ── churn rates ──────────────────────────────────────────────────────────────
# Monthly churn probability by plan (lower tier = higher churn)
MONTHLY_CHURN_PROB = {
    "starter":    0.048,
    "growth":     0.033,
    "enterprise": 0.018,
    "scale":      0.010,
}
VOLUNTARY_CHURN_SHARE    = 0.35   # 35% intentional cancellations
INVOLUNTARY_CHURN_SHARE  = 0.65   # 65% failed dunning / revenue leakage

# ── dunning retry mechanics ──────────────────────────────────────────────────
MAX_DUNNING_ATTEMPTS = 4
RETRY_GAPS_DAYS      = [3, 5, 7]   # gaps after each failed attempt

# Base invoice failure rates by attempt number
BASE_FAIL_RATE = {1: 0.11, 2: 0.38, 3: 0.58, 4: 0.72}

# Failure codes per Stripe taxonomy (weighted)
FAILURE_CODES = [
    "insufficient_funds",
    "card_expired",
    "do_not_honor",
    "generic_decline",
]
FAILURE_CODE_WEIGHTS = [0.44, 0.21, 0.20, 0.15]

CARD_BRANDS = ["visa", "mastercard", "amex"]
CARD_BRAND_WEIGHTS = [0.55, 0.32, 0.13]

CARD_TYPES = ["credit", "debit"]
CARD_TYPE_WEIGHTS = [0.68, 0.32]

# ── operational flaw (embedded anomaly for analytics to uncover) ──────────────
# Debit + insufficient_funds retried within 24–48h  → 84% fail rate
FLAW_DEBIT_INSUF_FAST_RETRY_FAIL = 0.84
# Debit + insufficient_funds retried Day 5–7 (payroll cycle) → only 48% fail (52% recovery)
FLAW_DEBIT_INSUF_PAYROLL_FAIL    = 0.48

# ── upgrade / downgrade transition matrix ────────────────────────────────────
# For active customers at each monthly tick, probability of plan change
UPGRADE_PROB   = {"starter": 0.025, "growth": 0.015, "enterprise": 0.008, "scale": 0.000}
DOWNGRADE_PROB = {"starter": 0.000, "growth": 0.010, "enterprise": 0.018, "scale": 0.022}

# ── industry / company size tags ─────────────────────────────────────────────
INDUSTRIES = [
    "SaaS", "FinTech", "HealthTech", "EdTech", "E-Commerce",
    "Logistics", "Marketing", "HR Tech", "LegalTech", "AgriTech",
]
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500", "501-2000", "2001+"]
ACQUISITION_CHANNELS = ["organic", "paid_search", "referral", "outbound_sales", "partner"]

# ── country distribution ─────────────────────────────────────────────────────
COUNTRIES = {
    "US": 0.52, "CA": 0.08, "GB": 0.09, "DE": 0.06, "AU": 0.05,
    "FR": 0.04, "IN": 0.05, "SG": 0.03, "NL": 0.03, "SE": 0.02,
    "BR": 0.02, "JP": 0.01,
}

# ── path helpers ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR      = PROJECT_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════════════
# UTILITY HELPERS
# ════════════════════════════════════════════════════════════════════════════════

def weighted_choice(options, weights):
    return random.choices(options, weights=weights, k=1)[0]


def add_months(d: date, months: int) -> date:
    """Advance a date by N calendar months, clamping to month-end."""
    month = d.month - 1 + months
    year  = d.year + month // 12
    month = month % 12 + 1
    day   = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                         else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def month_offset(d: date) -> int:
    """Return how many months after SIM_START the given date falls."""
    return (d.year - SIM_START.year) * 12 + (d.month - SIM_START.month)


def plan_price(plan_key: str, reference_date: date) -> float:
    """Return the correct plan price, accounting for Month-18 price increase."""
    for pk, _, price_v1, price_v2 in PLAN_CATALOG:
        if pk == plan_key:
            return price_v2 if month_offset(reference_date) >= PRICE_INCREASE_MONTH else price_v1
    raise ValueError(f"Unknown plan key: {plan_key}")


def stripe_invoice_id() -> str:
    return "in_" + uuid.uuid4().hex[:20]


def stripe_sub_id() -> str:
    return "sub_" + uuid.uuid4().hex[:14]


def stripe_cust_id() -> str:
    return "cus_" + uuid.uuid4().hex[:14]


# ════════════════════════════════════════════════════════════════════════════════
# CUSTOMER ACQUISITION MODEL
# A growth-weighted distribution across 36 months that mimics a real SaaS curve:
#   • slow ramp in months 1-6
#   • steady compounding through months 7-30
#   • slight plateau in months 31-36
# ════════════════════════════════════════════════════════════════════════════════

def build_acquisition_weights() -> list:
    """
    Return a 36-element weight list that shapes customer start dates to
    mimic a realistic SaaS S-curve acquisition pattern.
    """
    weights = []
    for m in range(1, SIM_MONTHS + 1):
        # Logistic growth scaled to plateau toward end of window
        w = 1 / (1 + math.exp(-0.20 * (m - 14))) + random.gauss(0, 0.03)
        weights.append(max(0.01, w))
    # Normalise
    total = sum(weights)
    return [w / total for w in weights]


ACQ_WEIGHTS = build_acquisition_weights()


def assign_start_month() -> int:
    """Return a month index (0-based) for a customer's subscription start."""
    # Customers who start in month 35 only have ~1 month of data – realistic
    return random.choices(range(SIM_MONTHS), weights=ACQ_WEIGHTS, k=1)[0]


# ════════════════════════════════════════════════════════════════════════════════
# DIM_PLANS_HISTORICAL  (SCD Type 2)
# ════════════════════════════════════════════════════════════════════════════════

def build_dim_plans_historical() -> list[dict]:
    """
    Build SCD Type 2 plan dimension.
    Each plan has 2 rows: v1 (launch through Month 17) and v2 (Month 18 onward).
    Returns a list of dicts ready for CSV serialisation.
    """
    rows = []
    price_increase_date = add_months(SIM_START, PRICE_INCREASE_MONTH)

    for rank, (plan_key, plan_name, price_v1, price_v2) in enumerate(PLAN_CATALOG, start=1):
        plan_sk_v1 = f"plan_{plan_key}_v1"
        plan_sk_v2 = f"plan_{plan_key}_v2"

        # Version 1 – from simulation start through the moment v2 takes effect (exclusive end)
        rows.append({
            "plan_surrogate_key": plan_sk_v1,
            "plan_natural_key":   plan_key,
            "plan_name":          plan_name,
            "monthly_price":      price_v1,
            "currency":           "USD",
            "billing_interval":   "monthly",
            "tier_rank":          rank,
            "version":            1,
            "effective_from":     SIM_START.isoformat(),
            "effective_to":       price_increase_date.isoformat(),   # exclusive; = v2 valid_from
            "is_current":         False,
        })

        # Version 2 – from price increase through end of simulation (open-ended)
        rows.append({
            "plan_surrogate_key": plan_sk_v2,
            "plan_natural_key":   plan_key,
            "plan_name":          plan_name,
            "monthly_price":      price_v2,
            "currency":           "USD",
            "billing_interval":   "monthly",
            "tier_rank":          rank,
            "version":            2,
            "effective_from":     price_increase_date.isoformat(),
            "effective_to":       "9999-12-31",
            "is_current":         True,
        })

    return rows


# ════════════════════════════════════════════════════════════════════════════════
# DIM_CUSTOMERS
# ════════════════════════════════════════════════════════════════════════════════

def build_dim_customers() -> list[dict]:
    """Generate 25,000 synthetic B2B customer account records."""
    log.info("Building dim_customers (%s accounts)…", f"{N_CUSTOMERS:,}")
    country_keys    = list(COUNTRIES.keys())
    country_weights = list(COUNTRIES.values())
    rows = []

    for _ in range(N_CUSTOMERS):
        country   = weighted_choice(country_keys, country_weights)
        acq_month = assign_start_month()
        signup_date = add_months(SIM_START, acq_month) + timedelta(days=random.randint(0, 27))

        rows.append({
            "customer_id":          stripe_cust_id(),
            "company_name":         fake.company(),
            "contact_email":        fake.company_email(),
            "country":              country,
            "industry":             random.choice(INDUSTRIES),
            "company_size":         weighted_choice(COMPANY_SIZES,
                                        [0.18, 0.30, 0.25, 0.14, 0.09, 0.04]),
            "acquisition_channel":  weighted_choice(ACQUISITION_CHANNELS,
                                        [0.28, 0.22, 0.20, 0.18, 0.12]),
            "signup_date":          signup_date.isoformat(),
            "account_created_at":   datetime.combine(signup_date, datetime.min.time())
                                        .isoformat(sep=" "),
        })

    log.info("  → %s customer records generated.", f"{len(rows):,}")
    return rows


# ════════════════════════════════════════════════════════════════════════════════
# INVOICE GENERATION ENGINE
# ════════════════════════════════════════════════════════════════════════════════

def resolve_invoice_fail_rate(attempt: int, card_type: str,
                              failure_code: str, retry_gap_days: int | None) -> float:
    """
    Compute the probability that this invoice attempt *fails*.

    Embeds the operational flaw:
      • debit + insufficient_funds retried within 24-48h  → 84% failure (fast retry)
      • debit + insufficient_funds retried on day 5–7     → 48% failure (payroll recovery)
    """
    base = BASE_FAIL_RATE[attempt]

    if card_type == "debit" and failure_code == "insufficient_funds" and retry_gap_days is not None:
        if 1 <= retry_gap_days <= 2:          # fast retry (24-48h) → very high fail
            return FLAW_DEBIT_INSUF_FAST_RETRY_FAIL
        elif 5 <= retry_gap_days <= 7:        # payroll cycle window → lower fail
            return FLAW_DEBIT_INSUF_PAYROLL_FAIL

    # Standard modifiers by card type and failure code
    modifier = 0.0
    if card_type == "debit":
        modifier += 0.05          # debit generally harder to recover
    if failure_code == "card_expired":
        modifier -= 0.10          # expired card usually resolved by customer
    elif failure_code == "do_not_honor":
        modifier += 0.08          # issuer block – hard to recover
    elif failure_code == "generic_decline":
        modifier += 0.03

    return min(0.97, max(0.02, base + modifier))


def generate_invoices_for_subscription(
    subscription_id: str,
    customer_id:     str,
    plan_key:        str,
    card_brand:      str,
    card_type:       str,
    billing_start:   date,
    billing_end:     date,   # exclusive – subscription's effective end date
    is_involuntary:  bool,   # True = churn driven by failed dunning
    churn_month_idx: int | None,
) -> list[dict]:
    """
    Simulate monthly invoice cycles for one subscription, including full
    dunning retry sequences for failed invoices.

    Returns a list of fact_invoice row dicts.
    """
    invoice_rows = []
    current_date = billing_start

    while current_date < billing_end and current_date <= SIM_END:
        amount           = plan_price(plan_key, current_date)
        failure_code     = weighted_choice(FAILURE_CODES, FAILURE_CODE_WEIGHTS)
        prior_fail_date: date | None = None
        sub_churned_this_cycle = False

        # ── Involuntary churn: detect the final billing cycle ─────────────────
        # If the next cycle would exceed billing_end, we are in the last cycle.
        # Force ALL dunning attempts to fail so attempt_number=4 is always
        # present and status='failed' for every involuntary-churned subscription.
        next_cycle_approx     = current_date + timedelta(days=30)
        force_dunning_exhaust = is_involuntary and (next_cycle_approx >= billing_end)

        for attempt in range(1, MAX_DUNNING_ATTEMPTS + 1):
            # Compute retry gap from previous failed attempt
            retry_gap = None
            if prior_fail_date is not None:
                retry_gap = (current_date - prior_fail_date).days

            fail_rate = resolve_invoice_fail_rate(attempt, card_type, failure_code, retry_gap)

            # Determine outcome
            if attempt < MAX_DUNNING_ATTEMPTS:
                # Attempts 1-3: probabilistic, unless we are forcing exhaustion
                failed = True if force_dunning_exhaust else (random.random() < fail_rate)
            else:
                # Attempt 4 (final)
                if force_dunning_exhaust:
                    failed = True
                    sub_churned_this_cycle = True
                else:
                    failed = random.random() < fail_rate

            # prior_failure_code: the Stripe decline code that triggered THIS retry
            # (None for first attempts; always set for attempts 2-4 regardless of outcome)
            prior_fc = failure_code if attempt > 1 else None

            invoice_rows.append({
                "invoice_id":          stripe_invoice_id(),
                "subscription_id":     subscription_id,
                "customer_id":         customer_id,
                "plan_key":            plan_key,
                "amount":              round(amount, 2),
                "currency":            "USD",
                "attempt_number":      attempt,
                "charge_date":         current_date.isoformat(),
                "status":              "failed" if failed else "paid",
                "card_brand":          card_brand,
                "card_type":           card_type,
                "failure_code":        failure_code if failed else None,
                "prior_failure_code":  prior_fc,
                "retry_gap_days":      retry_gap,
            })

            if not failed:
                # Payment succeeded – break dunning loop, advance to next month
                break
            else:
                prior_fail_date = current_date
                if attempt < MAX_DUNNING_ATTEMPTS:
                    # Schedule next retry attempt
                    gap = RETRY_GAPS_DAYS[attempt - 1] + random.randint(-1, 1)
                    gap = max(1, gap)
                    current_date = current_date + timedelta(days=gap)
                else:
                    # Exhausted all retries – subscription will mark past_due / churned
                    break

        if sub_churned_this_cycle:
            break

        # Advance to next billing cycle (~30 days)
        current_date = billing_start + timedelta(days=30 * (month_offset(current_date)
                        - month_offset(billing_start) + 1))
        if current_date <= billing_start:
            current_date = billing_start + timedelta(days=30)

    # ── Post-loop guarantee for involuntary churn ─────────────────────────────
    # Edge case: a prior successful payment cycle advanced current_date past
    # billing_end before force_dunning_exhaust could trigger, leaving the
    # subscription without a 4th-attempt failed invoice.
    # Synthesize a final exhausted dunning cycle anchored 14 days before billing_end.
    if is_involuntary and not sub_churned_this_cycle:
        final_cycle_date = max(
            billing_end - timedelta(days=14),
            billing_start + timedelta(days=1),
        )
        final_failure_code = weighted_choice(FAILURE_CODES, FAILURE_CODE_WEIGHTS)
        prior_fc_date: date | None = None

        for attempt in range(1, MAX_DUNNING_ATTEMPTS + 1):
            retry_gap = (final_cycle_date - prior_fc_date).days if prior_fc_date else None
            prior_fc  = final_failure_code if attempt > 1 else None

            invoice_rows.append({
                "invoice_id":          stripe_invoice_id(),
                "subscription_id":     subscription_id,
                "customer_id":         customer_id,
                "plan_key":            plan_key,
                "amount":              round(plan_price(plan_key, final_cycle_date), 2),
                "currency":            "USD",
                "attempt_number":      attempt,
                "charge_date":         final_cycle_date.isoformat(),
                "status":              "failed",
                "card_brand":          card_brand,
                "card_type":           card_type,
                "failure_code":        final_failure_code,
                "prior_failure_code":  prior_fc,
                "retry_gap_days":      retry_gap,
            })

            prior_fc_date = final_cycle_date
            if attempt < MAX_DUNNING_ATTEMPTS:
                gap = RETRY_GAPS_DAYS[attempt - 1]
                final_cycle_date = final_cycle_date + timedelta(days=gap)

    return invoice_rows


# ════════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION STATE ENGINE
# ════════════════════════════════════════════════════════════════════════════════

def simulate_customer_lifecycle(customer: dict) -> tuple[list[dict], list[dict]]:
    """
    Drive one customer through the full subscription lifecycle:
      New → Active → [Upgrade | Downgrade] → [Past Due → Churned | Active]

    Returns:
      - subscription_rows  : list of fact_subscriptions dicts
      - invoice_rows       : list of fact_invoices dicts
    """
    cid           = customer["customer_id"]
    signup_date   = date.fromisoformat(customer["signup_date"])

    # Assign initial plan based on company size (larger companies → higher tier)
    size = customer["company_size"]
    if size in ("501-2000", "2001+"):
        plan_weights_local = [0.05, 0.20, 0.40, 0.35]
    elif size in ("201-500",):
        plan_weights_local = [0.10, 0.35, 0.38, 0.17]
    elif size in ("51-200",):
        plan_weights_local = [0.25, 0.45, 0.22, 0.08]
    else:
        plan_weights_local = [0.55, 0.33, 0.09, 0.03]

    current_plan = weighted_choice(PLAN_KEYS, plan_weights_local)

    # Assign payment card profile (sticky per customer)
    card_brand = weighted_choice(CARD_BRANDS, CARD_BRAND_WEIGHTS)
    card_type  = weighted_choice(CARD_TYPES,  CARD_TYPE_WEIGHTS)

    subscription_rows: list[dict] = []
    invoice_rows:      list[dict] = []

    sub_start   = signup_date
    sub_version = 1
    active      = True
    churn_type  = None

    current_sub_id = stripe_sub_id()

    while active and sub_start <= SIM_END:
        sub_end = SIM_END  # default – assume active through sim window

        # ── Monthly tick simulation for this subscription version ────────────
        churn_month_idx  = None
        upgrade_month    = None
        downgrade_month  = None
        months_on_plan   = 0

        tick_date = sub_start
        while tick_date <= SIM_END:
            mo = month_offset(tick_date)
            months_on_plan += 1

            # ── Churn evaluation ─────────────────────────────────────────────
            churn_p = MONTHLY_CHURN_PROB[current_plan]
            # Accelerate churn slightly after month 18 price increase if affected
            if mo >= PRICE_INCREASE_MONTH:
                churn_p *= 1.08

            if random.random() < churn_p:
                churn_month_idx = mo
                sub_end = tick_date + timedelta(days=random.randint(1, 28))
                sub_end = min(sub_end, SIM_END)

                # Decide voluntary vs involuntary churn.
                # Require at least 3 months of tenure before voluntary churn:
                # customers who haven't cleared 2+ paid invoices are more likely
                # to have churned due to payment failure (involuntary).
                if months_on_plan > 2 and random.random() < VOLUNTARY_CHURN_SHARE:
                    churn_type = "voluntary"
                else:
                    churn_type = "involuntary"

                active = False
                break

            # ── Plan change evaluation (only if no churn this month) ─────────
            up_p   = UPGRADE_PROB.get(current_plan, 0.0)
            down_p = DOWNGRADE_PROB.get(current_plan, 0.0)
            r = random.random()

            if r < up_p and months_on_plan >= 2:
                upgrade_month = mo
                sub_end       = tick_date
                break

            elif r < up_p + down_p and months_on_plan >= 3:
                downgrade_month = mo
                sub_end         = tick_date
                break

            tick_date = add_months(tick_date, 1)

        # ── Record subscription version ──────────────────────────────────────
        price_at_start = plan_price(current_plan, sub_start)
        price_at_end   = plan_price(current_plan, min(sub_end, SIM_END))
        plan_sk        = (f"plan_{current_plan}_v2"
                          if month_offset(min(sub_end, SIM_END)) >= PRICE_INCREASE_MONTH
                          else f"plan_{current_plan}_v1")

        sub_status = "active"
        if churn_type == "voluntary":
            sub_status = "cancelled"
        elif churn_type == "involuntary":
            sub_status = "past_due_churned"
        elif upgrade_month is not None:
            sub_status = "upgraded"
        elif downgrade_month is not None:
            sub_status = "downgraded"
        elif sub_end >= SIM_END:
            sub_status = "active"

        subscription_rows.append({
            "subscription_id":      current_sub_id,
            "customer_id":          cid,
            "plan_key":             current_plan,
            "plan_surrogate_key":   plan_sk,
            "version":              sub_version,
            "status":               sub_status,
            "start_date":           sub_start.isoformat(),
            "end_date":             sub_end.isoformat() if sub_end < SIM_END else None,
            "monthly_price":        price_at_start,
            "monthly_price_at_end": price_at_end,
            "churn_type":           churn_type,
            "card_brand":           card_brand,
            "card_type":            card_type,
            "mrr":                  round(price_at_start, 2),
        })

        # ── Generate invoices for this subscription window ───────────────────
        inv_rows = generate_invoices_for_subscription(
            subscription_id  = current_sub_id,
            customer_id      = cid,
            plan_key         = current_plan,
            card_brand       = card_brand,
            card_type        = card_type,
            billing_start    = sub_start,
            billing_end      = sub_end,
            is_involuntary   = (churn_type == "involuntary"),
            churn_month_idx  = churn_month_idx,
        )
        invoice_rows.extend(inv_rows)

        # ── Handle plan transitions ──────────────────────────────────────────
        if upgrade_month is not None and sub_end < SIM_END:
            plan_idx = PLAN_KEYS.index(current_plan)
            if plan_idx < len(PLAN_KEYS) - 1:
                current_plan = PLAN_KEYS[plan_idx + 1]
            sub_start   = sub_end
            sub_version += 1
            current_sub_id = stripe_sub_id()
            churn_type  = None
            active      = True

        elif downgrade_month is not None and sub_end < SIM_END:
            plan_idx = PLAN_KEYS.index(current_plan)
            if plan_idx > 0:
                current_plan = PLAN_KEYS[plan_idx - 1]
            sub_start   = sub_end
            sub_version += 1
            current_sub_id = stripe_sub_id()
            churn_type  = None
            active      = True

        else:
            # Churned or simulation ended – exit lifecycle loop
            break

    return subscription_rows, invoice_rows


# ════════════════════════════════════════════════════════════════════════════════
# CSV STREAMING WRITERS
# ════════════════════════════════════════════════════════════════════════════════

def write_csv(path: Path, rows: list[dict], label: str) -> None:
    if not rows:
        log.warning("No rows to write for %s – skipping.", label)
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("  ✔ Wrote %-35s  %10s rows  →  %s",
             label, f"{len(rows):,}", path.relative_to(PROJECT_ROOT))


# ════════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ════════════════════════════════════════════════════════════════════════════════

def main() -> None:
    t0 = time.perf_counter()
    log.info("=" * 72)
    log.info("SaaS Revenue Leakage & Subscription Lifecycle – Data Generator")
    log.info("=" * 72)
    log.info("Simulation window : %s → %s (%d months)", SIM_START, SIM_END, SIM_MONTHS)
    log.info("Target customers  : %s", f"{N_CUSTOMERS:,}")
    log.info("Output directory  : %s", RAW_DIR)
    log.info("-" * 72)

    # ── 1. Dimension: plans (SCD Type 2) ─────────────────────────────────────
    log.info("Step 1/4 · Generating dim_plans_historical (SCD Type 2)…")
    plans = build_dim_plans_historical()
    write_csv(RAW_DIR / "dim_plans_historical.csv", plans, "dim_plans_historical")

    # ── 2. Dimension: customers ───────────────────────────────────────────────
    log.info("Step 2/4 · Generating dim_customers…")
    customers = build_dim_customers()
    write_csv(RAW_DIR / "dim_customers.csv", customers, "dim_customers")

    # ── 3 & 4. Facts: subscriptions + invoices ───────────────────────────────
    log.info("Step 3–4/4 · Simulating subscription lifecycles + invoice dunning…")
    log.info("  (This is the heavy loop – generating ~400K+ transactional events)")

    all_subscriptions: list[dict] = []
    all_invoices:      list[dict] = []

    milestone = N_CUSTOMERS // 10   # log every 10%

    for idx, customer in enumerate(customers, start=1):
        sub_rows, inv_rows = simulate_customer_lifecycle(customer)
        all_subscriptions.extend(sub_rows)
        all_invoices.extend(inv_rows)

        if idx % milestone == 0 or idx == N_CUSTOMERS:
            elapsed = time.perf_counter() - t0
            pct     = (idx / N_CUSTOMERS) * 100
            log.info(
                "  [%5.1f%%]  customers=%7s  subscriptions=%8s  invoices=%9s  elapsed=%.1fs",
                pct,
                f"{idx:,}",
                f"{len(all_subscriptions):,}",
                f"{len(all_invoices):,}",
                elapsed,
            )

    # ── Write facts ───────────────────────────────────────────────────────────
    write_csv(RAW_DIR / "fact_subscriptions.csv", all_subscriptions, "fact_subscriptions")
    write_csv(RAW_DIR / "fact_invoices.csv",      all_invoices,      "fact_invoices")

    # ── Final summary ─────────────────────────────────────────────────────────
    t1      = time.perf_counter()
    elapsed = t1 - t0

    log.info("-" * 72)
    log.info("COMPLETED in %.2f seconds", elapsed)
    log.info("-" * 72)
    log.info("Row counts:")
    log.info("  dim_customers         : %s", f"{len(customers):,}")
    log.info("  dim_plans_historical  : %s", f"{len(plans):,}")
    log.info("  fact_subscriptions    : %s", f"{len(all_subscriptions):,}")
    log.info("  fact_invoices         : %s", f"{len(all_invoices):,}")
    log.info("  TOTAL                 : %s", f"{len(customers)+len(plans)+len(all_subscriptions)+len(all_invoices):,}")
    log.info("-" * 72)

    # ── Churn breakdown validation ────────────────────────────────────────────
    involuntary_subs = [s for s in all_subscriptions if s.get("churn_type") == "involuntary"]
    voluntary_subs   = [s for s in all_subscriptions if s.get("churn_type") == "voluntary"]
    total_churned    = len(involuntary_subs) + len(voluntary_subs)

    if total_churned > 0:
        inv_pct = len(involuntary_subs) / total_churned * 100
        vol_pct = len(voluntary_subs)   / total_churned * 100
        log.info("Churn breakdown (target: 65%% involuntary / 35%% voluntary):")
        log.info("  Involuntary (revenue leakage): %s  (%.1f%%)", f"{len(involuntary_subs):,}", inv_pct)
        log.info("  Voluntary   (self-cancelled):  %s  (%.1f%%)", f"{len(voluntary_subs):,}",   vol_pct)

    # ── Invoice status breakdown ──────────────────────────────────────────────
    paid_inv   = sum(1 for i in all_invoices if i["status"] == "paid")
    failed_inv = sum(1 for i in all_invoices if i["status"] == "failed")
    log.info("Invoice status breakdown:")
    log.info("  Paid   invoices: %s  (%.1f%%)", f"{paid_inv:,}",   paid_inv   / max(len(all_invoices), 1) * 100)
    log.info("  Failed invoices: %s  (%.1f%%)", f"{failed_inv:,}", failed_inv / max(len(all_invoices), 1) * 100)

    # ── Debit / insufficient_funds flaw signal ────────────────────────────────
    # Filter on prior_failure_code so we capture ALL retry outcomes (paid + failed),
    # not just the rows that happened to fail on this attempt.
    debit_insuf = [i for i in all_invoices
                   if i["card_type"] == "debit"
                   and i["prior_failure_code"] == "insufficient_funds"
                   and i["attempt_number"] > 1]
    fast_retry  = [i for i in debit_insuf
                   if i["retry_gap_days"] is not None and 1 <= i["retry_gap_days"] <= 2]
    slow_retry  = [i for i in debit_insuf
                   if i["retry_gap_days"] is not None and 5 <= i["retry_gap_days"] <= 7]
    fast_fail   = sum(1 for i in fast_retry  if i["status"] == "failed")
    slow_fail   = sum(1 for i in slow_retry  if i["status"] == "failed")

    log.info("Embedded operational flaw signal (debit + insufficient_funds retries):")
    log.info("  Fast retry (1-2d):    n=%s  fail_rate=%.1f%%  (expected ~84%%)",
             f"{len(fast_retry):,}", fast_fail / max(len(fast_retry), 1) * 100)
    log.info("  Payroll retry (5-7d): n=%s  fail_rate=%.1f%%  (expected ~48%%)",
             f"{len(slow_retry):,}", slow_fail / max(len(slow_retry), 1) * 100)
    log.info("=" * 72)

    # ── Confirm 400K+ threshold ───────────────────────────────────────────────
    total_events = len(all_subscriptions) + len(all_invoices)
    if total_events < 400_000:
        log.warning(
            "Total transactional events (%s) is below the 400K target. "
            "Consider increasing N_CUSTOMERS or churn rates.",
            f"{total_events:,}",
        )
    else:
        log.info("✔ 400K+ transactional event target met: %s events", f"{total_events:,}")


if __name__ == "__main__":
    main()
