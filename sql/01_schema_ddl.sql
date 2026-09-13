-- =============================================================================
-- sql/01_schema_ddl.sql
-- SaaS Revenue Leakage & Subscription Lifecycle Reconciliation
-- Lead DBA: Production Schema DDL
-- =============================================================================
-- Execution order:
--   1. Extensions
--   2. Drop existing objects (idempotent re-run)
--   3. Dimension tables
--   4. Fact tables
--   5. Composite B-Tree indexes
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid() for UUID helpers


-- ---------------------------------------------------------------------------
-- 2. Idempotent teardown (reverse FK order)
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS fact_invoices       CASCADE;
DROP TABLE IF EXISTS fact_subscriptions  CASCADE;
DROP TABLE IF EXISTS dim_plans_scd       CASCADE;
DROP TABLE IF EXISTS dim_customers       CASCADE;


-- ---------------------------------------------------------------------------
-- 3a. dim_customers
-- ---------------------------------------------------------------------------
CREATE TABLE dim_customers (
    customer_id         VARCHAR(30)  NOT NULL,
    company_name        VARCHAR(255) NOT NULL,
    contact_email       VARCHAR(255) NOT NULL,
    country             CHAR(2)      NOT NULL,
    industry            VARCHAR(100),
    company_size        VARCHAR(20),
    acquisition_channel VARCHAR(60),
    signup_date         DATE         NOT NULL,
    account_created_at  TIMESTAMPTZ  NOT NULL,

    -- Constraints
    CONSTRAINT pk_dim_customers        PRIMARY KEY (customer_id),
    CONSTRAINT ck_dim_customers_signup CHECK       (signup_date >= '2020-01-01')
);

COMMENT ON TABLE  dim_customers IS 'One row per unique B2B SaaS account.';
COMMENT ON COLUMN dim_customers.customer_id IS 'Stripe cus_* natural key.';
COMMENT ON COLUMN dim_customers.country     IS 'ISO 3166-1 alpha-2 country code.';


-- ---------------------------------------------------------------------------
-- 3b. dim_plans_scd  (SCD Type 2)
-- ---------------------------------------------------------------------------
CREATE TABLE dim_plans_scd (
    plan_sk             SERIAL          NOT NULL,
    plan_surrogate_key  VARCHAR(40)     NOT NULL,   -- e.g. plan_growth_v2
    plan_id             VARCHAR(40)     NOT NULL,   -- natural key  e.g. growth
    plan_name           VARCHAR(100)    NOT NULL,
    price               NUMERIC(10, 2)  NOT NULL,
    currency            CHAR(3)         NOT NULL    DEFAULT 'USD',
    billing_interval    VARCHAR(20)     NOT NULL    DEFAULT 'monthly',
    tier_rank           SMALLINT        NOT NULL,
    version             SMALLINT        NOT NULL    DEFAULT 1,
    valid_from          TIMESTAMPTZ     NOT NULL,
    valid_to            TIMESTAMPTZ,                -- NULL means currently active
    is_current          BOOLEAN         NOT NULL    DEFAULT TRUE,

    -- Constraints
    CONSTRAINT pk_dim_plans_scd          PRIMARY KEY (plan_sk),
    CONSTRAINT uq_dim_plans_scd_sk       UNIQUE      (plan_surrogate_key),
    CONSTRAINT ck_dim_plans_price        CHECK       (price > 0),
    CONSTRAINT ck_dim_plans_tier_rank    CHECK       (tier_rank BETWEEN 1 AND 10),
    CONSTRAINT ck_dim_plans_version      CHECK       (version   >= 1),
    CONSTRAINT ck_dim_plans_valid_range  CHECK       (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_dim_plans_currency     CHECK       (currency ~ '^[A-Z]{3}$')
);

COMMENT ON TABLE  dim_plans_scd              IS 'SCD Type 2 plan/pricing dimension. One row per plan version.';
COMMENT ON COLUMN dim_plans_scd.plan_sk      IS 'Surrogate key – auto-incrementing SERIAL.';
COMMENT ON COLUMN dim_plans_scd.plan_id      IS 'Natural key shared across SCD versions (starter|growth|enterprise|scale).';
COMMENT ON COLUMN dim_plans_scd.valid_from   IS 'Inclusive start of this price version (UTC).';
COMMENT ON COLUMN dim_plans_scd.valid_to     IS 'Exclusive end of this price version. NULL = currently active row.';
COMMENT ON COLUMN dim_plans_scd.is_current   IS 'Convenience flag: TRUE only for the latest version of each plan.';


-- ---------------------------------------------------------------------------
-- 3c. fact_subscriptions
-- ---------------------------------------------------------------------------
CREATE TABLE fact_subscriptions (
    subscription_id        VARCHAR(30)     NOT NULL,
    customer_id            VARCHAR(30)     NOT NULL,
    plan_key               VARCHAR(40)     NOT NULL,
    plan_surrogate_key     VARCHAR(40)     NOT NULL,
    version                SMALLINT        NOT NULL    DEFAULT 1,
    status                 VARCHAR(30)     NOT NULL,
    start_date             DATE            NOT NULL,
    end_date               DATE,
    monthly_price          NUMERIC(10, 2)  NOT NULL,
    monthly_price_at_end   NUMERIC(10, 2)  NOT NULL,
    churn_type             VARCHAR(20),
    card_brand             VARCHAR(20)     NOT NULL,
    card_type              VARCHAR(10)     NOT NULL,
    mrr                    NUMERIC(10, 2)  NOT NULL,

    -- Constraints
    CONSTRAINT pk_fact_subscriptions       PRIMARY KEY (subscription_id),
    CONSTRAINT fk_fact_sub_customer        FOREIGN KEY (customer_id)
                                               REFERENCES dim_customers (customer_id)
                                               ON DELETE RESTRICT,
    CONSTRAINT fk_fact_sub_plan_sk         FOREIGN KEY (plan_surrogate_key)
                                               REFERENCES dim_plans_scd (plan_surrogate_key)
                                               ON DELETE RESTRICT,
    CONSTRAINT ck_fact_sub_status          CHECK (status IN (
                                               'active', 'cancelled', 'past_due_churned',
                                               'upgraded', 'downgraded')),
    CONSTRAINT ck_fact_sub_churn_type      CHECK (churn_type IN ('voluntary', 'involuntary') OR churn_type IS NULL),
    CONSTRAINT ck_fact_sub_price           CHECK (monthly_price > 0 AND monthly_price_at_end > 0),
    CONSTRAINT ck_fact_sub_mrr             CHECK (mrr >= 0),
    CONSTRAINT ck_fact_sub_date_range      CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT ck_fact_sub_version         CHECK (version >= 1),
    CONSTRAINT ck_fact_sub_card_type       CHECK (card_type IN ('credit', 'debit')),
    CONSTRAINT ck_fact_sub_card_brand      CHECK (card_brand IN ('visa', 'mastercard', 'amex'))
);

COMMENT ON TABLE  fact_subscriptions IS 'One row per subscription version per customer (tracks upgrades/downgrades).';
COMMENT ON COLUMN fact_subscriptions.subscription_id      IS 'Stripe sub_* natural key.';
COMMENT ON COLUMN fact_subscriptions.plan_surrogate_key   IS 'FK into dim_plans_scd.plan_surrogate_key (SCD Type 2 aware).';
COMMENT ON COLUMN fact_subscriptions.version              IS 'Increments for each plan change on the same account.';
COMMENT ON COLUMN fact_subscriptions.churn_type           IS 'NULL = not churned; voluntary = intentional; involuntary = dunning failure.';
COMMENT ON COLUMN fact_subscriptions.mrr                  IS 'Monthly Recurring Revenue at subscription start.';


-- ---------------------------------------------------------------------------
-- 3d. fact_invoices
-- ---------------------------------------------------------------------------
CREATE TABLE fact_invoices (
    invoice_id          VARCHAR(30)     NOT NULL,
    subscription_id     VARCHAR(30)     NOT NULL,
    customer_id         VARCHAR(30)     NOT NULL,
    plan_key            VARCHAR(40)     NOT NULL,
    amount              NUMERIC(10, 2)  NOT NULL,
    currency            CHAR(3)         NOT NULL    DEFAULT 'USD',
    attempt_number      SMALLINT        NOT NULL,
    charge_date         DATE            NOT NULL,
    status              VARCHAR(10)     NOT NULL,
    card_brand          VARCHAR(20)     NOT NULL,
    card_type           VARCHAR(10)     NOT NULL,
    failure_code        VARCHAR(50),               -- NULL when status = 'paid'
    prior_failure_code  VARCHAR(50),               -- failure code from preceding attempt (NULL for attempt 1)
    retry_gap_days      SMALLINT,                  -- days since prior attempt (NULL for attempt 1)

    -- Constraints
    CONSTRAINT pk_fact_invoices            PRIMARY KEY (invoice_id),
    CONSTRAINT fk_fact_inv_subscription    FOREIGN KEY (subscription_id)
                                               REFERENCES fact_subscriptions (subscription_id)
                                               ON DELETE RESTRICT,
    CONSTRAINT fk_fact_inv_customer        FOREIGN KEY (customer_id)
                                               REFERENCES dim_customers (customer_id)
                                               ON DELETE RESTRICT,
    CONSTRAINT ck_fact_inv_amount          CHECK (amount >= 0),
    CONSTRAINT ck_fact_inv_attempt         CHECK (attempt_number BETWEEN 1 AND 4),
    CONSTRAINT ck_fact_inv_status          CHECK (status IN ('paid', 'failed')),
    CONSTRAINT ck_fact_inv_card_type       CHECK (card_type IN ('credit', 'debit')),
    CONSTRAINT ck_fact_inv_card_brand      CHECK (card_brand IN ('visa', 'mastercard', 'amex')),
    CONSTRAINT ck_fact_inv_failure_code    CHECK (
                                               failure_code IS NULL OR failure_code IN (
                                                   'insufficient_funds', 'card_expired',
                                                   'do_not_honor', 'generic_decline')),
    CONSTRAINT ck_fact_inv_prior_fc        CHECK (
                                               prior_failure_code IS NULL OR prior_failure_code IN (
                                                   'insufficient_funds', 'card_expired',
                                                   'do_not_honor', 'generic_decline')),
    CONSTRAINT ck_fact_inv_failure_null    CHECK (
                                               (status = 'paid'   AND failure_code IS NULL) OR
                                               (status = 'failed' AND failure_code IS NOT NULL)),
    CONSTRAINT ck_fact_inv_retry_gap       CHECK (retry_gap_days IS NULL OR retry_gap_days >= 0),
    CONSTRAINT ck_fact_inv_currency        CHECK (currency ~ '^[A-Z]{3}$')
);

COMMENT ON TABLE  fact_invoices IS 'One row per billing attempt (up to 4 dunning retries per invoice cycle).';
COMMENT ON COLUMN fact_invoices.attempt_number     IS '1 = initial charge; 2-4 = dunning retries.';
COMMENT ON COLUMN fact_invoices.failure_code       IS 'Stripe decline code on THIS attempt. NULL when paid.';
COMMENT ON COLUMN fact_invoices.prior_failure_code IS 'Decline code from the preceding attempt; drives retry strategy analysis.';
COMMENT ON COLUMN fact_invoices.retry_gap_days     IS 'Calendar days elapsed since the previous failed attempt. NULL for attempt_number=1.';


-- ---------------------------------------------------------------------------
-- 4. Composite B-Tree Indexes
-- ---------------------------------------------------------------------------

-- Subscription analytical queries: customer lifecycle by date range
CREATE INDEX idx_subscriptions_customer_dates
    ON fact_subscriptions (customer_id, start_date, end_date);

-- Invoice dunning status queries: per-subscription payment performance
CREATE INDEX idx_invoices_sub_status_date
    ON fact_invoices (subscription_id, status, charge_date);

-- Operational flaw / failure-mode analysis: debit card decline patterns
CREATE INDEX idx_invoices_failure_analysis
    ON fact_invoices (card_type, failure_code, attempt_number);

-- Additional high-value indexes for common analytical access patterns
CREATE INDEX idx_invoices_charge_date
    ON fact_invoices (charge_date);

CREATE INDEX idx_subscriptions_status
    ON fact_subscriptions (status);

CREATE INDEX idx_invoices_prior_failure
    ON fact_invoices (prior_failure_code, retry_gap_days)
    WHERE prior_failure_code IS NOT NULL;


-- ---------------------------------------------------------------------------
-- 5. Verification query (informational)
-- ---------------------------------------------------------------------------
SELECT
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
