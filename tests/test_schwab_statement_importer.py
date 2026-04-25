"""Tests for Schwab PDF -> ACB CSV importer (no PyMuPDF required)."""
from decimal import Decimal

from capgains.schwab_statement_importer import (
    AcbRow,
    _bucket_line,
    _lines_from_words,
    _parse_money,
    _parse_trade_date,
    extract_acb_rows_from_page,
    write_acb_csv,
)


def _w(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text, 0, 0, 0)


def test_parse_trade_date():
    assert _parse_trade_date("06/15/22") == _parse_trade_date("6/15/22")
    d = _parse_trade_date("06/15/2022")
    assert d.year == 2022 and d.month == 6 and d.day == 15


def test_parse_money():
    assert _parse_money("$1,234.50") == Decimal("1234.50")
    assert _parse_money("--") is None
    assert _parse_money("") is None


def test_lines_from_words_and_bucket():
    words = [
        _w(60, 100, 80, 112, "06/01/22"),
        _w(120, 100, 160, 112, "ESPP"),
        _w(200, 100, 260, 112, "PURCHASE"),
        _w(360, 100, 400, 112, "$10.00"),
        _w(580, 100, 620, 112, "5"),
    ]
    lines = _lines_from_words(words)
    assert len(lines) == 1
    cols = _bucket_line(lines[0])
    assert cols[0] == "06/01/22"
    assert "ESPP" in cols[1]
    assert "PURCHASE" in cols[2]


def test_extract_acb_rows_from_page_synthetic_buy():
    class FakePage:
        def get_text(self, mode=None):
            if mode == "words":
                return [
                    _w(36, 124, 68, 140, "Stock"),
                    _w(205, 124, 239, 140, "NVDA"),
                    _w(711, 162, 756, 176, "Proceeds"),
                    _w(36, 228, 68, 244, "Cash"),
                    _w(69, 228, 136, 244, "Transaction"),
                    _w(140, 228, 200, 244, "Summary"),
                    _w(60, 190, 90, 204, "06/01/22"),
                    _w(120, 190, 160, 204, "ESPP"),
                    _w(200, 190, 280, 204, "PURCHASE"),
                    _w(360, 190, 400, 204, "$10.00"),
                    _w(580, 190, 620, 204, "5"),
                ]
            return (
                "Page 3\n"
                "Stock Transaction Summary: NVDA\n"
                "Cash Transaction Summary\n"
            )

    rows = extract_acb_rows_from_page(FakePage(), "USD")
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, AcbRow)
    assert r.ticker == "NVDA"
    assert r.action == "BUY"
    assert r.qty == Decimal(5)
    assert r.price == Decimal("10.00")
    assert r.currency == "USD"


def test_extract_acb_rows_from_page_synthetic_sell():
    class FakePage:
        def get_text(self, mode=None):
            if mode == "words":
                return [
                    _w(36, 124, 68, 140, "Stock"),
                    _w(205, 124, 239, 140, "NVDA"),
                    _w(711, 162, 756, 176, "Proceeds"),
                    _w(36, 228, 68, 244, "Cash"),
                    _w(69, 228, 136, 244, "Transaction"),
                    _w(140, 228, 200, 244, "Summary"),
                    _w(60, 190, 90, 204, "06/10/22"),
                    _w(120, 190, 160, 204, "SALE"),
                    _w(200, 190, 260, 204, "SOLD"),
                    _w(580, 190, 620, 204, "2"),
                    _w(670, 190, 710, 204, "$50.00"),
                    _w(720, 190, 780, 204, "$99.00"),
                ]
            return (
                "Page 3\n"
                "Stock Transaction Summary: NVDA\n"
                "Cash Transaction Summary\n"
            )

    rows = extract_acb_rows_from_page(FakePage(), "USD")
    assert len(rows) == 1
    r = rows[0]
    assert r.action == "SELL"
    assert r.qty == Decimal(2)
    assert r.price == Decimal("50.00")


def test_write_acb_csv(tmp_path):
    p = tmp_path / "out.csv"
    rows = [
        AcbRow(
            trade_date=_parse_trade_date("1/2/2022"),
            description="ESPP PURCHASE",
            ticker="NVDA",
            action="BUY",
            qty=Decimal(1),
            price=Decimal("10"),
            commission=Decimal(0),
            currency="USD",
        )
    ]
    write_acb_csv(rows, p, with_header=True)
    txt = p.read_text(encoding="utf-8")
    assert "date,description" in txt
    assert "NVDA" in txt
