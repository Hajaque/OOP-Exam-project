"""Access control: users, roles, permissions and sessions (Milestone 1, F7/F10).

Idea in one paragraph: a person logs in and gets a Session. Before a service
does anything it asks the Session "may this user do X?". The rules about which
role may do what live in ONE place: AccessPolicy.
"""
import hashlib
import hmac
import os
from enum import Enum

from .exceptions import AccessDeniedError, AuthenticationError, ValidationError
from .validators import clean_code, clean_text

# Number of times PBKDF2 repeats its hashing. More = slower for attackers.
# (The unit tests lower this number so they run fast.)
PBKDF2_ITERATIONS = 200_000


class Role(Enum):
    ADMIN = "admin"
    PRESCRIBER = "prescriber"      # a doctor
    DISPENSER = "dispenser"        # a pharmacist
    STORE_CLERK = "store_clerk"


class Permission(Enum):
    MANAGE_USERS = "manage_users"
    MANAGE_CATALOGUE = "manage_catalogue"
    MANAGE_BRANCHES = "manage_branches"
    MANAGE_PRESCRIBERS = "manage_prescribers"
    RECEIVE_STOCK = "receive_stock"
    ALLOCATE_STOCK = "allocate_stock"
    VIEW_STOCK = "view_stock"
    CREATE_PRESCRIPTION = "create_prescription"
    VIEW_PRESCRIPTIONS = "view_prescriptions"
    DISPENSE = "dispense"
    CANCEL_PRESCRIPTION = "cancel_prescription"
    VIEW_REPORTS = "view_reports"


# ---------------------------------------------------------------------------
# Password hashing (A20): PBKDF2-HMAC-SHA256 with a random salt, standard library only.
# We NEVER store the password itself, only "pbkdf2_sha256$iterations$salt$hash".
# ---------------------------------------------------------------------------
def hash_password(plain, salt=None):
    """Return a storable hash string for `plain`."""
    if not isinstance(plain, str) or len(plain) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    salt = salt or os.urandom(16)               # random salt: same password -> different hash
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


class UserAccount:
    """One worker's account. Holds a password HASH, never the password."""

    def __init__(self, username, full_name, role, password_hash, branch_id=None,
                 prescriber_code=None, active=True, user_id=None):
        self._username = clean_text(username, "Username").lower()
        self._full_name = clean_text(full_name, "Full name")
        if not isinstance(role, Role):
            raise ValidationError("Invalid role.")
        self._role = role
        # INV-21: everyone except the administrator needs a home branch.
        if role is not Role.ADMIN and branch_id is None:
            raise ValidationError("Home branch is required for this role.")
        self._branch_id = branch_id
        # INV-22: a doctor's account must carry a prescriber code.
        if role is Role.PRESCRIBER:
            self._prescriber_code = clean_code(
                prescriber_code, "Prescriber code")
        else:
            self._prescriber_code = None
        self._password_hash = clean_text(password_hash, "Password hash")
        self._active = bool(active)
        self._user_id = user_id

    @property
    def user_id(self):
        return self._user_id

    @property
    def username(self):
        return self._username

    @property
    def full_name(self):
        return self._full_name

    @property
    def role(self):
        return self._role

    @property
    def branch_id(self):
        return self._branch_id

    @property
    def prescriber_code(self):
        return self._prescriber_code

    @property
    def is_active(self):
        return self._active

    @property
    def password_hash(self):
        """Needed only by the repository to save the account."""
        return self._password_hash

    def assign_id(self, new_id):
        if self._user_id is not None:
            raise ValidationError("User id is already set.")
        self._user_id = new_id

    def verify_password(self, plain):
        """True if `plain` matches the stored hash (constant-time comparison)."""
        try:
            _, iterations, salt_hex, digest_hex = self._password_hash.split("$")
            digest = hashlib.pbkdf2_hmac(
                "sha256", str(plain).encode("utf-8"),
                bytes.fromhex(salt_hex), int(iterations))
        except ValueError:
            return False
        return hmac.compare_digest(digest.hex(), digest_hex)

    def can_access_branch(self, branch_id):
        """Admin may use every branch; everyone else only their home branch."""
        return self._role is Role.ADMIN or self._branch_id == branch_id


class AccessPolicy:
    """The single role -> permissions table (Milestone 1, Section 8.3)."""

    def __init__(self):
        P = Permission
        self._grants = {
            Role.ADMIN: frozenset({
                P.MANAGE_USERS, P.MANAGE_CATALOGUE, P.MANAGE_BRANCHES,
                P.MANAGE_PRESCRIBERS, P.RECEIVE_STOCK, P.ALLOCATE_STOCK,
                P.VIEW_STOCK, P.VIEW_PRESCRIPTIONS, P.VIEW_REPORTS}),
            Role.PRESCRIBER: frozenset({
                P.CREATE_PRESCRIPTION, P.VIEW_PRESCRIPTIONS, P.CANCEL_PRESCRIPTION}),
            Role.DISPENSER: frozenset({
                P.VIEW_STOCK, P.VIEW_PRESCRIPTIONS, P.DISPENSE}),
            Role.STORE_CLERK: frozenset({
                P.RECEIVE_STOCK, P.ALLOCATE_STOCK, P.VIEW_STOCK}),
        }

    def is_allowed(self, role, permission):
        # "Deny by default": anything not listed above is refused.
        return permission in self._grants.get(role, frozenset())


class Session:
    """A successful login. Services call require()/require_branch() on it."""

    def __init__(self, user, policy):
        if not user.is_active:
            raise AuthenticationError("Incorrect username or password.")
        self._user = user
        self._policy = policy

    @property
    def user(self):
        return self._user

    def require(self, permission):
        """Raise AccessDeniedError unless the user's role holds `permission`."""
        if not self._policy.is_allowed(self._user.role, permission):
            raise AccessDeniedError("Your role cannot do this.")

    def require_branch(self, branch_id):
        """Raise AccessDeniedError unless the user may work at `branch_id`."""
        if not self._user.can_access_branch(branch_id):
            raise AccessDeniedError("You can only work at your own branch.")

    def branch_scope(self, requested_branch_id=None):
        """Decide which branch a LIST query should cover.

        Admin: whatever was asked (None = all branches).
        Everyone else: always their own home branch.
        """
        if self._user.role is Role.ADMIN:
            return requested_branch_id
        if requested_branch_id is not None:
            self.require_branch(requested_branch_id)
        return self._user.branch_id
