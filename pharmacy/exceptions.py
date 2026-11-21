"""Custom exceptions (Milestone 1, Section 5.4 / Figure 3.4).

Every error the system raises on purpose inherits from PharmacyError.
That means the GUI (Milestone 3) can catch ONE type -- `except PharmacyError` --
and show a friendly message instead of crashing.
"""


class PharmacyError(Exception):
    """Base class for all errors raised on purpose by this system."""


class ValidationError(PharmacyError):
    """Input is invalid (blank field, bad quantity, missing receipt, ...)."""


class DuplicateCodeError(ValidationError):
    """A medicine code, branch name or username already exists."""


class InvalidPriceError(ValidationError):
    """Unit price is zero, negative or not a number."""


class NotFoundError(PharmacyError):
    """A medicine, branch, prescription, user or prescriber does not exist."""


class InsufficientStockError(PharmacyError):
    """Not enough stock at a branch for the requested quantity."""


class UnauthorisedPrescriberError(PharmacyError):
    """A controlled medicine was prescribed by someone not on the allow-list."""


class InvalidStatusTransitionError(PharmacyError):
    """Prescription status change that is not allowed (e.g. dispensing twice)."""


class AuthenticationError(PharmacyError):
    """Login failed (unknown user, wrong password or inactive account)."""


class AccessDeniedError(PharmacyError):
    """The user's role (or branch) does not allow this action."""
