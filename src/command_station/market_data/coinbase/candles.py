"""Unauthenticated Coinbase Advanced public candle adapter."""

from collections.abc import Callable, Mapping
from typing import Protocol, cast

from requests import Session
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, Timeout

from command_station.market_data.historical import (
    CoinbaseCandleRequest,
    HistoricalCandleRequestError,
)
from command_station.market_data.raw_archive import unix_seconds_text

MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = (0.1, 0.2, 0.4)


class _SdkCandleClient(Protocol):
    is_authenticated: bool
    session: Session

    def get_public_candles(
        self, product_id: str, start: str, end: str, granularity: str, limit: int
    ) -> object: ...


class CoinbasePublicCandleClient:
    def __init__(
        self,
        sdk_client: _SdkCandleClient | None = None,
        *,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if sdk_client is None:
            from coinbase.rest import RESTClient  # type: ignore[import-untyped]

            sdk_client = cast(
                _SdkCandleClient,
                RESTClient(api_key=None, api_secret=None, key_file=None, timeout=10),
            )
        if sdk_client.is_authenticated is not False:
            raise HistoricalCandleRequestError(
                "Coinbase public candle client requires an explicitly unauthenticated SDK client"
            )
        session = getattr(sdk_client, "session", None)
        if not isinstance(session, Session):
            raise HistoricalCandleRequestError(
                "Coinbase public candle client requires a requests Session for credential isolation"
            )
        if session.auth is not None or session.params or session.cookies:
            raise HistoricalCandleRequestError(
                "Coinbase public candle client rejects injected session credentials"
            )
        if any(name.casefold() == "authorization" for name in session.headers):
            raise HistoricalCandleRequestError(
                "Coinbase public candle client rejects injected Authorization headers"
            )
        # Requests otherwise reads ambient .netrc credentials for matching hosts.
        # This deliberately also opts out of environment proxy configuration: a
        # public historical importer must not inherit ambient authority settings.
        session.trust_env = False
        if sleeper is None:
            from time import sleep

            sleeper = sleep
        self._sdk_client, self._sleeper = sdk_client, sleeper

    def fetch_page(self, request: CoinbaseCandleRequest) -> Mapping[str, object]:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._sdk_client.get_public_candles(
                    request.product_id.value,
                    unix_seconds_text(request.request_start),
                    unix_seconds_text(request.request_end),
                    "ONE_MINUTE",
                    request.limit,
                )
                return _response_mapping(response)
            except Exception as error:
                if not _transient(error) or attempt == MAX_ATTEMPTS - 1:
                    raise HistoricalCandleRequestError(
                        "Coinbase public candle request failed"
                    ) from error
                self._sleeper(_BACKOFF_SECONDS[attempt])
        raise AssertionError("unreachable retry state")


def _response_mapping(response: object) -> Mapping[str, object]:
    try:
        to_dict = getattr(response, "to_dict", None)
        value = to_dict() if callable(to_dict) else response
    except Exception as error:
        raise HistoricalCandleRequestError("Coinbase SDK response conversion failed") from error
    if not isinstance(value, Mapping):
        raise HistoricalCandleRequestError("Coinbase SDK response must be a mapping")
    return cast(Mapping[str, object], value)


def _transient(error: Exception) -> bool:
    if isinstance(error, (Timeout, RequestsConnectionError)):
        return True
    if isinstance(error, HTTPError):
        response = error.response
        return response is not None and (
            response.status_code == 429 or 500 <= response.status_code <= 599
        )
    return False
