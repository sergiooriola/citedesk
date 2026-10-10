import asyncio
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from citedesk.deployment import Access
from citedesk.service import TokenGate

ISSUER = "https://id.example/auth"
ACCESS = Access(
    issuer=ISSUER,
    jwks_url="https://id.example/auth/keys",
    emails=("Staff@School.example",),
    subjects=("user-7",),
)
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


type PrivateKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey


def published(key: PrivateKey) -> jwt.PyJWK:
    if isinstance(key, rsa.RSAPrivateKey):
        return jwt.PyJWK.from_dict(RSAAlgorithm.to_jwk(key.public_key(), as_dict=True))
    return jwt.PyJWK.from_dict(ECAlgorithm.to_jwk(key.public_key(), as_dict=True))


class Keys:
    """Stands in for the provider's published keys: one key, or none it can reach."""

    def __init__(self, key: PrivateKey = KEY, error: Exception | None = None) -> None:
        self.key = published(key)
        self.error = error

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:  # noqa: ARG002
        if self.error:
            raise self.error
        return self.key


def token(key: PrivateKey | str = KEY, algorithm: str = "ES256", **claims: Any) -> str:  # noqa: ANN401
    payload = {"iss": ISSUER, "sub": "user-1", "exp": time.time() + 600} | claims
    payload = {name: value for name, value in payload.items() if value is not None}
    return jwt.encode(payload, key, algorithm=algorithm)


def refusal(presented: str | None, access: Access = ACCESS, keys: Keys | None = None) -> str | None:
    return asyncio.run(TokenGate(access, keys or Keys()).refusal(presented))


def test_a_listed_email_passes_whatever_its_case() -> None:
    assert refusal(token(email="staff@school.EXAMPLE")) is None


def test_a_listed_subject_passes_without_an_email() -> None:
    assert refusal(token(sub="user-7")) is None


def test_someone_signed_in_but_not_listed_is_not_allowed() -> None:
    assert refusal(token(email="family@home.example")) == "not_allowed"
    assert refusal(token()) == "not_allowed"
    assert refusal(token(email=["staff@school.example"])) == "not_allowed"


@pytest.mark.parametrize("presented", [None, "", "not-a-token"])
def test_without_a_token_the_person_has_to_sign_in(presented: str | None) -> None:
    assert refusal(presented) == "sign_in_required"


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": time.time() - 60},
        {"exp": None},
        {"iss": "https://elsewhere.example"},
        {"sub": None},
    ],
)
def test_a_token_that_is_expired_from_elsewhere_or_incomplete_is_refused(
    claims: dict[str, Any],
) -> None:
    assert refusal(token(email="staff@school.example", **claims)) == "sign_in_required"


def test_a_token_signed_with_another_key_is_refused() -> None:
    assert refusal(token(OTHER_KEY, email="staff@school.example")) == "sign_in_required"


def test_a_token_signed_with_a_shared_secret_is_refused() -> None:
    forged = token("a-secret-that-is-long-enough-for-hs256", "HS256", email="staff@school.example")

    assert refusal(forged) == "sign_in_required"


def test_an_rsa_signature_is_accepted_too() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert refusal(token(key, "RS256", sub="user-7"), keys=Keys(key)) is None


def test_the_audience_is_checked_only_when_the_deployment_sets_one() -> None:
    strict = ACCESS.model_copy(update={"audience": "authenticated"})

    assert refusal(token(sub="user-7", aud="anything")) is None
    assert refusal(token(sub="user-7", aud="authenticated"), strict) is None
    assert refusal(token(sub="user-7", aud="anything"), strict) == "sign_in_required"
    assert refusal(token(sub="user-7"), strict) == "sign_in_required"


def test_when_the_keys_cannot_be_fetched_nobody_passes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    keys = Keys(error=jwt.PyJWKClientConnectionError("down"))

    assert refusal(token(sub="user-7"), keys=keys) == "sign_in_required"
    assert "the provider's keys could not be fetched" in caplog.text


def test_by_default_the_keys_come_from_the_deployments_address() -> None:
    gate = TokenGate(ACCESS)

    assert isinstance(gate._keys, jwt.PyJWKClient)
    assert gate._keys.uri == "https://id.example/auth/keys"
