"""
Converter for T5008 tax slips from CRA's "All Slips" PDF.

Parses the PDF downloaded from CRA My Account (Tax information slips ->
All slips) and extracts T5008 entries.  The conversion to BUY-SELL
transaction pairs is handled by the shared convert_t5008_to_transactions
function from td_t5008_pdf.

The CRA PDF uses a structured "Box number / Box name / Box value"
layout -- one block per slip -- rather than the tabular format that TD
uses.  Importantly, the CRA version has NO settlement dates, so all
transactions are assigned to Jan 1 of the tax year.  This is fine
because each BUY-SELL pair is self-contained (no ACB pooling across
entries).

This converter is primarily useful for cross-verifying CRA data against
the TD T5008 converter to make sure both sources agree.
"""

import json
import re
import sys
from datetime import date
from decimal import Decimal

import pdfplumber
from click import ClickException

from .td_t5008_pdf import convert_t5008_to_transactions

_SLIP_HEADER_RE = re.compile(
    r'(\d{4}) T5008 slip \((?:original|amended)\) from (.+)'
)
_QTY_RE = re.compile(
    r'^16 Quantity of securities ([\d,]+\.\d+)', re.MULTILINE
)
_SECURITY_RE = re.compile(
    r'^17 Identification of securities (.+)', re.MULTILINE
)
_CUSIP_RE = re.compile(
    r'^18 ISIN/CUSIP number (\S+)', re.MULTILINE
)
_COST_RE = re.compile(
    r'^20 Cost or book value ([\d,]+\.\d+)', re.MULTILINE
)
_PROCEEDS_RE = re.compile(
    r'^21 Proceeds of disposition or settlement amount ([\d,]+\.\d+)',
    re.MULTILINE
)


def parse_cra_t5008_pdf(pdf_path):
    """Parse a CRA AllSlips PDF and extract T5008 entries.

    Returns:
        list of dicts with keys: date, qty, security_name, cusip,
        cost, proceeds  (same shape as td_t5008_pdf.parse_t5008_pdf)
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n".join(
                page.extract_text() or ""
                for page in pdf.pages
            )
    except Exception as e:
        raise ClickException(f"Error reading CRA PDF: {e}")

    if not full_text.strip():
        raise ClickException("Could not extract text from CRA PDF")

    year_match = re.search(
        r'List of all slips for tax year (\d{4})', full_text
    )
    if year_match:
        year = int(year_match.group(1))
    else:
        raise ClickException(
            "Could not extract tax year from CRA PDF"
        )

    headers = list(_SLIP_HEADER_RE.finditer(full_text))
    if not headers:
        raise ClickException("No T5008 slips found in CRA PDF")

    entries = []
    for i, header in enumerate(headers):
        start = header.end()
        next_start = headers[i + 1].start() if i + 1 < len(headers) else None
        end = next_start if next_start is not None else len(full_text)
        block = full_text[start:end]

        qty_m = _QTY_RE.search(block)
        sec_m = _SECURITY_RE.search(block)
        cusip_m = _CUSIP_RE.search(block)
        cost_m = _COST_RE.search(block)
        proceeds_m = _PROCEEDS_RE.search(block)

        if not all([qty_m, sec_m, cost_m, proceeds_m]):
            continue

        entries.append({
            'date': date(year, 1, 1),
            'qty': Decimal(qty_m.group(1).replace(',', '')),
            'security_name': sec_m.group(1).strip(),
            'cusip': cusip_m.group(1) if cusip_m else '',
            'cost': Decimal(cost_m.group(1).replace(',', '')),
            'proceeds': Decimal(proceeds_m.group(1).replace(',', '')),
        })

    if not entries:
        raise ClickException(
            "No T5008 entries found in CRA PDF"
        )

    return entries


def convert_cra_t5008_file(input_file, output_file, ticker_map=None):
    """Convert a CRA AllSlips PDF (T5008 entries) to capgains format."""
    entries = parse_cra_t5008_pdf(input_file)
    transactions = convert_t5008_to_transactions(entries, ticker_map)

    with open(output_file, 'w') as f:
        json.dump(transactions, f, indent=2)

    n = len(entries)
    print(
        f"Converted {n} CRA T5008 entries to "
        f"{len(transactions)} transactions",
        file=sys.stderr,
    )
