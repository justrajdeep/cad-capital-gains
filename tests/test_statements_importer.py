"""Tests for Schwab PDF -> ACB CSV importer (no PyMuPDF required)."""
from decimal import Decimal

from capgains.statements_importer import (
    AcbRow,
    _extract_rows_from_etrade_section,
    _extract_rows_from_text_blocks,
    _infer_split_factor_and_mode,
    _normalize_split_rows,
    _bucket_line,
    _lines_from_words,
    _parse_money,
    _parse_trade_date,
    collect_rows_from_dir,
    extract_acb_rows_from_page,
    load_existing_row_keys,
    mark_duplicate_flags,
    resolve_existing_row_keys,
    row_key_from_acb_row,
    write_acb_csv,
)


def _w(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text, 0, 0, 0)


def test_parse_trade_date():
    assert _parse_trade_date("06/15/22") == _parse_trade_date("6/15/22")
    d = _parse_trade_date("06/15/2022")
    assert d.year == 2022 and d.month == 6 and d.day == 15
    d2 = _parse_trade_date("2024-06-20")
    assert d2.year == 2024 and d2.month == 6 and d2.day == 20


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
                    _w(205, 124, 239, 140, "EXAM"),
                    _w(711, 162, 756, 176, "Proceeds"),
                    _w(36, 228, 68, 244, "Cash"),
                    _w(69, 228, 136, 244, "Transaction"),
                    _w(140, 228, 200, 244, "Summary"),
                    _w(60, 190, 90, 204, "06/01/22"),
                    _w(120, 190, 160, 204, "ESPP"),
                    _w(200, 190, 280, 204, "PURCHASE"),
                    _w(360, 190, 400, 204, "$10.00"),
                    _w(450, 190, 500, 204, "$12.50"),
                    _w(580, 190, 620, 204, "5"),
                ]
            return (
                "Page 3\n"
                "Stock Transaction Summary: EXAM\n"
                "Cash Transaction Summary\n"
            )

    rows = extract_acb_rows_from_page(FakePage(), "USD")
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, AcbRow)
    assert r.ticker == "EXAM"
    assert r.action == "BUY"
    assert r.qty == Decimal(5)
    assert r.price == Decimal("12.50")
    assert r.currency == "USD"
    assert r.source == "Manual"


def test_extract_acb_rows_from_page_synthetic_sell():
    class FakePage:
        def get_text(self, mode=None):
            if mode == "words":
                return [
                    _w(36, 124, 68, 140, "Stock"),
                    _w(205, 124, 239, 140, "EXAM"),
                    _w(711, 162, 756, 176, "Proceeds"),
                    _w(36, 228, 68, 244, "Cash"),
                    _w(69, 228, 136, 244, "Transaction"),
                    _w(140, 228, 200, 244, "Summary"),
                    _w(60, 190, 90, 204, "06/10/22"),
                    _w(120, 190, 160, 204, "SALE"),
                    _w(200, 190, 260, 204, "SOLD"),
                    _w(450, 190, 500, 204, "$49.50"),
                    _w(580, 190, 620, 204, "2"),
                    _w(670, 190, 710, 204, "$50.00"),
                    _w(720, 190, 780, 204, "$99.00"),
                ]
            return (
                "Page 3\n"
                "Stock Transaction Summary: EXAM\n"
                "Cash Transaction Summary\n"
            )

    rows = extract_acb_rows_from_page(FakePage(), "USD")
    assert len(rows) == 1
    r = rows[0]
    assert r.action == "SELL"
    assert r.qty == Decimal(2)
    assert r.price == Decimal("49.50")


def test_write_acb_csv(tmp_path):
    p = tmp_path / "out.csv"
    rows = [
        AcbRow(
            trade_date=_parse_trade_date("1/2/2022"),
            description="ESPP PURCHASE",
            ticker="EXAM",
            action="BUY",
            qty=Decimal(1),
            price=Decimal("10"),
            commission=Decimal(0),
            currency="USD",
        )
    ]
    write_acb_csv([(r, False) for r in rows], p, with_header=True)
    txt = p.read_text(encoding="utf-8")
    assert "date,description" in txt
    assert "source" in txt
    assert "EXAM" in txt
    assert "Manual" in txt


def _sample_row():
    return AcbRow(
        trade_date=_parse_trade_date("1/2/2022"),
        description="ESPP PURCHASE",
        ticker="EXAM",
        action="BUY",
        qty=Decimal(1),
        price=Decimal("10"),
        commission=Decimal(0),
        currency="USD",
    )


def test_mark_duplicate_flags_within_batch():
    a = _sample_row()
    b = _sample_row()
    out = mark_duplicate_flags([a, b], set())
    assert out[0][1] is False
    assert out[1][1] is True


def test_mark_duplicate_flags_against_existing(tmp_path):
    p = tmp_path / "prev.csv"
    r = _sample_row()
    write_acb_csv([(r, False)], p, with_header=True)
    keys = load_existing_row_keys(p)
    assert row_key_from_acb_row(r) in keys
    out = mark_duplicate_flags([_sample_row()], keys)
    assert out[0][1] is True


def test_write_acb_csv_duplicate_prefix(tmp_path):
    p = tmp_path / "out.csv"
    r = _sample_row()
    write_acb_csv([(r, True)], p, with_header=True)
    txt = p.read_text(encoding="utf-8")
    assert "[DUPLICATE]" in txt
    assert "ESPP" in txt


def test_load_existing_strips_duplicate_prefix_for_keys(tmp_path):
    p = tmp_path / "f.csv"
    r = _sample_row()
    write_acb_csv([(r, True)], p, with_header=True)
    keys = load_existing_row_keys(p)
    assert row_key_from_acb_row(r) in keys
    assert len(keys) == 1


def test_resolve_existing_row_keys_force(tmp_path):
    p = tmp_path / "out.csv"
    r = _sample_row()
    write_acb_csv([(r, False)], p, with_header=True)
    assert len(load_existing_row_keys(p)) == 1
    assert resolve_existing_row_keys(p, force=True) == set()
    assert len(resolve_existing_row_keys(p, force=False)) == 1


def test_collect_rows_from_dir_only_account_statement_files(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "Account Statement_2025-12-31.PDF").write_text("x")
    (tmp_path / "Account Statement_2026-03-31.PDF").write_text("x")
    (tmp_path / "Year-end Statement_2025-12-31.PDF").write_text("x")
    (tmp_path / "Restricted Stock Activity_2025-12-10.PDF").write_text("x")

    parsed = []

    def fake_extract(path, _currency):
        parsed.append(path.name)
        return []

    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_pdf",
        fake_extract,
    )
    rows = collect_rows_from_dir(tmp_path, "USD", verbose=False)
    assert rows == []
    assert parsed == [
        "Account Statement_2025-12-31.PDF",
        "Account Statement_2026-03-31.PDF",
    ]


def test_extract_rows_from_text_blocks_vertical_layout():
    text = (
        "Stock Transaction Summary: EXAM\n"
        "Transaction\nDate\nActivity\nDescription\nPurchase/\nVest Date\n"
        "Purchase\nPrice\nAcquisition\nFMV\nSubscription\nFMV\nShares\n"
        "Sale\nPrice\nGross\nProceeds\n"
        "2024-06-20\n18:33:50\nDeposit\nRS 100\n06/19/24\n--\n$135.58\n"
        "$0.00\n181.0000\n--\n--\n"
        "Cash Transaction Summary\n"
    )
    rows = _extract_rows_from_text_blocks(
        text,
        ticker="EXAM",
        default_currency="USD",
        source="Account Statement_2024-06-30.PDF",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.trade_date.isoformat() == "2024-06-20"
    assert row.description == "Deposit RS 100"
    assert row.qty == Decimal("181.0000")
    assert row.price == Decimal("135.58")
    assert row.source == "Account Statement_2024-06-30.PDF"


def test_stock_split_price_is_zero():
    text = (
        "Stock Transaction Summary: EXAM\n"
        "Transaction\nDate\nActivity\nDescription\nPurchase/\nVest Date\n"
        "Purchase\nPrice\nAcquisition\nFMV\nSubscription\nFMV\nShares\n"
        "Sale\nPrice\nGross\nProceeds\n"
        "2024-06-07\n22:03:53\nStock Split\nRS 57039\n06/21/23\n--\n$43.04\n"
        "$0.00\n1,872.0000\n--\n--\n"
        "Cash Transaction Summary\n"
    )
    rows = _extract_rows_from_text_blocks(
        text,
        ticker="EXAM",
        default_currency="USD",
        source="Account Statement_2024-06-30.PDF",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "BUY"
    assert row.price == Decimal("0")


def test_infer_split_factor_added_mode():
    qty = [Decimal("855"), Decimal("810"), Decimal("81"), Decimal("1872")]
    factor, mode = _infer_split_factor_and_mode(qty)
    assert factor == 10
    assert mode == "added"


def test_normalize_split_rows_post_mode_converts_qty():
    # Post-split totals for a 10:1 split should convert to +shares (x9/10).
    rows = [
        AcbRow(
            trade_date=_parse_trade_date("2024-06-07"),
            description="Stock Split EXAM",
            ticker="EXAM",
            action="BUY",
            qty=Decimal("1000"),
            price=Decimal("0"),
            commission=Decimal("0"),
            currency="USD",
            source="a.pdf",
        ),
        AcbRow(
            trade_date=_parse_trade_date("2024-06-07"),
            description="Stock Split EXAM",
            ticker="EXAM",
            action="BUY",
            qty=Decimal("2000"),
            price=Decimal("0"),
            commission=Decimal("0"),
            currency="USD",
            source="a.pdf",
        ),
    ]
    normalized = _normalize_split_rows(rows, verbose=False)
    assert normalized[0].qty == Decimal("900")
    assert normalized[1].qty == Decimal("1800")


def test_extract_rows_from_etrade_section_sold_rows():
    section = (
        "TRANSACTION HISTORY SECURITIES PURCHASED OR SOLD TRADE DATE "
        "SETTLEMENT DATE DESCRIPTION SYMBOL/CUSIP TRANSACTION TYPE QUANTITY "
        "PRICE AMOUNT PURCHASED AMOUNT SOLD "
        "05/10/19 09:30 05/14/19 ADVANCED MICRO DEVICES INC COM AMD "
        "Sold -45 27.0300 1,206.37 "
        "05/28/19 15:51 05/30/19 ADVANCED MICRO DEVICES INC COM AMD "
        "Sold -198 29.1633 5,764.26 "
        "TOTAL SECURITIES ACTIVITY"
    )
    rows = _extract_rows_from_etrade_section(
        section,
        source="ClientStatements_9139_053119.pdf",
        default_currency="USD",
    )
    assert len(rows) == 2
    assert rows[0].trade_date.isoformat() == "2019-05-10"
    assert rows[0].action == "SELL"
    assert rows[0].ticker == "AMD"
    assert rows[0].qty == Decimal("45")
    assert rows[0].price == Decimal("27.0300")
    assert rows[0].source == "ClientStatements_9139_053119.pdf"
