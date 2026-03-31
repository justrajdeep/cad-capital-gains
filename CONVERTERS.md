# Transaction Converters

The tool includes converters to import transaction data from various brokerage and tax slip formats into the cad-capital-gains format. All converters output JSON files that can be used with `capgains show`, `capgains calc`, and `capgains maxcost`.

To see all available converters:
```bash
$ capgains convert --help
```

## Schwab Equity Awards Center (EAC)

Convert transaction history exported from Schwab's Equity Awards Center:

```bash
# Convert all transactions
$ capgains convert schwab-eac schwab_export.json output.json

# Filter by specific tickers
$ capgains convert schwab-eac schwab_export.json output.json -t AAPL -t GOOGL
```

The converter handles:
- ESPP purchases (using Purchase Fair Market Value)
- RSU vests (using Vest Fair Market Value)
- Share sales (using Sale Price)
- ESPP deposits with tax withholding (uses `NetSharesDeposited` when shares are withheld for tax)
- Automatic filtering of non-capital-gains events (dividends, tax withholding)

## TD Direct Investing

### Trade Confirmations

Convert from individual trade confirmation PDFs:

```bash
$ capgains convert td-trades-pdf confirmation.pdf output.json
```

### Monthly Statements (Recommended)

Convert from monthly statements and trade confirmations together:

```bash
$ capgains convert td-statements-pdf ./statements/ ./confirmations/ output.json
```

This converter is recommended as it:
- Cross-validates data between statements and confirmations
- Automatically deduplicates transactions
- Supports Norbert's Gambit journal transfers (DLR.U <-> DLR)

### T5008 Tax Slip (TD PDF)

Convert the T5008 tax slip PDF downloaded from TD WebBroker:

```bash
$ capgains convert td-t5008-pdf t5008.pdf output.json
```

The cost and proceeds figures come directly from the T5008 values, so the output matches what CRA has on file. The statement/confirmation converters use Bank of Canada exchange rates and may produce slightly different figures.

If the converter doesn't recognise a security name on the slip, it will tell you the exact name and ask you to provide a mapping via `--ticker-map`:

```bash
$ capgains convert td-t5008-pdf t5008.pdf output.json \
    --ticker-map ticker_map.json
```

Where `ticker_map.json` is a simple JSON object:
```json
{
  "SOME CURRENCY ETF": "DLR",
  "ANOTHER ETF NAME": "XYZ"
}
```

## CRA AllSlips T5008

Convert T5008 entries from the CRA "All Slips" PDF downloaded from CRA My Account:

```bash
$ capgains convert cra-t5008-pdf allslips.pdf output.json
```

This produces the same output format as the TD T5008 converter and can be used to cross-verify that both sources agree. Note that the CRA version has no settlement dates, so all transactions are assigned to Jan 1 of the tax year.

The `--ticker-map` option works the same way as for the TD T5008 converter.

## Norbert's Gambit

For currency exchange using DLR/DLR.U ETF pairs, the tool supports special journal actions:

```bash
# Combine separate USD and CAD transaction files
$ capgains convert norberts-gambit usd_buys.json cad_sells.json output.json
```

The calculator correctly handles the JOURNAL_IN/JOURNAL_OUT sequence:
1. **BUY**: Purchase DLR.U in USD account
2. **JOURNAL_OUT**: Transfer shares out of USD account
3. **JOURNAL_IN**: Receive shares in CAD account as DLR
4. **SELL**: Sell DLR in CAD

Journal transactions preserve the adjusted cost base through the transfer without triggering capital gains.

## Merging Multiple Files

When you have transactions from different sources (e.g. stocks from one converter and ETFs from another), you can merge them into a single file using the top-level `merge` command:

```bash
$ capgains merge stocks.json etfs.json -o combined.json
```

The merged file is sorted chronologically and can be used directly with `calc`, `show`, or `maxcost`:

```bash
$ capgains calc combined.json 2024
```

This is useful when you file with data from multiple brokerages or want to combine converted T5008 data with other transaction sources into a single report.
