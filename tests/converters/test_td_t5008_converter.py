"""Tests for the TD T5008 PDF converter."""

import json
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock

from capgains.converters.td_t5008_pdf import (
    parse_t5008_pdf,
    convert_t5008_to_transactions,
    convert_td_t5008_file,
    DEFAULT_SECURITY_TICKERS,
)

SAMPLE_TICKER_MAP = {
    'SAMPLE CURRENCY ETF': 'SCE',
    'SAMPLE EQUITY FUND': 'SEF',
}

SAMPLE_T5008_TEXT_PAGE1 = """2023 O 1 123456789
MR JANE DOE
SAMPLE BROKERAGE INC.
PAGE 1 / 2"""

SAMPLE_T5008_TEXT_PAGE2 = """2023
PAGE 2 / 2
MR JANE DOE 123456789 CAD
300.0000 TOTAL 4,530.00 4,600.00
0315 PTI 100.0000 SAMPLE CURRENCY ETF XTEST00001 1,510.00 1,540.00
0315 PTI 200.0000 SAMPLE CURRENCY ETF XTEST00001 3,020.00 3,060.00
200.0000 TOTAL 5,520.00 5,415.00
0918 PTI 150.0000 SAMPLE EQUITY FUND XTEST00002 4,440.00 4,350.00
0918 PTI 50.0000 SAMPLE EQUITY FUND XTEST00002 1,080.00 1,065.00"""


def _make_mock_pdf(pages_text):
    """Create a mock pdfplumber PDF with the given page texts."""
    mock_pdf = MagicMock()
    mock_pages = []
    for text in pages_text:
        page = MagicMock()
        page.extract_text.return_value = text
        mock_pages.append(page)
    mock_pdf.pages = mock_pages
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


class TestParseT5008Pdf:

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_parses_all_entries(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        assert len(entries) == 4

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_extracts_year(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        for entry in entries:
            assert entry['date'].year == 2023

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_extracts_dates(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        dates = sorted(set(e['date'] for e in entries))
        assert date(2023, 3, 15) in dates
        assert date(2023, 9, 18) in dates

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_extracts_amounts(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        mar_100 = [
            e for e in entries
            if e['date'] == date(2023, 3, 15)
            and e['qty'] == Decimal('100')
        ]
        assert len(mar_100) == 1
        assert mar_100[0]['cost'] == Decimal('1510.00')
        assert mar_100[0]['proceeds'] == Decimal('1540.00')

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_extracts_security_names(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        names = set(e['security_name'] for e in entries)
        assert 'SAMPLE CURRENCY ETF' in names
        assert 'SAMPLE EQUITY FUND' in names

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_extracts_cusip(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        cusips = set(e['cusip'] for e in entries)
        assert 'XTEST00001' in cusips
        assert 'XTEST00002' in cusips

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_skips_total_lines(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        for entry in entries:
            assert 'TOTAL' not in entry['security_name']

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_total_cost_and_proceeds(self, mock_pdfplumber):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        entries = parse_t5008_pdf("dummy.pdf")
        total_cost = sum(e['cost'] for e in entries)
        total_proceeds = sum(e['proceeds'] for e in entries)
        assert total_cost == Decimal('10050.00')
        assert total_proceeds == Decimal('10015.00')

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_empty_pdf_raises(self, mock_pdfplumber):
        page = MagicMock()
        page.extract_text.return_value = ""
        mock_pdf = MagicMock()
        mock_pdf.pages = [page]
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf
        with pytest.raises(Exception, match="Could not extract tax year"):
            parse_t5008_pdf("dummy.pdf")


class TestConvertT5008ToTransactions:

    def _sample_entries(self):
        return [
            {
                'date': date(2023, 3, 15),
                'qty': Decimal('100'),
                'security_name': 'SAMPLE CURRENCY ETF',
                'cusip': 'XTEST00001',
                'cost': Decimal('1510.00'),
                'proceeds': Decimal('1540.00'),
            },
            {
                'date': date(2023, 3, 15),
                'qty': Decimal('200'),
                'security_name': 'SAMPLE CURRENCY ETF',
                'cusip': 'XTEST00001',
                'cost': Decimal('3020.00'),
                'proceeds': Decimal('3060.00'),
            },
        ]

    def test_produces_buy_sell_pairs(self):
        txs = convert_t5008_to_transactions(
            self._sample_entries(), ticker_map=SAMPLE_TICKER_MAP
        )
        assert len(txs) == 4
        assert txs[0]['action'] == 'BUY'
        assert txs[1]['action'] == 'SELL'
        assert txs[2]['action'] == 'BUY'
        assert txs[3]['action'] == 'SELL'

    def test_all_cad_currency(self):
        txs = convert_t5008_to_transactions(
            self._sample_entries(), ticker_map=SAMPLE_TICKER_MAP
        )
        for tx in txs:
            assert tx['currency'] == 'CAD'

    def test_ticker_mapping(self):
        txs = convert_t5008_to_transactions(
            self._sample_entries(), ticker_map=SAMPLE_TICKER_MAP
        )
        for tx in txs:
            assert tx['ticker'] == 'SCE'

    def test_default_ticker_map_has_entries(self):
        assert len(DEFAULT_SECURITY_TICKERS) > 0
        for name, ticker in DEFAULT_SECURITY_TICKERS.items():
            assert isinstance(name, str)
            assert isinstance(ticker, str)

    def test_custom_ticker_map(self):
        custom = {'SAMPLE CURRENCY ETF': 'CUSTOM'}
        txs = convert_t5008_to_transactions(
            self._sample_entries(), ticker_map=custom
        )
        for tx in txs:
            assert tx['ticker'] == 'CUSTOM'

    def test_unknown_security_raises(self):
        entries = [{
            'date': date(2023, 1, 1),
            'qty': Decimal('100'),
            'security_name': 'UNKNOWN SECURITY',
            'cusip': 'XTEST99999',
            'cost': Decimal('1000'),
            'proceeds': Decimal('1100'),
        }]
        with pytest.raises(Exception, match="Unknown security"):
            convert_t5008_to_transactions(entries)

    def test_gain_matches_t5008(self):
        entries = self._sample_entries()
        txs = convert_t5008_to_transactions(
            entries, ticker_map=SAMPLE_TICKER_MAP
        )

        for i in range(0, len(txs), 2):
            buy = txs[i]
            sell = txs[i + 1]
            acb = buy['qty'] * buy['price']
            proceeds = sell['qty'] * sell['price']
            gain = proceeds - acb
            entry = entries[i // 2]
            expected_gain = float(entry['proceeds'] - entry['cost'])
            assert abs(gain - expected_gain) < 0.01

    def test_chronological_order(self):
        entries = [
            {
                'date': date(2023, 9, 18),
                'qty': Decimal('150'),
                'security_name': 'SAMPLE EQUITY FUND',
                'cusip': 'XTEST00002',
                'cost': Decimal('4440.00'),
                'proceeds': Decimal('4350.00'),
            },
            {
                'date': date(2023, 3, 15),
                'qty': Decimal('100'),
                'security_name': 'SAMPLE CURRENCY ETF',
                'cusip': 'XTEST00001',
                'cost': Decimal('1510.00'),
                'proceeds': Decimal('1540.00'),
            },
        ]
        txs = convert_t5008_to_transactions(
            entries, ticker_map=SAMPLE_TICKER_MAP
        )
        assert txs[0]['date'] == '2023-03-15'
        assert txs[-1]['date'] == '2023-09-18'


class TestConvertTdT5008File:

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_writes_output_file(self, mock_pdfplumber, tmp_path):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        output = str(tmp_path / "output.json")
        convert_td_t5008_file(
            "dummy.pdf", output, ticker_map=SAMPLE_TICKER_MAP
        )

        with open(output) as f:
            data = json.load(f)
        assert len(data) == 8
        actions = [tx['action'] for tx in data]
        assert actions.count('BUY') == 4
        assert actions.count('SELL') == 4

    @patch('capgains.converters.td_t5008_pdf.pdfplumber')
    def test_total_gain(self, mock_pdfplumber, tmp_path):
        mock_pdfplumber.open.return_value = _make_mock_pdf(
            [SAMPLE_T5008_TEXT_PAGE1, SAMPLE_T5008_TEXT_PAGE2]
        )
        output = str(tmp_path / "output.json")
        convert_td_t5008_file(
            "dummy.pdf", output, ticker_map=SAMPLE_TICKER_MAP
        )

        with open(output) as f:
            data = json.load(f)

        total_gain = Decimal(0)
        for i in range(0, len(data), 2):
            buy_total = Decimal(str(data[i]['qty'])) * Decimal(
                str(data[i]['price'])
            )
            sell_total = Decimal(str(data[i + 1]['qty'])) * Decimal(
                str(data[i + 1]['price'])
            )
            total_gain += sell_total - buy_total

        expected = Decimal('10015.00') - Decimal('10050.00')
        assert abs(total_gain - expected) < Decimal('0.01')
