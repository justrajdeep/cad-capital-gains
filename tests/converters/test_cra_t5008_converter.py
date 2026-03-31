"""Tests for the CRA AllSlips T5008 PDF converter."""

import json
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock

from capgains.converters.cra_t5008_pdf import (
    parse_cra_t5008_pdf,
    convert_cra_t5008_file,
)
from capgains.converters.td_t5008_pdf import convert_t5008_to_transactions

SAMPLE_TICKER_MAP = {
    'SAMPLE CURRENCY ETF': 'SCE',
    'SAMPLE EQUITY FUND': 'SEF',
}

SAMPLE_CRA_TEXT = """Canada Revenue Agency
List of all slips for tax year 2023
T4 Statement of remuneration paid
2023 T4 slip (original) from ACME CORP
Box number Box name Box value
14 Employment income 100,000.00
Tax information slips - My Account Page 1 of 3

T5008 Statement of Securities Transactions
2023 T5008 slip (original) from SAMPLE BROKERAGE INC.
Box number Box name Box value
11 Recipient type Individual
13 Foreign currency CAD
15 Type code of securities PTI
16 Quantity of securities 100.00
17 Identification of securities SAMPLE CURRENCY ETF
18 ISIN/CUSIP number XTEST00001
19 Face amount
20 Cost or book value 1,510.00
21 Proceeds of disposition or settlement amount 1,540.00
22 Type code of securities received on settlement
23 Quantity of securities received on settlement
2023 T5008 slip (original) from SAMPLE BROKERAGE INC.
Box number Box name Box value
11 Recipient type Individual
13 Foreign currency CAD
15 Type code of securities PTI
16 Quantity of securities 150.00
17 Identification of securities SAMPLE EQUITY FUND
18 ISIN/CUSIP number XTEST00002
19 Face amount
20 Cost or book value 4,440.00
21 Proceeds of disposition or settlement amount 4,350.00
22 Type code of securities received on settlement
23 Quantity of securities received on settlement
Tax information slips - My Account Page 2 of 3
"""


def _make_mock_pdf(text):
    """Create a mock pdfplumber PDF with a single page of text."""
    mock_pdf = MagicMock()
    page = MagicMock()
    page.extract_text.return_value = text
    mock_pdf.pages = [page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


class TestParseCraT5008Pdf:

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_parses_all_entries(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        assert len(entries) == 2

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_extracts_year(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        for entry in entries:
            assert entry['date'] == date(2023, 1, 1)

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_extracts_amounts(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        currency_etf = [
            e for e in entries
            if e['security_name'] == 'SAMPLE CURRENCY ETF'
        ]
        assert len(currency_etf) == 1
        assert currency_etf[0]['qty'] == Decimal('100.00')
        assert currency_etf[0]['cost'] == Decimal('1510.00')
        assert currency_etf[0]['proceeds'] == Decimal('1540.00')

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_extracts_security_names(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        names = set(e['security_name'] for e in entries)
        assert 'SAMPLE CURRENCY ETF' in names
        assert 'SAMPLE EQUITY FUND' in names

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_extracts_cusip(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        cusips = set(e['cusip'] for e in entries)
        assert 'XTEST00001' in cusips
        assert 'XTEST00002' in cusips

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_ignores_non_t5008_slips(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        for entry in entries:
            assert entry['security_name'] != 'ACME CORP'

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_no_year_raises(self, mock_pdfplumber):
        text = "Some random text with no year header"
        mock_pdfplumber.open.return_value = _make_mock_pdf(text)
        with pytest.raises(Exception, match="Could not extract tax year"):
            parse_cra_t5008_pdf("dummy.pdf")

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_no_t5008_slips_raises(self, mock_pdfplumber):
        text = "List of all slips for tax year 2023\nNo T5008 here"
        mock_pdfplumber.open.return_value = _make_mock_pdf(text)
        with pytest.raises(Exception, match="No T5008 slips found"):
            parse_cra_t5008_pdf("dummy.pdf")


class TestCraT5008Integration:
    """Test that CRA-parsed entries work with the shared conversion logic."""

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_gain_matches_slip(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        entries = parse_cra_t5008_pdf("dummy.pdf")
        txs = convert_t5008_to_transactions(
            entries, ticker_map=SAMPLE_TICKER_MAP
        )

        total_gain = Decimal(0)
        for i in range(0, len(txs), 2):
            buy_total = Decimal(str(txs[i]['qty'])) * Decimal(
                str(txs[i]['price'])
            )
            sell_total = Decimal(str(txs[i + 1]['qty'])) * Decimal(
                str(txs[i + 1]['price'])
            )
            total_gain += sell_total - buy_total

        expected = sum(
            e['proceeds'] - e['cost'] for e in entries
        )
        assert abs(total_gain - expected) < Decimal('0.01')

    @patch('capgains.converters.cra_t5008_pdf.pdfplumber')
    def test_writes_output_file(self, mock_pdfplumber, tmp_path):
        mock_pdfplumber.open.return_value = _make_mock_pdf(SAMPLE_CRA_TEXT)
        output = str(tmp_path / "output.json")
        convert_cra_t5008_file(
            "dummy.pdf", output, ticker_map=SAMPLE_TICKER_MAP
        )

        with open(output) as f:
            data = json.load(f)
        assert len(data) == 4
        actions = [tx['action'] for tx in data]
        assert actions.count('BUY') == 2
        assert actions.count('SELL') == 2
        for tx in data:
            assert tx['currency'] == 'CAD'
