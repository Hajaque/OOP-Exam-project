-- ===========================================================================
-- Campus Pharmacy System - SQLite schema (Milestone 1, Section 9.4)
-- Safe to run more than once: every statement uses IF NOT EXISTS.
--
-- The CHECK / UNIQUE / FOREIGN KEY rules are a SECOND line of defence.
-- The Python classes reject bad data first; these rules make sure that even a
-- coding mistake can never save invalid data (NFR-01, "layer D" in Section 7).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS medicines (
    code           TEXT PRIMARY KEY CHECK (length(trim(code)) > 0),   -- unique code
    name           TEXT NOT NULL CHECK (length(trim(name)) > 0),
    unit_price     REAL NOT NULL CHECK (unit_price > 0),              -- positive price
    reorder_level  INTEGER NOT NULL CHECK (reorder_level >= 0),       -- non-negative
    is_controlled  INTEGER NOT NULL DEFAULT 0 CHECK (is_controlled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS branches (
    branch_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE CHECK (length(trim(username)) > 0),
    full_name       TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
    password_hash   TEXT NOT NULL CHECK (length(password_hash) > 0),  -- hash, never the password
    role            TEXT NOT NULL
                    CHECK (role IN ('admin', 'prescriber', 'dispenser', 'store_clerk')),
    branch_id       INTEGER REFERENCES branches(branch_id),
    prescriber_code TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    CHECK (role = 'admin' OR branch_id IS NOT NULL),
    CHECK (role <> 'prescriber'
           OR length(trim(coalesce(prescriber_code, ''))) > 0)
);

-- One row per (medicine, branch): quantities are held PER BRANCH (R2).
CREATE TABLE IF NOT EXISTS stock (
    medicine_code  TEXT NOT NULL REFERENCES medicines(code),
    branch_id      INTEGER NOT NULL REFERENCES branches(branch_id),
    quantity       INTEGER NOT NULL CHECK (quantity >= 0),            -- never negative
    PRIMARY KEY (medicine_code, branch_id)
);

-- Append-only ledger of every stock change (see the two triggers below).
CREATE TABLE IF NOT EXISTS stock_movements (
    movement_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    medicine_code  TEXT NOT NULL REFERENCES medicines(code),
    branch_id      INTEGER NOT NULL REFERENCES branches(branch_id),
    movement_type  TEXT NOT NULL
                   CHECK (movement_type IN ('receipt', 'transfer_in',
                                            'transfer_out', 'dispense')),
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    reference      TEXT NOT NULL CHECK (length(trim(reference)) > 0),
    user_id        INTEGER NOT NULL REFERENCES users(user_id),
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prescriptions (
    prescription_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          TEXT NOT NULL CHECK (length(trim(patient_id)) > 0),
    patient_category    TEXT NOT NULL
                        CHECK (patient_category IN ('student', 'staff', 'external')),
    finance_receipt_no  TEXT,
    branch_id           INTEGER NOT NULL REFERENCES branches(branch_id),
    prescriber_code     TEXT NOT NULL CHECK (length(trim(prescriber_code)) > 0),
    prescribed_by       INTEGER NOT NULL REFERENCES users(user_id),
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'dispensed', 'cancelled')),
    dispensed_by        INTEGER REFERENCES users(user_id),
    dispensed_at        TEXT,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- external patients must have a finance receipt (INV-23)
    CHECK (patient_category <> 'external'
           OR length(trim(coalesce(finance_receipt_no, ''))) > 0),
    -- "dispensed" and "who/when" must go together (INV-25)
    CHECK ((status = 'dispensed' AND dispensed_by IS NOT NULL
                                 AND dispensed_at IS NOT NULL)
           OR (status <> 'dispensed' AND dispensed_by IS NULL
                                      AND dispensed_at IS NULL))
);

CREATE TABLE IF NOT EXISTS prescription_lines (
    line_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_id  INTEGER NOT NULL
                     REFERENCES prescriptions(prescription_id) ON DELETE CASCADE,
    medicine_code    TEXT NOT NULL REFERENCES medicines(code),
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    UNIQUE (prescription_id, medicine_code)          -- no duplicate medicine (A9)
);

-- The simulated allow-list of prescribers for controlled medicines (R4).
CREATE TABLE IF NOT EXISTS authorised_prescribers (
    prescriber_code  TEXT PRIMARY KEY CHECK (length(trim(prescriber_code)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_stock_branch ON stock(branch_id);
CREATE INDEX IF NOT EXISTS idx_lines_prescription ON prescription_lines(prescription_id);
CREATE INDEX IF NOT EXISTS idx_prescriptions_status ON prescriptions(status, branch_id);
CREATE INDEX IF NOT EXISTS idx_movements_branch ON stock_movements(branch_id, created_at);

-- Triggers = rules that SQLite runs automatically.
-- A dispensed or cancelled prescription can never change status again (INV-13/14).
CREATE TRIGGER IF NOT EXISTS trg_prescription_status_guard
BEFORE UPDATE OF status ON prescriptions
WHEN OLD.status IN ('dispensed', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Prescription status is final');
END;

-- Ledger rows can be added but never edited or deleted (INV-24).
CREATE TRIGGER IF NOT EXISTS trg_movements_no_update
BEFORE UPDATE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'Ledger rows cannot be changed');
END;

CREATE TRIGGER IF NOT EXISTS trg_movements_no_delete
BEFORE DELETE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'Ledger rows cannot be deleted');
END;
