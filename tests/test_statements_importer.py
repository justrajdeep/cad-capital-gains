"""Tests for Schwab PDF -> ACB CSV importer (no PyMuPDF required)."""
from decimal import Decimal

from capgains.statements_importer import (
    AcbRow,
    _acbs_from_etrade_espp_confirmation_text,
    _acbs_from_etrade_rsu_release_text,
    _etrade_stmt_line_is_sell_to_cover_tax,
    _extract_rows_from_etrade_section,
    _extract_rows_from_ibkr_stocks_trades_section,
    _extract_rows_from_text_blocks,
    _infer_split_factor_and_mode,
    _normalize_split_rows,
    _bucket_line,
    _lines_from_words,
    _row_from_stock_fields,
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
    d3 = _parse_trade_date("3-15-2024")
    assert d3.year == 2024 and d3.month == 3 and d3.day == 15


def test_parse_money():
    assert _parse_money("$1,234.50") == Decimal("1234.50")
    assert _parse_money("(150.0000)") == Decimal("-150.0000")
    assert _parse_money("(1,500.00)") == Decimal("-1500.00")
    assert _parse_money("--") is None
    assert _parse_money("") is None


def test_schwab_transfer_in_kind_omitted():
    assert _row_from_stock_fields(
        trade_date_str="2024-09-05",
        activity="Transfer",
        desc="RS 62256",
        purchase_price_str="--",
        acq_fmv_str="$135.58",
        shares_str="(150.0000)",
        sale_price_str="--",
        proceeds_str="--",
        ticker="NVDA",
        default_currency="USD",
        source="s.pdf",
    ) is None


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


def test_collect_rows_from_dir_supported_file_patterns(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "Account Statement_2025-12-31.PDF").write_text("x")
    (tmp_path / "ClientStatements_9139_053119.pdf").write_text("x")
    (tmp_path / "U5486467_20240101_20241231.pdf").write_text("x")
    (tmp_path / "Year-end Statement_2025-12-31.PDF").write_text("x")
    (tmp_path / "Restricted Stock Activity_2025-12-10.PDF").write_text("x")

    parsed_schwab = []
    parsed_etrade = []
    parsed_ibkr = []

    def fake_extract_schwab(path, _currency):
        parsed_schwab.append(path.name)
        return []

    def fake_extract_etrade(path, _currency):
        parsed_etrade.append(path.name)
        return []

    def fake_extract_ibkr(path, _currency):
        parsed_ibkr.append(path.name)
        return []

    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_pdf",
        fake_extract_schwab,
    )
    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_etrade_pdf",
        fake_extract_etrade,
    )
    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_ibkr_pdf",
        fake_extract_ibkr,
    )
    rows = collect_rows_from_dir(tmp_path, "USD", verbose=False)
    assert rows == []
    assert parsed_schwab == [
        "Account Statement_2025-12-31.PDF",
    ]
    assert parsed_etrade == ["ClientStatements_9139_053119.pdf"]
    assert parsed_ibkr == ["U5486467_20240101_20241231.pdf"]


def test_acbs_from_etrade_espp_confirmation_text_synthetic():
    text = (
        "EMPLOYEE STOCK PLAN PURCHASE CONFIRMATION\n"
        "DEVICES(AMD)\n"
        "Purchase Date\n"
        "3-15-2024\n"
        "Quantity Shares Deposited STREETNAME\n"
        "12.5\n"
        "Purchase Price per Share\n"
        "$10.25\n"
    )
    rows = _acbs_from_etrade_espp_confirmation_text(
        text,
        source="getEsppConfirmation_1.pdf",
        default_currency="USD",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.trade_date.isoformat() == "2024-03-15"
    assert r.ticker == "AMD"
    assert r.action == "BUY"
    assert r.qty == Decimal("12.5")
    assert r.price == Decimal("10.25")
    assert r.description == "ESPP Purchase (E*TRADE plan)"
    assert r.source == "getEsppConfirmation_1.pdf"


def test_acbs_from_etrade_rsu_release_text_synthetic():
    text = (
        "EMPLOYEE STOCK PLAN RELEASE CONFIRMATION\n"
        "DEVICES(AMD)\n"
        "Release Date\n"
        "1-20-2024\n"
        "Market Value Per Share\n"
        "150.00\n"
        "Shares Issued\n"
        "5.5\n"
        "Award Number\n"
        "RU12345\n"
    )
    rows = _acbs_from_etrade_rsu_release_text(
        text,
        source="getReleaseConfirmation_1.pdf",
        default_currency="USD",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.trade_date.isoformat() == "2024-01-20"
    assert r.ticker == "AMD"
    assert r.action == "BUY"
    assert r.qty == Decimal("5.5")
    assert r.price == Decimal("150.00")
    assert r.description == "RSU Release RU12345 (E*TRADE plan)"
    assert r.source == "getReleaseConfirmation_1.pdf"


def test_collect_rows_from_dir_supported_file_patterns_includes_etrade_plan(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "getEsppConfirmation_amd.pdf").write_text("x")
    (tmp_path / "getReleaseConfirmation_rsu.pdf").write_text("x")
    (tmp_path / "getreleaseconfirmation_2.pdf").write_text("x")
    (tmp_path / "misc.txt").write_text("n")

    parsed_espp = []
    parsed_rsu = []

    def fake_espp(path, _currency):
        parsed_espp.append(path.name)
        return []

    def fake_rsu(path, _currency):
        parsed_rsu.append(path.name)
        return []

    _si = "capgains.statements_importer"
    monkeypatch.setattr(
        f"{_si}.extract_acb_rows_from_etrade_espp_confirmation",
        fake_espp,
    )
    monkeypatch.setattr(
        f"{_si}.extract_acb_rows_from_etrade_rsu_release",
        fake_rsu,
    )
    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_pdf",
        lambda _path, _currency: [],
    )
    collect_rows_from_dir(tmp_path, "USD", verbose=False)
    assert sorted(parsed_espp) == ["getEsppConfirmation_amd.pdf"]
    # Lowercase getreleaseconfirmation_ matches RSU; distinct from ESPP
    assert sorted(parsed_rsu) == [
        "getReleaseConfirmation_rsu.pdf",
        "getreleaseconfirmation_2.pdf",
    ]


def test_collect_rows_from_dir_verbose_summary_includes_ib(
    tmp_path,
    monkeypatch,
    capsys,
):
    (tmp_path / "Account Statement_2026-03-31.PDF").write_text("x")
    (tmp_path / "U5486467_20240101_20241231.pdf").write_text("x")

    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_pdf",
        lambda _path, _currency: [],
    )
    monkeypatch.setattr(
        "capgains.statements_importer.extract_acb_rows_from_ibkr_pdf",
        lambda _path, _currency: [],
    )
    rows = collect_rows_from_dir(tmp_path, "USD", verbose=True)
    assert rows == []
    out = capsys.readouterr().err
    assert "1 Interactive Brokers Activity Statement file(s)" in out
    assert "0 skipped." in out


def test_collect_rows_from_dir_verbose_includes_etrade_plan_count(
    tmp_path,
    monkeypatch,
    capsys,
):
    (tmp_path / "getEsppConfirmation_x.pdf").write_text("x")
    (tmp_path / "getReleaseConfirmation_y.pdf").write_text("x")
    (tmp_path / "random_unsupported.pdf").write_text("x")

    _si = "capgains.statements_importer"
    monkeypatch.setattr(
        f"{_si}.extract_acb_rows_from_etrade_espp_confirmation",
        lambda _p, _c: [],
    )
    monkeypatch.setattr(
        f"{_si}.extract_acb_rows_from_etrade_rsu_release",
        lambda _p, _c: [],
    )
    collect_rows_from_dir(tmp_path, "USD", verbose=True)
    err = capsys.readouterr().err
    assert "Found 3 PDF(s)" in err
    assert "2 E*TRADE plan confirmation (ESPP/RSU) file(s)" in err
    assert "1 skipped." in err


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


def test_extract_rows_from_ibkr_stocks_trades_section():
    lines = [
        "Stocks",
        "USD",
        "NVDA",
        "2024-10-04,",
        "09:33:21",
        "0.0102",
        "124.0400",
        "124.9200",
        "-1.27",
        "0.00",
        "1.27",
        "0.00",
        "0.01",
        "O;R",
        "QQQ",
        "2024-08-07,",
        "04:00:00",
        "-75",
        "441.6700",
        "434.7700",
        "33,125.25",
        "-1.34",
        "-35,865.79",
        "-2,741.89",
        "517.50",
        "C",
        "Total in CAD",
    ]
    rows = _extract_rows_from_ibkr_stocks_trades_section(
        lines,
        source="U5486467_20240101_20241231.pdf",
        default_currency="CAD",
    )
    assert len(rows) == 2
    assert rows[0].ticker == "NVDA"
    assert rows[0].action == "BUY"
    assert rows[0].qty == Decimal("0.0102")
    assert rows[0].price == Decimal("124.0400")
    assert rows[0].commission == Decimal("0")
    assert rows[0].currency == "USD"
    assert rows[1].ticker == "QQQ"
    assert rows[1].action == "SELL"
    assert rows[1].qty == Decimal("75")
    assert rows[1].price == Decimal("441.6700")
    assert rows[1].commission == Decimal("1.34")
    assert rows[1].source == "U5486467_20240101_20241231.pdf"


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


def test_etrade_stmt_line_is_sell_to_cover_tax_phrases():
    assert _etrade_stmt_line_is_sell_to_cover_tax(
        "ADVANCED MICRO DEVICES INC SELL TO COVER",
    )
    assert _etrade_stmt_line_is_sell_to_cover_tax("Sale to cover - AMD COM")
    assert _etrade_stmt_line_is_sell_to_cover_tax(
        "EMPLOYEE STOCK PLAN TAX WITHHOLDING",
    )
    assert not _etrade_stmt_line_is_sell_to_cover_tax(
        "ADVANCED MICRO DEVICES INC COM",
    )


def test_extract_rows_from_etrade_section_omits_sell_to_cover():
    section = (
        "TRANSACTION HISTORY SECURITIES PURCHASED OR SOLD TRADE DATE "
        "SETTLEMENT DATE DESCRIPTION SYMBOL/CUSIP TRANSACTION TYPE QUANTITY "
        "PRICE AMOUNT PURCHASED AMOUNT SOLD "
        "05/10/19 09:30 05/14/19 ADVANCED MICRO DEVICES INC COM AMD "
        "Sold -100 25.00 2,500.00 "
        "05/11/19 10:00 05/15/19 ADVANCED MICRO DEVICES SELL TO COVER AMD "
        "Sold -5 30.00 150.00 "
        "05/12/19 10:00 05/16/19 ADVANCED MICRO DEVICES INC COM AMD "
        "Sold -3 32.00 96.00 "
        "TOTAL SECURITIES ACTIVITY"
    )
    rows = _extract_rows_from_etrade_section(
        section,
        source="ClientStatements_x.pdf",
        default_currency="USD",
    )
    assert len(rows) == 2
    assert {r.qty for r in rows} == {Decimal("100"), Decimal("3")}
