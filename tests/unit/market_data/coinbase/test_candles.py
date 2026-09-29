from datetime import UTC, datetime, timedelta

import pytest
from requests import Request, Response, Session
from requests.exceptions import ConnectionError, HTTPError, Timeout

from command_station.domain import ProductId, UtcTimestamp
from command_station.market_data.coinbase.candles import CoinbasePublicCandleClient
from command_station.market_data.historical import (
    CoinbaseCandleRequest,
    HistoricalCandleRequestError,
)


class FakeSdk:
    def __init__(self, results: list[object], *, authenticated: bool = False) -> None:
        self.results = results
        self.is_authenticated = authenticated
        self.session = Session()
        self.calls: list[tuple[str, str, str, str, int]] = []

    def get_public_candles(
        self, product_id: str, start: str, end: str, granularity: str, limit: int
    ) -> object:
        self.calls.append((product_id, start, end, granularity, limit))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def request() -> CoinbaseCandleRequest:
    start = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    return CoinbaseCandleRequest(
        ProductId("BTC-USD"), start, UtcTimestamp(start.value + timedelta(minutes=1)), 1
    )


def test_public_candle_client_retries_timeout_with_injected_sleep() -> None:
    sdk = FakeSdk([Timeout(), {"candles": []}])
    delays: list[float] = []
    assert CoinbasePublicCandleClient(sdk, sleeper=delays.append).fetch_page(request()) == {
        "candles": []
    }
    assert delays == [0.1]
    assert sdk.calls[0][3:] == ("ONE_MINUTE", 1)


def test_public_candle_client_does_not_retry_malformed_response() -> None:
    sdk = FakeSdk([object()])
    with pytest.raises(HistoricalCandleRequestError):
        CoinbasePublicCandleClient(sdk, sleeper=lambda _: None).fetch_page(request())
    assert len(sdk.calls) == 1


@pytest.mark.parametrize("error", [Timeout(), ConnectionError(), HTTPError(response=Response())])
def test_public_client_retries_transient_errors(error: Exception) -> None:
    if isinstance(error, HTTPError):
        assert error.response is not None
        error.response.status_code = 500
    sdk = FakeSdk([error, {"candles": []}])
    delays: list[float] = []
    CoinbasePublicCandleClient(sdk, sleeper=delays.append).fetch_page(request())
    assert delays == [0.1] and len(sdk.calls) == 2


def test_public_client_retries_rate_limit_and_caps_attempts() -> None:
    response = Response()
    response.status_code = 429
    delays: list[float] = []
    sdk = FakeSdk([HTTPError(response=response)] * 4)
    with pytest.raises(HistoricalCandleRequestError):
        CoinbasePublicCandleClient(sdk, sleeper=delays.append).fetch_page(request())
    assert delays == [0.1, 0.2, 0.4] and len(sdk.calls) == 4


def test_public_client_does_not_retry_regular_http_error_or_allow_authenticated_sdk() -> None:
    response = Response()
    response.status_code = 400
    sdk = FakeSdk([HTTPError(response=response)])
    with pytest.raises(HistoricalCandleRequestError):
        CoinbasePublicCandleClient(sdk, sleeper=lambda _: None).fetch_page(request())
    assert len(sdk.calls) == 1
    with pytest.raises(HistoricalCandleRequestError, match="unauthenticated"):
        CoinbasePublicCandleClient(FakeSdk([], authenticated=True))


def test_public_client_disables_netrc_authorization_for_injected_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = FakeSdk([])

    def ambient_netrc(_: str, *, raise_errors: bool = False) -> tuple[str, str] | None:
        return ("ambient-user", "ambient-secret")

    monkeypatch.setattr("requests.sessions.get_netrc_auth", ambient_netrc)
    CoinbasePublicCandleClient(sdk)
    prepared = sdk.session.prepare_request(Request("GET", "https://api.coinbase.com/public"))
    assert sdk.session.trust_env is False
    assert "Authorization" not in prepared.headers


def test_public_client_default_sdk_session_disables_ambient_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ambient_netrc(_: str, *, raise_errors: bool = False) -> tuple[str, str] | None:
        return ("ambient-user", "ambient-secret")

    monkeypatch.setattr("requests.sessions.get_netrc_auth", ambient_netrc)
    client = CoinbasePublicCandleClient()
    session = client._sdk_client.session
    prepared = session.prepare_request(Request("GET", "https://api.coinbase.com/public"))
    assert session.trust_env is False
    assert "Authorization" not in prepared.headers


def test_public_client_rejects_injected_client_without_known_session_contract() -> None:
    class UnknownClient:
        is_authenticated = False

        def get_public_candles(self, *args: object) -> object:
            return {"candles": []}

    with pytest.raises(HistoricalCandleRequestError, match="Session"):
        CoinbasePublicCandleClient(UnknownClient())  # type: ignore[arg-type]


@pytest.mark.parametrize("credential", ["auth", "header", "cookie", "params"])
def test_public_client_rejects_injected_explicit_session_credentials(credential: str) -> None:
    sdk = FakeSdk([])
    if credential == "auth":
        sdk.session.auth = ("user", "secret")
    elif credential == "header":
        sdk.session.headers["aUtHoRiZaTiOn"] = "Bearer secret"
    elif credential == "cookie":
        sdk.session.cookies.set("session", "secret", domain="api.coinbase.com")
    else:
        sdk.session.params = {"access_token": "secret"}
    with pytest.raises(HistoricalCandleRequestError, match="rejects"):
        CoinbasePublicCandleClient(sdk)
