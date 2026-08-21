"""Token validation failure exposed at the authentication boundary."""


class TokenError(Exception):
    """A token is missing, malformed, expired, or not trusted."""
