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
_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

# Marks duplicate rows in the CSV (description) and in the terminal
_DUP_PREFIX = "[DUPLICATE] "
_DUP_STAMP_RE = re.compile(r"^\[DUPLICATE\]\s*", re.IGNORECASE)
_COMMON_SPLIT_FACTORS = (2, 3, 4, 5, 10)


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
    source: str = "Manual"

    def source_or_manual(self) -> str:
        src = self.source.strip()
        return src if src else "Manual"

    def as_tuple(
        self,
    ) -> Tuple[str, str, str, str, str, str, str, str, str]:
        return (
            self.trade_date.isoformat(),
            self.description,
            self.ticker,
            self.action,
            format(self.qty, "f"),
            format(self.price, "f"),
            format(self.commission, "f"),
            self.currency,
            self.source_or_manual(),
        )

    def as_tuple_duplicate_marked(
        self,
        is_duplicate: bool,
    ) -> Tuple[str, str, str, str, str, str, str, str, str]:
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
            self.source_or_manual(),
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
    if _ISODATE_RE.match(raw):
        return date.fromisoformat(raw)
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


def _is_date_token(s: str) -> bool:
    s = s.strip()
    return bool(_ISODATE_RE.match(s) or _DATE_RE.match(s))


def _is_time_token(s: str) -> bool:
    return bool(_TIME_RE.match(s.strip()))


def _infer_split_factor_and_mode(
    quantities: Sequence[Decimal],
) -> Tuple[Optional[int], Optional[str]]:
    """
    Infer split factor and quantity mode from split rows.

    mode='added': quantity already represents added shares.
    mode='post': quantity appears to be post-split total shares.
    """
    if not quantities:
        return None, None
    best = (0, None, None)  # score, factor, mode
    for factor in _COMMON_SPLIT_FACTORS:
        add_base = Decimal(factor - 1)
        post_base = Decimal(factor)
        add_hits = sum(1 for q in quantities if (q % add_base) == 0)
        post_hits = sum(1 for q in quantities if (q % post_base) == 0)
        add_better = add_hits > best[0]
        add_tie = add_hits == best[0] and factor > (best[1] or 0)
        if add_better or add_tie:
            best = (add_hits, factor, "added")
        post_better = post_hits > best[0]
        post_tie = post_hits == best[0] and factor > (best[1] or 0)
        if post_better or post_tie:
            best = (post_hits, factor, "post")
    score, factor, mode = best
    if score <= 0:
        return None, None
    return factor, mode


def _normalize_split_rows(
    rows: Sequence[AcbRow],
    *,
    verbose: bool = False,
) -> List[AcbRow]:
    """
    Normalize stock split rows to incremental-share form.

    If split rows look like post-split totals for factor F, convert
    qty -> qty * (F-1) / F so they become added-share rows.
    """
    out: List[AcbRow] = list(rows)
    idxs = [
        i for i, r in enumerate(out)
        if "stock split" in r.description.lower()
    ]
    if not idxs:
        return out

    groups = {}
    for i in idxs:
        r = out[i]
        groups.setdefault((r.ticker, r.trade_date), []).append(i)

    for (ticker, trade_date), gidx in groups.items():
        quantities = [out[i].qty for i in gidx]
        factor, mode = _infer_split_factor_and_mode(quantities)
        if verbose:
            click.echo(
                "Split analysis {} {}: factor={}, mode={}, rows={}".format(
                    ticker,
                    trade_date.isoformat(),
                    factor,
                    mode,
                    len(gidx),
                ),
                err=True,
            )
        if factor is None or mode != "post":
            # Already incremental (or not inferable).
            continue

        f = Decimal(factor)
        fm1 = Decimal(factor - 1)
        for i in gidx:
            r = out[i]
            new_qty = (r.qty * fm1) / f
            out[i] = AcbRow(
                trade_date=r.trade_date,
                description=r.description,
                ticker=r.ticker,
                action=r.action,
                qty=new_qty,
                price=r.price,
                commission=r.commission,
                currency=r.currency,
                source=r.source,
            )
    return out


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


def _row_from_stock_fields(
    trade_date_str: str,
    activity: str,
    desc: str,
    purchase_price_str: str,
    acq_fmv_str: str,
    shares_str: str,
    sale_price_str: str,
    proceeds_str: str,
    ticker: str,
    default_currency: str,
    source: str,
) -> Optional[AcbRow]:
    try:
        trade_date = _parse_trade_date(trade_date_str)
    except ValueError:
        return None

    shares_raw = _parse_money(shares_str)
    if shares_raw is None:
        return None
    qty = abs(shares_raw)

    sale_price = _parse_money(sale_price_str) or Decimal(0)
    proceeds = _parse_money(proceeds_str) or Decimal(0)
    acq_fmv = _parse_money(acq_fmv_str) or Decimal(0)

    summary_l = "{} {}".format(activity, desc).lower()
    is_stock_split = "stock split" in summary_l
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

    # Stock splits should increase share count without changing total ACB.
    # Represent split rows as zero-cost BUY entries.
    if is_stock_split:
        action = "BUY"
        price = Decimal(0)
    else:
        # Per user request: otherwise use Acquisition FMV as the price basis.
        price = acq_fmv if acq_fmv > 0 else Decimal(0)

    description = " ".join(
        p for p in (activity.strip(), desc.strip()) if p
    ).strip() or "Schwab"

    return AcbRow(
        trade_date=trade_date,
        description=description[:500],
        ticker=ticker,
        action=action,
        qty=qty,
        price=price,
        commission=Decimal(0),
        currency=default_currency,
        source=source,
    )


def _extract_rows_from_text_blocks(
    page_text: str,
    ticker: str,
    default_currency: str,
    source: str,
) -> List[AcbRow]:
    lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    if "No stock transactions during this period" in page_text:
        return []

    try:
        start = lines.index("Proceeds") + 1
    except ValueError:
        return []

    rows: List[AcbRow] = []
    i = start
    while i < len(lines):
        token = lines[i]
        low = token.lower()
        if low.startswith("cash transaction summary"):
            break
        if token.startswith("* This transaction occurred"):
            break
        if token.startswith("©"):
            break
        if low.startswith("page "):
            i += 1
            continue
        if not _is_date_token(token):
            i += 1
            continue

        trade_date_str = token
        i += 1
        if i < len(lines) and _is_time_token(lines[i]):
            i += 1

        if i + 8 >= len(lines):
            break
        activity = lines[i]
        desc = lines[i + 1]
        # skip purchase/vest date (i+2) and subscription FMV (i+5)
        purchase_price_str = lines[i + 3]
        acq_fmv_str = lines[i + 4]
        shares_str = lines[i + 6]
        sale_price_str = lines[i + 7]
        proceeds_str = lines[i + 8]
        i += 9

        row = _row_from_stock_fields(
            trade_date_str=trade_date_str,
            activity=activity,
            desc=desc,
            purchase_price_str=purchase_price_str,
            acq_fmv_str=acq_fmv_str,
            shares_str=shares_str,
            sale_price_str=sale_price_str,
            proceeds_str=proceeds_str,
            ticker=ticker,
            default_currency=default_currency,
            source=source,
        )
        if row is not None:
            rows.append(row)

    return rows


def extract_acb_rows_from_page(
    page: Any,
    default_currency: str,
    source: str = "Manual",
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
    if y_header is None:
        return []
    if y_cash is None:
        # Continued pages often omit a cash summary section; keep scanning
        # until the end of the page and let row-level validation filter noise.
        y_cash = float("inf")

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
            _parse_trade_date(cols[0])
        except ValueError:
            continue

        row = _row_from_stock_fields(
            trade_date_str=cols[0],
            activity=cols[1],
            desc=cols[2],
            purchase_price_str=cols[4],
            acq_fmv_str=cols[5],
            shares_str=cols[7],
            sale_price_str=cols[8],
            proceeds_str=cols[9],
            ticker=ticker,
            default_currency=default_currency,
            source=source,
        )
        if row is not None:
            rows.append(row)

    # Fallback for statements where each transaction is rendered as vertical
    # blocks (date/time/activity/... one line each) instead of a row grid.
    fallback_rows = _extract_rows_from_text_blocks(
        text,
        ticker=ticker,
        default_currency=default_currency,
        source=source,
    )
    seen = {row_key_from_acb_row(r) for r in rows}
    for r in fallback_rows:
        key = row_key_from_acb_row(r)
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)

    return rows


def extract_acb_rows_from_pdf(
    path: Path,
    default_currency: str,
) -> List[AcbRow]:
    fitz = _import_fitz()
    rows: List[AcbRow] = []
    source = path.name.strip() or "Manual"
    with fitz.open(path) as doc:
        for page in doc:
            rows.extend(
                extract_acb_rows_from_page(
                    page,
                    default_currency,
                    source=source,
                )
            )
    rows.sort(key=lambda r: (r.trade_date, r.ticker, r.action))
    return rows


def collect_rows_from_dir(
    input_dir: Path,
    default_currency: str,
    *,
    verbose: bool = False,
) -> List[AcbRow]:
    pdfs = sorted(input_dir.glob("*.pdf")) + sorted(input_dir.glob("*.PDF"))
    relevant_pdfs = [
        p for p in pdfs
        if p.name.lower().startswith("account statement")
    ]
    skipped_pdfs = [
        p for p in pdfs
        if p not in relevant_pdfs
    ]
    if verbose:
        msg = "Found {} PDF(s): {} Account Statement file(s), {} skipped."
        click.echo(
            msg.format(
                len(pdfs),
                len(relevant_pdfs),
                len(skipped_pdfs),
            ),
            err=True,
        )
        for p in skipped_pdfs:
            click.echo(
                "Skipping non-Account-Statement file: {}".format(p.name),
                err=True,
            )

    all_rows: List[AcbRow] = []
    for p in relevant_pdfs:
        if not p.is_file():
            continue
        if verbose:
            click.echo("Parsing {}".format(p.name), err=True)
        all_rows.extend(extract_acb_rows_from_pdf(p, default_currency))
    all_rows = _normalize_split_rows(all_rows, verbose=verbose)
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
                    "source",
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
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Print file scanning/parsing progress to stderr.",
)
def main(
    input_dir: str,
    output_path: str,
    currency: str,
    with_header: bool,
    force: bool,
    verbose: bool,
) -> None:
    """Read Schwab statement PDFs from INPUT_DIR and write acb-style CSV."""
    _import_fitz()
    in_dir = _path_arg(input_dir)
    out_path = _path_arg(output_path)
    rows = collect_rows_from_dir(
        in_dir,
        currency,
        verbose=verbose,
    )
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
