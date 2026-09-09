"""Pull stock quotes from Finnhub and append them to a CSV file.

Usage:
    python fetch_quotes.py --out data/quotes.csv     # prompts for symbols

Reads FINNHUB_API_KEY from a .env file in the project root, or from the
environment. Each run appends one row per symbol, so running it on a schedule
builds up a time series you can load into pandas or Excel later.
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# Reads .env into the environment. Real environment variables still win.
load_dotenv()

BASE_URL = "https://finnhub.io/api/v1/quote"

# The free tier allows 60 calls/minute. One second between calls keeps us
# comfortably under that even with a long symbol list.
SECONDS_BETWEEN_CALLS = 1.0

# Column order for the CSV. Finnhub's quote endpoint uses single-letter keys,
# so we rename them into something readable.
FIELDNAMES = [
    "fetched_at",
    "symbol",
    "current",
    "open",
    "high",
    "low",
    "previous_close",
    "change",
    "percent_change",
    "quote_time",
]


def parse_symbols(raw):
    """Turn a free-text string into a clean, de-duplicated list of tickers.

    Accepts commas, spaces, or both: "aapl, msft  nvda" -> ["AAPL", "MSFT", "NVDA"]
    """
    # Treat commas as spaces, then split() handles any run of whitespace.
    tokens = raw.replace(",", " ").split()
    symbols = [token.upper() for token in tokens]

    # dict keys are unique and keep insertion order, so this drops duplicates
    # without shuffling the list the way set() would.
    return list(dict.fromkeys(symbols))


def prompt_for_symbols():
    """Ask the user for tickers, re-asking until we get at least one."""
    while True:
        raw = input("Enter ticker symbols (space or comma separated): ")
        symbols = parse_symbols(raw)
        if symbols:
            return symbols
        print("  please enter at least one symbol, or press Ctrl-C to quit")


def fetch_quote(session, symbol, api_key):
    """Fetch one quote and return it as a dict matching FIELDNAMES.

    Returns None if the symbol is unknown or the request fails.
    """
    response = session.get(
        BASE_URL,
        params={"symbol": symbol, "token": api_key},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    # Finnhub returns zeros rather than a 404 for symbols it doesn't cover.
    if not data.get("c"):
        print(f"  no data for {symbol} (unknown symbol or not on free tier)")
        return None

    quote_time = data.get("t")
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": symbol,
        "current": data.get("c"),
        "open": data.get("o"),
        "high": data.get("h"),
        "low": data.get("l"),
        "previous_close": data.get("pc"),
        "change": data.get("d"),
        "percent_change": data.get("dp"),
        "quote_time": (
            datetime.fromtimestamp(quote_time, timezone.utc).isoformat(timespec="seconds")
            if quote_time
            else ""
        ),
    }


def append_rows(path, rows):
    """Append rows to the CSV, writing the header only if the file is new."""
    file_is_new = not path.exists()

    # Create the parent directory if it doesn't exist yet. open() won't do this.
    path.parent.mkdir(parents=True, exist_ok=True)

    # newline="" is required so the csv module controls line endings.
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if file_is_new:
            writer.writeheader()
        writer.writerows(rows)


def fetch_all(symbols, api_key):
    """Fetch every symbol, skipping any that fail. Returns a list of rows."""
    rows = []

    # A Session reuses the underlying TCP connection across requests.
    with requests.Session() as session:
        for index, symbol in enumerate(symbols):
            print(f"Fetching {symbol}...")

            try:
                quote = fetch_quote(session, symbol, api_key)
            except requests.HTTPError as error:
                print(f"  HTTP error for {symbol}: {error}")
                continue
            except requests.RequestException as error:
                print(f"  request failed for {symbol}: {error}")
                continue

            if quote:
                rows.append(quote)

            # Don't sleep after the final symbol.
            if index < len(symbols) - 1:
                time.sleep(SECONDS_BETWEEN_CALLS)

    return rows


def main():
    parser = argparse.ArgumentParser(description="Fetch stock quotes into a CSV.")
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Ticker symbols, e.g. AAPL MSFT. If omitted, you'll be prompted.",
    )
    parser.add_argument(
        "--out",
        default="quotes.csv",
        type=Path,
        help="Output CSV path (default: quotes.csv)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        sys.exit("FINNHUB_API_KEY is not set. Add it to .env and try again.")

    # Command-line symbols win; prompt only when none were given.
    symbols = parse_symbols(" ".join(args.symbols)) if args.symbols else prompt_for_symbols()

    rows = fetch_all(symbols, api_key)

    if not rows:
        print("Nothing written.")
        return

    append_rows(args.out, rows)
    print(f"Wrote {len(rows)} row(s) to {args.out}")


if __name__ == "__main__":
    main()