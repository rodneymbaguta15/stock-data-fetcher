"""Tests for fetch_quotes.py

Run with:
    pip install pytest
    pytest test_fetch_quotes.py -v

No network calls are made. fetch_quote() takes a `session` argument, so the
tests hand it a fake session that returns a canned payload instead of a real
requests.Session that would hit Finnhub.
"""

import csv

import pytest
import requests

from fetch_quotes import FIELDNAMES, append_rows, fetch_quote, parse_symbols

# A realistic Finnhub /quote response.
SAMPLE_PAYLOAD = {
    "c": 228.52,
    "d": 1.21,
    "dp": 0.5325,
    "h": 229.10,
    "l": 226.80,
    "o": 227.05,
    "pc": 227.31,
    "t": 1757433600,
}


class FakeResponse:
    """Stands in for a requests.Response object."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


class FakeSession:
    """Stands in for a requests.Session, and records how it was called."""

    def __init__(self, payload, status_code=200):
        self._response = FakeResponse(payload, status_code)
        self.last_url = None
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_url = url
        self.last_params = params
        return self._response


# --- parse_symbols ---------------------------------------------------------


def test_parse_symbols_splits_on_spaces():
    assert parse_symbols("AAPL MSFT NVDA") == ["AAPL", "MSFT", "NVDA"]


def test_parse_symbols_splits_on_commas():
    assert parse_symbols("AAPL,MSFT,NVDA") == ["AAPL", "MSFT", "NVDA"]


def test_parse_symbols_handles_messy_input():
    assert parse_symbols("  aapl,  msft   nvda ") == ["AAPL", "MSFT", "NVDA"]


def test_parse_symbols_removes_duplicates_keeping_order():
    assert parse_symbols("MSFT AAPL msft") == ["MSFT", "AAPL"]


def test_parse_symbols_returns_empty_list_for_blank_input():
    assert parse_symbols("   ") == []


# --- fetch_quote -----------------------------------------------------------


def test_fetch_quote_maps_fields():
    session = FakeSession(SAMPLE_PAYLOAD)

    quote = fetch_quote(session, "AAPL", "fake_key")

    assert quote["symbol"] == "AAPL"
    assert quote["current"] == 228.52
    assert quote["open"] == 227.05
    assert quote["high"] == 229.10
    assert quote["low"] == 226.80
    assert quote["previous_close"] == 227.31


def test_fetch_quote_returns_every_column():
    """Guards against a field being added to FIELDNAMES but not to the dict,
    which would make DictWriter raise at write time instead of here."""
    session = FakeSession(SAMPLE_PAYLOAD)

    quote = fetch_quote(session, "AAPL", "fake_key")

    assert set(quote.keys()) == set(FIELDNAMES)


def test_fetch_quote_sends_symbol_and_token():
    session = FakeSession(SAMPLE_PAYLOAD)

    fetch_quote(session, "MSFT", "fake_key")

    assert session.last_params == {"symbol": "MSFT", "token": "fake_key"}


def test_fetch_quote_converts_timestamp_to_iso():
    session = FakeSession(SAMPLE_PAYLOAD)

    quote = fetch_quote(session, "AAPL", "fake_key")

    # 1757433600 is 2025-09-09 00:00:00 UTC.
    assert quote["quote_time"].startswith("2025-09-09")


def test_fetch_quote_returns_none_for_unknown_symbol():
    """Finnhub returns 200 with zeroed fields, not a 404."""
    empty = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
    session = FakeSession(empty)

    assert fetch_quote(session, "ZZZZQQ", "fake_key") is None


def test_fetch_quote_raises_on_http_error():
    session = FakeSession({}, status_code=429)

    with pytest.raises(requests.HTTPError):
        fetch_quote(session, "AAPL", "fake_key")


def test_fetch_quote_handles_missing_timestamp():
    payload = dict(SAMPLE_PAYLOAD)
    del payload["t"]
    session = FakeSession(payload)

    quote = fetch_quote(session, "AAPL", "fake_key")

    assert quote["quote_time"] == ""


# --- append_rows -----------------------------------------------------------
# tmp_path is a built-in pytest fixture: a fresh empty directory per test.


def test_append_rows_writes_header_to_new_file(tmp_path):
    path = tmp_path / "quotes.csv"
    row = fetch_quote(FakeSession(SAMPLE_PAYLOAD), "AAPL", "fake_key")

    append_rows(path, [row])

    with open(path, newline="", encoding="utf-8") as handle:
        lines = list(csv.reader(handle))

    assert lines[0] == FIELDNAMES
    assert len(lines) == 2


def test_append_rows_writes_header_only_once(tmp_path):
    path = tmp_path / "quotes.csv"
    row = fetch_quote(FakeSession(SAMPLE_PAYLOAD), "AAPL", "fake_key")

    append_rows(path, [row])
    append_rows(path, [row])

    with open(path, newline="", encoding="utf-8") as handle:
        lines = list(csv.reader(handle))

    assert len(lines) == 3  # one header, two data rows
    assert lines[1] == lines[2]


def test_append_rows_writes_all_rows(tmp_path):
    path = tmp_path / "quotes.csv"
    session = FakeSession(SAMPLE_PAYLOAD)
    rows = [fetch_quote(session, sym, "fake_key") for sym in ("AAPL", "MSFT", "NVDA")]

    append_rows(path, rows)

    with open(path, newline="", encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))

    assert [r["symbol"] for r in records] == ["AAPL", "MSFT", "NVDA"]