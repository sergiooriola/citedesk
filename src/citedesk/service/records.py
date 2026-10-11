"""Records: each exchange sent to where the organisation keeps them."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx2

if TYPE_CHECKING:
    from citedesk.deployment import Records

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0


@dataclass(frozen=True)
class Exchange:
    """One message of a person and what was replied to it.

    Attributes:
        at: When the reply was sent, as an ISO 8601 time in UTC.
        conversation: What the caller names the conversation by, so that its exchanges can
            be read together. None when the caller gave no name.
        turn: Which of the person's messages in the conversation this is, from 1.
        asked: The person's message.
        replied: The text sent back.
        kind: "answer", "hand_off" or "fallback".
        entry_ids: The entries the reply rests on.
        reason: Why a fallback was sent. None otherwise.
        language: The language the model read the message in. None for a fallback.
        usd: What the model cost for this reply.
        ms: How long the reply took.
    """

    at: str
    conversation: str | None
    turn: int
    asked: str
    replied: str
    kind: str
    entry_ids: tuple[str, ...]
    reason: str | None
    language: str | None
    usd: float
    ms: int


class Recorder(Protocol):
    """Keeps exchanges somewhere."""

    async def record(self, exchange: Exchange) -> None:
        """Keep one exchange. It must not raise: a reply never depends on its record."""
        ...


class HttpRecorder:
    """Sends each exchange as a JSON object in a POST request.

    That is enough for a database with an HTTP interface or for a small receiver of the
    organisation's own. A record that cannot be delivered is logged and lost: the person
    has their reply already.
    """

    def __init__(
        self,
        records: Records,
        *,
        key: str | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Set up the recorder of one deployment.

        Args:
            records: Where the exchanges go and under which names.
            key: The secret the receiver asks for, sent in the header `records.key_header`.
            transport: How requests are sent. Tests replace it.
        """
        self._url = records.url
        self._names = records.fields
        self._headers = dict(records.headers)
        if records.key_header and key:
            self._headers[records.key_header] = key
        self._transport = transport

    async def record(self, exchange: Exchange) -> None:
        """Send one exchange, and log it if the receiver does not take it."""
        try:
            async with httpx2.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
                response = await client.post(
                    self._url, json=self._body(exchange), headers=self._headers
                )
        except httpx2.HTTPError as error:
            logger.warning("records: not delivered (%s)", type(error).__name__)
            return
        if response.is_error:
            logger.warning("records: the receiver answered %d", response.status_code)

    def _body(self, exchange: Exchange) -> dict[str, Any]:
        """Lay an exchange out under the names the receiver expects."""
        values = asdict(exchange) | {"entry_ids": list(exchange.entry_ids)}
        return {self._names.get(name, name): value for name, value in values.items()}
