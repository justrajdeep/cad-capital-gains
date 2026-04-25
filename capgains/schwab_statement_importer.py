"""
Import Schwab account statement PDFs into cad-capital-gains CSV rows.

Parses the "Stock Transaction Summary" table using word positions from
PyMuPDF. Layout is tuned for common Schwab stock-summary tables; other
formats may need boundary tweaks.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Set, Tuple

import click


# PyMuPDF word tuple: x0, y0, x1, y1, text, block, line, word
Word = Tuple[float, float, float, float, str, int, int, int]

# Column splits (x0) measured from sample Schwab "Stock Transaction Summary"
# pages; words are bucketed into [lo, hi) ranges.
_X_BOUNDS = (0, 95, 180, 265, 345, 405, 475, 555, 635, 705, 1200)

_DATE_RE = re.compile(
    r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$"
)
_ISODATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Marks duplicate rows in the CSV (description) and in the terminal
_DUP_PREFIX = "[DUPLICATE] "
_DUP_STAMP_RE = re.compile(r"^\[DUPLICATE\]\s*", re.IGNORECASE)


def _strip_dup_stamp(desc: str) -> str:
    return _DUP_STAMP_RE.sub("", desc, count=1).strip()


@dataclass(frozen=True)
class AcbRow:
    """One cad-capital-gains CSV row."""

    trade_date: date
    description: str
    ticker: str
    action: str
    qty: Decimal
    price: Decimal
    commission: Decimal
    currency: str

    def as_tuple(self) -> Tuple[str, str, str, str, str, str, str, str]:
        return (
            self.trade_date.isoformat(),
            self.description,
            self.ticker,
            self.action,
            format(self.qty, "f"),
            format(self.price, "f"),
            format(self.commission, "f"),
            self.currency,
        )

    def as_tuple_duplicate_marked(
        self,
        is_duplicate: bool,
    ) -> Tuple[str, str, str, str, str, str, str, str]:
        if not is_duplicate:
            return self.as_tuple()
        base = _strip_dup_stamp(self.description)
        desc = _DUP_PREFIX + base
        return (
            self.trade_date.isoformat(),
            desc,
            self.ticker,
            self.action,
            format(self.qty, "f"),
            format(self.price, "f"),
            format(self.commission, "f"),
            self.currency,
        )


def _import_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise click.ClickException(
            "PyMuPDF is required. In this repo run `uv sync` "
            "(pdf is a default group) or `uv sync --group pdf`, "
            "then e.g. `uv run -m capgains.schwab_statement_importer`."
        ) from e
    return fitz


def _parse_trade_date(raw: str) -> date:
    raw = raw.strip()
    m = _DATE_RE.match(raw)
    if not m:
        raise ValueError("bad date {!r}".format(raw))
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    return date(y, mo, d)


def _parse_money(raw: str) -> Optional[Decimal]:
    s = raw.strip()
    if not s or s == "--":
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _norm_dec_str(s: str) -> str:
    t = s.strip().replace(",", "").replace("$", "")
    if not t:
        d = Decimal(0)
    else:
        d = Decimal(t)
    return format(d.normalize(), "f")


def _fmt_key_dec(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _parse_date_field_for_key(s: str) -> str:
    s = s.strip()
    if _ISODATE_RE.match(s):
        return s
    return _parse_trade_date(s).isoformat()


def row_key_from_acb_row(r: AcbRow) -> Tuple[str, ...]:
    return (
        r.trade_date.isoformat(),
        _strip_dup_stamp(r.description).lower(),
        r.ticker.strip().upper(),
        r.action.strip().upper(),
        _fmt_key_dec(r.qty),
        _fmt_key_dec(r.price),
        _fmt_key_dec(r.commission),
        r.currency.strip().upper(),
    )


def row_key_from_csv_fields(cols: Sequence[str]) -> Tuple[str, ...]:
    if len(cols) < 8:
        raise ValueError("expected 8 columns")
    d = _parse_date_field_for_key(cols[0])
    desc = _strip_dup_stamp(cols[1]).lower()
    t = cols[2].strip().upper()
    a = cols[3].strip().upper()
    q = _norm_dec_str(cols[4])
    p = _norm_dec_str(cols[5])
    c = _norm_dec_str(cols[6])
    cur = cols[7].strip().upper()
    return (d, desc, t, a, q, p, c, cur)


def load_existing_row_keys(path: Path) -> Set[Tuple[str, ...]]:
    if not path.is_file():
        return set()
    keys: Set[Tuple[str, ...]] = set()
    with path.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.reader(fp))
    if not rows:
        return set()
    start = 0
    if rows[0] and rows[0][0].strip().lower() == "date":
        start = 1
    for row in rows[start:]:
        if len(row) < 8:
            continue
        if not any(x.strip() for x in row[:8]):
            continue
        try:
            keys.add(row_key_from_csv_fields(row[:8]))
        except (ValueError, InvalidOperation):
            continue
    return keys


def resolve_existing_row_keys(
    out_path: Path,
    force: bool,
) -> Set[Tuple[str, ...]]:
    """Row keys from the output file, or empty when ``--force``."""
    if force:
        return set()
    return load_existing_row_keys(out_path)


def mark_duplicate_flags(
    rows: Sequence[AcbRow],
    existing_keys: Set[Tuple[str, ...]],
) -> List[Tuple[AcbRow, bool]]:
    seen: Set[Tuple[str, ...]] = set()
    out: List[Tuple[AcbRow, bool]] = []
    for r in rows:
        k = row_key_from_acb_row(r)
        is_dup = k in existing_keys or k in seen
        if not is_dup:
            seen.add(k)
        out.append((r, is_dup))
    return out


def _lines_from_words(
    words: Sequence[Word],
    y_tol: float = 3.5,
) -> List[List[Word]]:
    """Group PyMuPDF words into visual lines (sorted left-to-right)."""
    if not words:
        return []
    ws = sorted(words, key=lambda w: (w[1], w[0]))
    lines: List[List[Word]] = []
    for w in ws:
        if not lines:
            lines.append([w])
            continue
        line_y = sum(x[1] for x in lines[-1]) / len(lines[-1])
        if abs(w[1] - line_y) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w[0])
    return lines


def _bucket_line(line: Sequence[Word]) -> List[str]:
    cols: List[List[str]] = [[] for _ in range(len(_X_BOUNDS) - 1)]
    for w in line:
        x0 = w[0]
        for i in range(len(_X_BOUNDS) - 1):
            lo, hi = _X_BOUNDS[i], _X_BOUNDS[i + 1]
            if lo <= x0 < hi:
                cols[i].append(w[4])
                break
    return [" ".join(parts).strip() for parts in cols]


def _line_text(line: Sequence[Word]) -> str:
    return " ".join(w[4] for w in sorted(line, key=lambda w: w[0]))


def _find_ticker(page_text: str) -> Optional[str]:
    m = re.search(r"Stock Transaction Summary:\s*(\S+)", page_text)
    return m.group(1).strip() if m else None


def _header_end_y(
    lines: Sequence[Sequence[Word]],
    y_cash: Optional[float],
) -> Optional[float]:
    """Return y of the last header line containing 'Proceeds' (above cash)."""
    best: Optional[float] = None
    for ln in lines:
        y = sum(w[1] for w in ln) / len(ln)
        if y_cash is not None and y >= y_cash - 2:
            continue
        if "proceeds" in _line_text(ln).lower():
            if best is None or y > best:
                best = y
    return best


def _cash_section_y(lines: Sequence[Sequence[Word]]) -> Optional[float]:
    for ln in lines:
        if "cash transaction summary" in _line_text(ln).lower():
            return sum(w[1] for w in ln) / len(ln)
    return None


def extract_acb_rows_from_page(
    page: Any,
    default_currency: str,
) -> List[AcbRow]:
    """Parse one PDF page; returns rows (may be empty)."""
    text = page.get_text()
    ticker = _find_ticker(text)
    if not ticker:
        return []

    words = page.get_text("words")
    if not words:
        return []

    lines = _lines_from_words(words)
    y_cash = _cash_section_y(lines)
    y_header = _header_end_y(lines, y_cash)
    if y_header is None or y_cash is None:
        return []

    rows: List[AcbRow] = []
    for ln in lines:
        y = sum(w[1] for w in ln) / len(ln)
        if y <= y_header + 2 or y >= y_cash - 2:
            continue
        lt = _line_text(ln)
        low = lt.lower()
        if "no stock transactions" in low:
            continue
        if "stock transaction summary" in low:
            continue

        cols = _bucket_line(ln)
        if len(cols) < 10:
            continue
        if not cols[0]:
            continue
        try:
            trade_date = _parse_trade_date(cols[0])
        except ValueError:
            continue

        activity = cols[1].strip()
        desc = cols[2].strip()
        purchase_price = _parse_money(cols[4]) or Decimal(0)
        sale_price = _parse_money(cols[8]) or Decimal(0)
        proceeds = _parse_money(cols[9]) or Decimal(0)
        shares_raw = _parse_money(cols[7])
        if shares_raw is None:
            continue
        qty = abs(shares_raw)

        act_l = activity.lower()
        if any(k in act_l for k in ("sell", "sale", "sold")):
            action = "SELL"
        elif proceeds > 0 and sale_price > 0:
            action = "SELL"
        elif any(k in act_l for k in (
            "buy", "purchase", "vest", "grant", "espp", "rsu",
        )):
            action = "BUY"
        elif proceeds > 0:
            action = "SELL"
        else:
            action = "BUY"

        if action == "SELL":
            if sale_price > 0:
                price = sale_price
            elif qty > 0 and proceeds > 0:
                price = proceeds / qty
            else:
                price = Decimal(0)
        else:
            if purchase_price > 0:
                price = purchase_price
            else:
                acq = _parse_money(cols[5]) or Decimal(0)
                price = (acq / qty) if qty > 0 and acq > 0 else Decimal(0)

        description = " ".join(
            p for p in (activity, desc) if p
        ).strip() or "Schwab"

        rows.append(
            AcbRow(
                trade_date=trade_date,
                description=description[:500],
                ticker=ticker,
                action=action,
                qty=qty,
                price=price,
                commission=Decimal(0),
                currency=default_currency,
            )
        )
    return rows


def extract_acb_rows_from_pdf(
    path: Path,
    default_currency: str,
) -> List[AcbRow]:
    fitz = _import_fitz()
    rows: List[AcbRow] = []
    with fitz.open(path) as doc:
        for page in doc:
            rows.extend(extract_acb_rows_from_page(page, default_currency))
    rows.sort(key=lambda r: (r.trade_date, r.ticker, r.action))
    return rows


def collect_rows_from_dir(
    input_dir: Path,
    default_currency: str,
) -> List[AcbRow]:
    pdfs = sorted(input_dir.glob("*.pdf")) + sorted(input_dir.glob("*.PDF"))
    all_rows: List[AcbRow] = []
    for p in pdfs:
        if not p.is_file():
            continue
        all_rows.extend(extract_acb_rows_from_pdf(p, default_currency))
    all_rows.sort(key=lambda r: (r.trade_date, r.ticker, r.action))
    return all_rows


def write_acb_csv(
    rows: Iterable[Tuple[AcbRow, bool]],
    output_path: Path,
    *,
    with_header: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if with_header:
            w.writerow(
                [
                    "date",
                    "description",
                    "ticker",
                    "action",
                    "qty",
                    "price",
                    "commission",
                    "currency",
                ]
            )
        for r, is_dup in rows:
            w.writerow(r.as_tuple_duplicate_marked(is_dup))


def _path_arg(value: str) -> Path:
    """Normalize CLI paths (Click 7 passes str, not pathlib)."""
    return Path(value).expanduser()


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "input_dir",
    type=click.Path(exists=True, file_okay=False),
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    default=str(Path.home() / "acb.csv"),
    show_default=True,
    help="Output CSV path.",
)
@click.option(
    "--currency",
    default="USD",
    show_default=True,
    help="Currency column for all imported rows.",
)
@click.option(
    "--with-header/--no-header",
    default=True,
    show_default=True,
    help=(
        "Write a column header line "
        "(use --no-header for capgains show/calc)."
    ),
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help=(
        "Overwrite without comparing to the previous output file "
        "(duplicate checks only within this import)."
    ),
)
def main(
    input_dir: str,
    output_path: str,
    currency: str,
    with_header: bool,
    force: bool,
) -> None:
    """Read Schwab statement PDFs from INPUT_DIR and write acb-style CSV."""
    _import_fitz()
    in_dir = _path_arg(input_dir)
    out_path = _path_arg(output_path)
    rows = collect_rows_from_dir(in_dir, currency)
    existing = resolve_existing_row_keys(out_path, force)
    flagged = mark_duplicate_flags(rows, existing)
    ndup = sum(1 for _r, d in flagged if d)
    for r, is_dup in flagged:
        if not is_dup:
            continue
        line = "DUPLICATE: {}  {}  {}  qty={}  price={}  {}".format(
            r.trade_date.isoformat(),
            r.ticker,
            r.action,
            format(r.qty, "f"),
            format(r.price, "f"),
            r.currency,
        )
        click.secho(line, fg="yellow", err=True)
        dtxt = _strip_dup_stamp(r.description)
        if dtxt:
            click.secho("  {}".format(dtxt[:200]), fg="yellow", err=True)
    write_acb_csv(flagged, out_path, with_header=with_header)
    if ndup:
        click.echo(
            "Wrote {} row(s) to {} ({} duplicate(s); see [DUPLICATE] in CSV "
            "and messages above).".format(len(flagged), out_path, ndup),
            err=True,
        )
    else:
        click.echo(
            "Wrote {} row(s) to {}".format(len(flagged), out_path),
            err=True,
        )
    if not rows:
        click.echo(
            "No stock transactions found (or layout did not match). "
            "If your statements differ, open an issue with a redacted sample.",
            err=True,
        )


if __name__ == "__main__":  # pragma: no cover
    main.main(standalone_mode=True)
