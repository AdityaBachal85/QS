"""Users, roles and sessions -- who changed a number, and who may.

The audit log has recorded every write since the store was built, and until now
every row said ``local``. A change log that cannot name a person is a list of
events, not an account of what happened -- and the reason the workbook has two
live shuttering rates Rs 1.25 crore apart, with nothing saying who set either
or when (C-7).

Passwords are hashed with ``hashlib.scrypt`` from the standard library. No new
dependency, and the parameters are the ones RFC 7914 recommends for interactive
logins. Sessions are opaque tokens in an HttpOnly cookie; nothing about the
user is carried in the cookie itself, so it cannot be edited into a different
role.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

#: scrypt at RFC 7914's interactive settings. n is the work factor; raising it
#: makes every login and every guess slower in the same proportion.
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32
SESSION_COOKIE = "qs_session"
SESSION_HOURS = 12


class Role(Enum):
    """What a person may do.

    Ordered: every role can do everything the ones below it can. A reviewer
    signs off and cannot edit; a viewer reads and does neither.
    """

    ADMIN = "admin"
    QS_LEAD = "qs_lead"
    QS = "qs"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


#: Roles allowed to change project data. A reviewer's job is to disagree with a
#: number, not to quietly replace it.
CAN_WRITE = frozenset({Role.ADMIN, Role.QS_LEAD, Role.QS})

#: Roles allowed to approve a correction or confirm a mapping.
CAN_APPROVE = frozenset({Role.ADMIN, Role.QS_LEAD, Role.REVIEWER})

#: Roles allowed to add and remove users.
CAN_ADMINISTER = frozenset({Role.ADMIN})


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    role: Role
    is_active: bool = True

    def may_write(self) -> bool:
        return self.is_active and self.role in CAN_WRITE

    def may_approve(self) -> bool:
        return self.is_active and self.role in CAN_APPROVE

    def may_administer(self) -> bool:
        return self.is_active and self.role in CAN_ADMINISTER


def hash_password(password: str, salt: bytes | None = None) -> str:
    """``scrypt$n$r$p$salt$key``, all hex -- self-describing, so the work factor
    can be raised later without invalidating existing passwords."""
    if not password or len(password) < 8:
        raise ValueError("a password must be at least 8 characters")
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P,
                         dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison, and a stored hash it cannot parse is a no."""
    try:
        scheme, n, r, p, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(key_hex)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, bytes.fromhex(key_hex))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry(hours: int = SESSION_HOURS) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)) \
        .isoformat(timespec="seconds")


def is_expired(expires_at: str) -> bool:
    try:
        return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True
