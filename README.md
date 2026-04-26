Canadian Capital Gains CLI Tool
=
[![Build](https://github.com/EmilMaric/cad-capital-gains/actions/workflows/build.yml/badge.svg?branch=master)](https://github.com/EmilMaric/cad-capital-gains/actions/workflows/build.yml)
[![codecov](https://codecov.io/gh/EmilMaric/cad-capital-gains/branch/master/graph/badge.svg)](https://codecov.io/gh/EmilMaric/cad-capital-gains)

Calculating your capital gains and tracking your adjusted cost base (ACB) manually, or using an Excel document, often proves to be a laborious process. This CLI tool calculates your capital gains and ACB for you, and just requires a CSV file with basic information about your transactions. The idea with this tool is that you are able to more or less cut-and-copy the output that it genarates and copy it into whatever tax filing software you end up using.

## Features:
- Supports transactions with multiple different stock tickers in the same CSV file, and outputs them in separate tables.
- Currently supports transactions done in both USD and CAD. For USD transactions, the daily exchange rate will be automatically fetched from the Bank of Canada.
- Will automatically apply [superficial capital loss](https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/tax-return/completing-a-tax-return/personal-income/line-127-capital-gains/capital-losses-deductions/what-a-superficial-loss.html) rules when calculating your capital gains and ACB. This tool only supports full superficial capital losses, and does not support partial superficial losses. In sales with a superficial capital loss, the capital loss will be carried forward as perscribed by the CRA. A sale with a capital loss will be treated as superficial if it satisifies the following:
    - Shares with the same ticker were bought in the 61 day window (30 days before or 30 days after the sale)
    - There is a non-zero balance of shares sharing the same ticker at the end of the 61 day window (30 days after the sale)
- Outputs the running adjusted cost base (ACB) for every transaction with a non-superficial capital gain/loss
- Supports fractional quantities of shares
- Supports brokerage PDF import via `statements-to-acb` for:
    - Schwab: `Account Statement_*.PDF`
    - E*TRADE: `ClientStatements_*.pdf`
    - Interactive Brokers: `U<account>_<yyyymmdd>_<yyyymmdd>.pdf` (stock trades in `Trades` -> `Stocks`)

# Installation
```bash
# To get the latest release
uv tool install cad-capgains

# Or run without installing permanently
uvx cad-capgains --help
```

## Brokerage statement PDFs (optional)

This repo includes an importer wrapper for brokerage PDF statements. Point it
to a folder and it auto-detects supported files:
- `Account Statement_*.PDF` (Schwab)
- `ClientStatements_*.pdf` (E*TRADE)
- `U<account>_<yyyymmdd>_<yyyymmdd>.pdf` (Interactive Brokers activity statements)

It writes a CSV compatible with `capgains` and includes a `source` column.
For Interactive Brokers files, the current parser targets stock trades from
the `Trades` -> `Stocks` sections.

From a git checkout, run:

```bash
uv run statements-to-acb acb_pdf -o <acb.csv> [-f] [-v]
```

The importer **writes a header row by default**. `capgains show` /
`capgains calc` now handle files with or without a header row.

The importer also writes a `source` column (typically the PDF filename). If
no source data is available, it defaults to `Manual`.

For Schwab imports, the CSV `price` column is taken from the statement's
**Acquisition FMV** value.
Exception: `Stock Split` rows are emitted with `price=0` so split events do
not artificially increase ACB.

**In-kind position transfers (e.g. Schwab to IBKR):** Schwab
*Stock Transaction Summary* rows whose **Activity** is `Transfer` are
**omitted** from the import (not a new purchase, not a market sale, and
you keep your existing ACB). IBKR **FOP / ACAT** in-kind deposits appear in
the **Transfers** section; they are **not** added as new `BUY` rows, so
you do not double-count the same shares when you mix broker PDFs in one
run. Rely on your lot history; add manual `BUY`/`SELL` lines only if you
need a single CSV to model the move in a way your advisor recommends.

For stock splits, the importer also applies split-aware quantity handling:
it infers the split factor/mode from statement rows and normalizes split
entries to incremental-share form when needed.

Example (10-for-1 split):
- If you held 100 shares before the split, you should end up with 1000 total.
- The importer records the split as an incremental row of +900 shares at
  `price=0`, so share count changes but total ACB does not.

If the output file already exists, any new row that matches a line already
on disk (or a repeated line in the same import run) is **flagged in the
terminal** (highlighted when the terminal supports color) and in the CSV by
prefixing the **description** field with **`[DUPLICATE]`** so you can fix or
remove it before using the file elsewhere. Pass **`-f` / `--force`** to
ignore the previous file and only detect duplicates **within** the current
import (full rewrite from PDFs).

Only supported statement file patterns are parsed; other PDFs in the input
folder are skipped. Use **`-v` / `--verbose`** to see what was skipped and what
was parsed.

# CSV File Requirements
To start, create a CSV file that will contain all of your transactions. In the CSV file, each line will represent a `BUY` or `SELL` transaction.  Your transactions **must be in order**, with the oldest transactions coming first, followed by newer transactions coming later. The format is as follows:
```csv
<yyyy-mm-dd>,<description>,<stock_ticker>,<action(BUY/SELL)>,<quantity>,<price>,<commission>,<currency>[,<source>]
```
Here is a sample CSV file:
```csv
# sample.csv
2017-2-15,ESPP PURCHASE,GOOG,BUY,100,50.00,10.00,USD,Manual
2017-5-20,RSU VEST,GOOG,SELL,50,45.00,0.00,CAD,Manual
```

**NOTE: This tool only supports calculating ACB and capital gains with transactions
dating from May 1, 2007 and onwards.**

# Usage
To show the CSV file in a nice tabular format you can run:
```bash
$ capgains show sample.csv
+------------+---------------+----------+----------+-------+---------+--------------+------------+
| date       | description   | ticker   | action   |   qty |   price |   commission |   currency |
|------------+---------------+----------+----------+-------+---------+--------------+------------|
| 2017-02-15 | ESPP PURCHASE | GOOG     | BUY      |   100 |   50.00 |        10.00 |        USD |
| 2017-05-20 | RSU VEST      | GOOG     | SELL     |    50 |   45.00 |         0.00 |        CAD |
+------------+---------------+----------+----------+-------+---------+--------------+------------+
```
To calculate the capital gains you can run:
```bash
$ capgains calc sample.csv 2017
GOOG-2017
[Total Gains = -1,028.54]
+------------+---------------+----------+-------+------------+----------+-----------+---------------------+
| date       | description   | ticker   | qty   |   proceeds |      ACB |   outlays |   capital gain/loss |
|------------+---------------+----------+-------+------------+----------+-----------+---------------------|
| 2017-05-20 | RSU VEST      | GOOG     | 50    |   2,250.00 | 3,278.54 |      0.00 |           -1,028.54 |
+------------+---------------+----------+-------+------------+----------+-----------+---------------------+
```
Your CSV file can contain transactions spanning across multiple different tickers. You can filter the above commands by running the following:
```bash
$ capgains calc sample.csv 2017 -t GOOG
...

$ capgains show sample.csv -t GOOG
...
```
For additional commands and options, run one of the following:
```bash
$ capgains --help

$ capgains <command> --help
```
You can take this output and plug it into your favourite tax software (Simpletax, StudioTax, etc) and verify that the capital gains/losses that the tax software reports lines up with what the output of this command says.

# Finding issues
If you find issues using this tool, please create an Issue using the [Github issue tracker](https://github.com/EmilMaric/cad-capital-gains/issues) and one of us will try to fix it.

# Contributing
If you would like to contribute, please read the [CONTRIBUTING.md](https://github.com/EmilMaric/cad-capital-gains/blob/master/CONTRIBUTING.md) page
