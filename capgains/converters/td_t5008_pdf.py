"""
Converter for TD Direct Investing T5008 tax slips from PDF format.

Parses the T5008 PDF issued by TD and outputs interleaved BUY-SELL
transaction pairs in CAD.  Because both cost and proceeds come straight
from the T5008 (which CRA already has), the resulting capital gains
match the slip exactly -- no Bank-of-Canada exchange-rate conversion
is involved.

This is the preferred converter for filing, since the T5008 figures
are pre-populated in tax software (e.g. ufile) from CRA.  The
statement/confirmation converters remain useful for mid-year estimates
before the T5008 is available (typically February of the following year).
"""

import json
import re
import sys
from datetime import date
from decimal import Decimal

import pdfplumber
from click import ClickException


DEFAULT_SECURITY_TICKERS = {
    "HORIZONS US DOLL CURR ETF": "DLR",
    "GLB X US DOLL CURR-A ETF": "DLR",
}

# T5008 columns are: cost/book value (Box 20), proceeds of disposition (Box 21)
_TX_LINE_RE = re.compile(
    r'^\s*(\d{4})\s+'          # MMDD settlement date
    r'\w+\s+'                  # transaction type (PTI, etc.)
    r'([\d,]+\.\d{4})\s+'     # qty (4 decimal places)
    r'(.+?)\s+'               # security name (non-greedy)
    r'([A-Z0-9]{6,12})\s+'    # CUSIP
    r'([\d,]+\.\d{2})\s+'     # cost  (Box 20)
    r'([\d,]+\.\d{2})\s*$'    # proceeds (Box 21)
)


def parse_t5008_pdf(pdf_path):
    """Parse a TD T5008 PDF and extract transaction entries.

    Returns:
        list of dicts with keys: date, qty, security_name, cusip,
        cost, proceeds
    """
    entries = []
    year = None

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue

                for line in text.split('\n'):
                    line = line.strip()

                    if not year:
                        year_match = re.match(r'^(\d{4})\b', line)
                        if year_match:
                            candidate = int(year_match.group(1))
                            if 2000 <= candidate <= 2099:
                                year = candidate

                    match = _TX_LINE_RE.match(line)
                    if not match:
                        continue

                    mmdd = match.group(1)
                    qty = Decimal(match.group(2).replace(',', ''))
                    security_name = match.group(3).strip()
                    cusip = match.group(4)
                    cost = Decimal(match.group(5).replace(',', ''))
                    proceeds = Decimal(match.group(6).replace(',', ''))

                    month = int(mmdd[:2])
                    day = int(mmdd[2:])
                    entry_date = date(year, month, day)

                    entries.append({
                        'date': entry_date,
                        'qty': qty,
                        'security_name': security_name,
                        'cusip': cusip,
                        'cost': cost,
                        'proceeds': proceeds,
                    })

    except Exception as e:
        raise ClickException(f"Error reading T5008 PDF: {e}")

    if not year:
        raise ClickException(
            "Could not extract tax year from T5008 PDF"
        )
    if not entries:
        raise ClickException(
            "No transaction entries found in T5008 PDF"
        )

    return entries


def convert_t5008_to_transactions(entries, ticker_map=None):
    """Convert T5008 entries to interleaved BUY-SELL transaction pairs.

    Each T5008 entry becomes a BUY (at the T5008 cost) immediately
    followed by a SELL (at the T5008 proceeds), both denominated in
    CAD so no exchange-rate lookup is needed.  Because each BUY is
    sold before the next BUY, ACB pooling does not mix lots.
    """
    if ticker_map is None:
        ticker_map = DEFAULT_SECURITY_TICKERS

    transactions = []
    sorted_entries = sorted(entries, key=lambda e: e['date'])

    for entry in sorted_entries:
        ticker = ticker_map.get(entry['security_name'])
        if not ticker:
            raise ClickException(
                f"Unknown security: '{entry['security_name']}' "
                f"(CUSIP: {entry['cusip']}). "
                f"Use --ticker-map to provide a mapping."
            )

        date_str = entry['date'].isoformat()
        qty = entry['qty']
        cost_per_share = entry['cost'] / qty
        proceeds_per_share = entry['proceeds'] / qty

        transactions.append({
            'date': date_str,
            'description': f"T5008 - {entry['security_name']}",
            'ticker': ticker,
            'action': 'BUY',
            'qty': float(qty),
            'price': float(cost_per_share),
            'commission': 0,
            'currency': 'CAD',
        })
        transactions.append({
            'date': date_str,
            'description': f"T5008 - {entry['security_name']}",
            'ticker': ticker,
            'action': 'SELL',
            'qty': float(qty),
            'price': float(proceeds_per_share),
            'commission': 0,
            'currency': 'CAD',
        })

    return transactions


def convert_td_t5008_file(input_file, output_file, ticker_map=None):
    """Convert a TD T5008 PDF to cad-capital-gains transaction format."""
    entries = parse_t5008_pdf(input_file)
    transactions = convert_t5008_to_transactions(entries, ticker_map)

    with open(output_file, 'w') as f:
        json.dump(transactions, f, indent=2)

    n = len(entries)
    print(
        f"Converted {n} T5008 entries to {len(transactions)} transactions",
        file=sys.stderr,
    )
