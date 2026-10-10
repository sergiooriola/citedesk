"""Who may use a deployment's service: people signed in elsewhere and named on a list."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal, Protocol

import jwt

if TYPE_CHECKING:
    from citedesk.deployment import Access

logger = logging.getLogger(__name__)

# Only signatures made with a private key are accepted. A token signed with a shared
# secret, or not signed at all, is refused whatever its header claims.
_ALGORITHMS = ["ES256", "RS256"]

Refusal = Literal["sign_in_required", "not_allowed"]


class Gate(Protocol):
    """Decides whether the bearer of a token may use the service."""

    async def refusal(self, token: str | None) -> Refusal | None:
        """Say why a token's bearer is turned away, or None when they may pass."""
        ...


class KeySource(Protocol):
    """Where the issuer's public keys come from. PyJWT's `PyJWKClient` is one."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        """Return the key that signed a token, fetching the issuer's keys if needed."""
        ...


class TokenGate:
    """Lets through the people an identity provider has signed in and the deployment lists.

    The person signs in with the provider, in the organisation's own website, and the
    browser sends the token the provider gave it. The service checks the token's signature
    against the provider's public keys, its issuer and its expiry, and then looks for its
    subject or its email on the deployment's list.
    """

    def __init__(self, access: Access, keys: KeySource | None = None) -> None:
        """Set up the gate of one deployment.

        Args:
            access: The provider and the list of people.
            keys: Where the provider's public keys come from. By default they are fetched
                from `access.jwks_url` and kept for five minutes.
        """
        self._access = access
        self._keys = keys or jwt.PyJWKClient(access.jwks_url, timeout=5)
        self._emails = {email.casefold() for email in access.emails}

    async def refusal(self, token: str | None) -> Refusal | None:
        """Say why a token's bearer is turned away, or None when they may pass."""
        if not token:
            return "sign_in_required"
        try:
            # Fetching the provider's keys blocks, so it happens off the event loop.
            key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key,
                algorithms=_ALGORITHMS,
                issuer=self._access.issuer,
                audience=self._access.audience,
                options={
                    "require": ["exp", "iss", "sub"],
                    "verify_aud": self._access.audience is not None,
                },
            )
        except jwt.PyJWKClientConnectionError:
            logger.warning("access: the provider's keys could not be fetched")
            return "sign_in_required"
        except jwt.PyJWTError:
            return "sign_in_required"
        email = claims.get("email")
        listed = claims["sub"] in self._access.subjects or (
            isinstance(email, str) and email.casefold() in self._emails
        )
        return None if listed else "not_allowed"
