"""A newly issued token and its absolute expiry."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime
