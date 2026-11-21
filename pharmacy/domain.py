"""Domain model: the business objects and the rules they protect.

Nothing in this file knows about SQL or tkinter. Each class guards its own
data so that an invalid object can never exist ("invariants" from Milestone 1).

Encapsulation reminder:
    * Attributes start with ONE underscore (_name) = "please don't touch directly".
    * Outside code reads them through @property and changes them only through
      methods that run the validation checks.
"""
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from enum import Enum

from .exceptions import (
    InsufficientStockError,
    InvalidPriceError,
    InvalidStatusTransitionError,
    NotFoundError,
    ValidationError,
)
from .validators import clean_code, clean_text, positive_int


# ---------------------------------------------------------------------------
# Enumerations: a fixed list of allowed values (prevents typos like "Pendng")
# The .value is the lowercase text stored in SQLite.
# ---------------------------------------------------------------------------
class PrescriptionStatus(Enum):
    PENDING = "pending"
    DISPENSED = "dispensed"
    CANCELLED = "cancelled"


class PatientCategory(Enum):
    STUDENT = "student"
    STAFF = "staff"
    EXTERNAL = "external"   # external patients must have a finance receipt (F6)


class MovementType(Enum):
    RECEIPT = "receipt"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    DISPENSE = "dispense"


# ---------------------------------------------------------------------------
# PrescriberRegistry: the simulated allow-list of authorised prescriber codes
# ---------------------------------------------------------------------------
class PrescriberRegistry:
    """A set of prescriber codes allowed to prescribe controlled medicines (R4)."""

    def __init__(self, codes=None):
        self._allowed_codes = set()
        for code in (codes or []):
            self.add(code)

    def add(self, code):
        self._allowed_codes.add(clean_code(code, "Prescriber code"))

    def remove(self, code):
        code = clean_code(code, "Prescriber code")
        if code not in self._allowed_codes:
            raise NotFoundError(f"Prescriber '{code}' was not found.")
        self._allowed_codes.remove(code)

    def is_authorised(self, code):
        """True only if the code is really ON the list (not just non-empty)."""
        if not isinstance(code, str):
            return False
        return code.strip().upper() in self._allowed_codes


# ---------------------------------------------------------------------------
# Medicine hierarchy  (INHERITANCE + METHOD OVERRIDING + POLYMORPHISM)
#
#            Medicine  (abstract)
#              /    \
#   OrdinaryMedicine  ControlledMedicine
# ---------------------------------------------------------------------------
class Medicine(ABC):
    """Abstract base class: data and rules shared by ALL medicines.

    Because it inherits from ABC and has @abstractmethod methods, you cannot
    write Medicine(...) directly -- you must create a subclass that implements
    can_dispense() and describe().
    """

    def __init__(self, code, name, unit_price, reorder_level):
        self._code = clean_code(code, "Medicine code")
        self._name = clean_text(name, "Medicine name")
        # Assigning through the property below runs the validation (setter).
        self.unit_price = unit_price
        self.reorder_level = reorder_level

    # --- read-only properties ---------------------------------------------
    @property
    def code(self):
        return self._code

    @property
    def name(self):
        return self._name

    # --- unit_price: property WITH a validating setter ---------------------
    @property
    def unit_price(self):
        return self._unit_price

    @unit_price.setter
    def unit_price(self, value):
        message = "Unit price must be a number greater than zero."
        if isinstance(value, bool):
            raise InvalidPriceError(message)
        try:
            # str() first so 0.1 float becomes Decimal('0.1') not 0.1000000000000000055...
            price = Decimal(str(value).strip())
            if not price.is_finite():          # rejects NaN / Infinity
                raise InvalidPriceError(message)
            price = price.quantize(Decimal("0.01"))   # exactly 2 decimal places (A7)
        except InvalidOperation:               # e.g. the text "abc"
            raise InvalidPriceError(message)
        if price <= 0:                         # R1: price must be positive
            raise InvalidPriceError(message)
        self._unit_price = price

    # --- reorder_level: property WITH a validating setter ------------------
    @property
    def reorder_level(self):
        return self._reorder_level

    @reorder_level.setter
    def reorder_level(self, value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValidationError("Reorder level must be a whole number, 0 or more.")
        self._reorder_level = value

    # --- behaviour that each subclass MUST define (the polymorphic hooks) ---
    @property
    @abstractmethod
    def is_controlled(self):
        """True for controlled medicines. Used by the repository to store the type."""

    @abstractmethod
    def can_dispense(self, prescriber_code, registry):
        """May this medicine be dispensed for this prescriber? (R4)"""

    @abstractmethod
    def describe(self):
        """One-line human readable summary (used to label GUI rows)."""


class OrdinaryMedicine(Medicine):
    """A medicine with no prescriber restriction."""

    @property
    def is_controlled(self):
        return False

    def can_dispense(self, prescriber_code, registry):
        # OVERRIDES the abstract method: ordinary medicines skip the check.
        return True

    def describe(self):
        return f"Ordinary: {self.code} - {self.name} @ {self.unit_price}"


class ControlledMedicine(Medicine):
    """A medicine that may only be dispensed for an allow-listed prescriber."""

    @property
    def is_controlled(self):
        return True

    def can_dispense(self, prescriber_code, registry):
        # OVERRIDES the abstract method: ask the allow-list.
        return registry.is_authorised(prescriber_code)

    def describe(self):
        return (f"Controlled: {self.code} - {self.name} @ {self.unit_price} "
                "[prescriber check required]")


# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------
class Branch:
    """One dispensing point, e.g. 'Main Campus'."""

    def __init__(self, name, branch_id=None):
        self._name = clean_text(name, "Branch name")
        self._branch_id = branch_id        # None until SQLite assigns one

    @property
    def branch_id(self):
        return self._branch_id

    @property
    def name(self):
        return self._name


# ---------------------------------------------------------------------------
# StockItem: quantity of ONE medicine at ONE branch (R2: never negative)
# ---------------------------------------------------------------------------
class StockItem:
    def __init__(self, medicine_code, branch_id, quantity=0):
        self._medicine_code = clean_code(medicine_code, "Medicine code")
        self._branch_id = branch_id
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ValidationError("Stock quantity cannot be negative.")
        self._quantity = quantity

    @property
    def medicine_code(self):
        return self._medicine_code

    @property
    def branch_id(self):
        return self._branch_id

    @property
    def quantity(self):
        # Read-only: there is NO setter, so quantity can only change through
        # add() and remove(), which both protect the "never negative" rule.
        return self._quantity

    def add(self, amount):
        """Increase stock by a positive whole number."""
        self._quantity += positive_int(amount, "Quantity")

    def remove(self, amount, branch_name=None):
        """Decrease stock. Raises InsufficientStockError (quantity unchanged)
        if we do not have enough."""
        amount = positive_int(amount, "Quantity")
        if amount > self._quantity:
            where = f" at {branch_name}" if branch_name else ""
            raise InsufficientStockError(
                f"Only {self._quantity} units of {self._medicine_code} "
                f"available{where}; {amount} requested."
            )
        self._quantity -= amount

    def is_low(self, reorder_level):
        """R7: low stock means quantity AT OR BELOW the reorder level."""
        return self._quantity <= reorder_level


# ---------------------------------------------------------------------------
# PrescriptionLine and Prescription
# ---------------------------------------------------------------------------
class PrescriptionLine:
    """One medicine + quantity on a prescription."""

    def __init__(self, medicine_code, quantity):
        self._medicine_code = clean_code(medicine_code, "Medicine code")
        self._quantity = positive_int(quantity, "Quantity")

    @property
    def medicine_code(self):
        return self._medicine_code

    @property
    def quantity(self):
        return self._quantity


class Prescription:
    """A patient's request for one visit. Owns its lines and its status.

    Status lifecycle (the only legal moves):
        PENDING --> DISPENSED
        PENDING --> CANCELLED
    """

    def __init__(self, patient_id, patient_category, branch_id, prescriber_code,
                 prescribed_by, lines, finance_receipt_no=None,
                 status=PrescriptionStatus.PENDING, prescription_id=None,
                 dispensed_by=None, dispensed_at=None):
        self._patient_id = clean_text(patient_id, "Patient ID")
        self._patient_category = self._to_category(patient_category)
        self._branch_id = branch_id
        self._prescriber_code = clean_code(prescriber_code, "Prescriber code")
        self._prescribed_by = prescribed_by

        # Finance receipt (INV-23): mandatory for external patients only.
        receipt = (finance_receipt_no or "").strip() or None
        if self._patient_category is PatientCategory.EXTERNAL and receipt is None:
            raise ValidationError(
                "A finance receipt number is required for external patients.")
        self._finance_receipt_no = receipt

        # Lines (INV-09): at least one, and no medicine listed twice (A9).
        lines = list(lines or [])
        if not lines:
            raise ValidationError("Add at least one line.")
        codes = [line.medicine_code for line in lines]
        if len(codes) != len(set(codes)):
            raise ValidationError("Medicine already on this prescription.")
        self._lines = lines

        # Status fields (INV-25): dispenser + time exist only when dispensed.
        self._status = status
        self._prescription_id = prescription_id
        self._dispensed_by = dispensed_by
        self._dispensed_at = dispensed_at
        if (status is PrescriptionStatus.DISPENSED) != (dispensed_by is not None
                                                         and dispensed_at is not None):
            raise ValidationError(
                "Dispenser and time must be recorded if (and only if) dispensed.")

    @staticmethod
    def _to_category(value):
        """Accept either a PatientCategory or its text value ('student')."""
        if isinstance(value, PatientCategory):
            return value
        try:
            return PatientCategory(str(value).strip().lower())
        except ValueError:
            raise ValidationError("Patient category must be student, staff or external.")

    # --- read-only properties ---------------------------------------------
    @property
    def prescription_id(self):
        return self._prescription_id

    @property
    def patient_id(self):
        return self._patient_id

    @property
    def patient_category(self):
        return self._patient_category

    @property
    def finance_receipt_no(self):
        return self._finance_receipt_no

    @property
    def branch_id(self):
        return self._branch_id

    @property
    def prescriber_code(self):
        return self._prescriber_code

    @property
    def prescribed_by(self):
        return self._prescribed_by

    @property
    def status(self):
        return self._status

    @property
    def dispensed_by(self):
        return self._dispensed_by

    @property
    def dispensed_at(self):
        return self._dispensed_at

    @property
    def lines(self):
        # A COPY of the list, so callers cannot add/remove lines behind our back.
        return list(self._lines)

    def assign_id(self, new_id):
        """Called once by the service after the database gives us an id."""
        if self._prescription_id is not None:
            raise ValidationError("Prescription id is already set.")
        self._prescription_id = new_id

    # --- status transitions ----------------------------------------------
    def ensure_dispensable(self):
        """Raise InvalidStatusTransitionError unless the status is PENDING (R6)."""
        if self._status is PrescriptionStatus.DISPENSED:
            raise InvalidStatusTransitionError(
                "This prescription is already dispensed and cannot be changed.")
        if self._status is PrescriptionStatus.CANCELLED:
            raise InvalidStatusTransitionError(
                "This prescription was cancelled and cannot be dispensed.")

    def mark_dispensed(self, user_id, when):
        """PENDING -> DISPENSED, recording who and when."""
        self.ensure_dispensable()
        self._status = PrescriptionStatus.DISPENSED
        self._dispensed_by = user_id
        self._dispensed_at = when

    def mark_cancelled(self):
        """PENDING -> CANCELLED (Advanced feature FR-A1)."""
        if self._status is PrescriptionStatus.DISPENSED:
            raise InvalidStatusTransitionError(
                "This prescription is already dispensed and cannot be changed.")
        if self._status is PrescriptionStatus.CANCELLED:
            raise InvalidStatusTransitionError("This prescription is already cancelled.")
        self._status = PrescriptionStatus.CANCELLED


# ---------------------------------------------------------------------------
# StockMovement: one row of the append-only stock ledger (F8, INV-24)
# ---------------------------------------------------------------------------
class StockMovement:
    """Immutable record of a stock change. There are no setters or update methods."""

    def __init__(self, medicine_code, branch_id, movement_type, quantity,
                 reference, user_id, movement_id=None, created_at=None):
        self._medicine_code = clean_code(medicine_code, "Medicine code")
        self._branch_id = branch_id
        if not isinstance(movement_type, MovementType):
            raise ValidationError("Invalid movement type.")
        self._movement_type = movement_type
        self._quantity = positive_int(quantity, "Quantity")   # direction comes from the type
        self._reference = clean_text(reference, "Reference")
        self._user_id = user_id
        self._movement_id = movement_id
        self._created_at = created_at

    @property
    def movement_id(self):
        return self._movement_id

    @property
    def medicine_code(self):
        return self._medicine_code

    @property
    def branch_id(self):
        return self._branch_id

    @property
    def movement_type(self):
        return self._movement_type

    @property
    def quantity(self):
        return self._quantity

    @property
    def reference(self):
        return self._reference

    @property
    def user_id(self):
        return self._user_id

    @property
    def created_at(self):
        return self._created_at
