"""Tests for the convert merge CLI command."""

import json

from click.testing import CliRunner
from capgains.cli import capgains


def _write_json(path, transactions):
    with open(path, 'w') as f:
        json.dump(transactions, f)


def _tx(date, ticker, action='BUY', qty=100, price=10.0, currency='CAD'):
    return {
        "date": date, "description": f"{action} {ticker}",
        "ticker": ticker, "action": action,
        "qty": qty, "price": price,
        "commission": 0, "currency": currency
    }


class TestConvertMerge:

    def test_merge_two_files(self, tmp_path):
        fa = str(tmp_path / "a.json")
        fb = str(tmp_path / "b.json")
        out = str(tmp_path / "merged.json")
        _write_json(fa, [_tx("2024-01-15", "AAA")])
        _write_json(fb, [_tx("2024-06-15", "BBB", currency="USD")])

        runner = CliRunner()
        result = runner.invoke(
            capgains, ['merge', fa, fb, '-o', out]
        )
        assert result.exit_code == 0

        with open(out) as f:
            merged = json.load(f)
        assert len(merged) == 2
        assert merged[0]['ticker'] == 'AAA'
        assert merged[1]['ticker'] == 'BBB'

    def test_merge_sorts_chronologically(self, tmp_path):
        fa = str(tmp_path / "a.json")
        fb = str(tmp_path / "b.json")
        out = str(tmp_path / "merged.json")
        _write_json(fa, [_tx("2024-06-01", "LATE", "SELL")])
        _write_json(fb, [_tx("2024-01-01", "EARLY")])

        runner = CliRunner()
        result = runner.invoke(
            capgains, ['merge', fa, fb, '-o', out]
        )
        assert result.exit_code == 0

        with open(out) as f:
            merged = json.load(f)
        assert merged[0]['date'] == '2024-01-01'
        assert merged[1]['date'] == '2024-06-01'

    def test_merge_three_files(self, tmp_path):
        files = []
        for i, (d, t) in enumerate([
            ("2024-03-01", "CCC"),
            ("2024-01-01", "AAA"),
            ("2024-02-01", "BBB"),
        ]):
            f = str(tmp_path / f"f{i}.json")
            _write_json(f, [_tx(d, t)])
            files.append(f)

        out = str(tmp_path / "merged.json")
        runner = CliRunner()
        result = runner.invoke(
            capgains, ['merge', *files, '-o', out]
        )
        assert result.exit_code == 0

        with open(out) as f:
            merged = json.load(f)
        assert len(merged) == 3
        assert [t['ticker'] for t in merged] == ['AAA', 'BBB', 'CCC']

    def test_merge_preserves_tickers(self, tmp_path):
        fa = str(tmp_path / "xxx.json")
        fb = str(tmp_path / "yyy.json")
        out = str(tmp_path / "merged.json")
        _write_json(fa, [_tx("2024-01-01", "XXX", price=500, currency="USD")])
        _write_json(fb, [_tx("2024-01-15", "YYY", price=13.71)])

        runner = CliRunner()
        result = runner.invoke(
            capgains, ['merge', fa, fb, '-o', out]
        )
        assert result.exit_code == 0

        with open(out) as f:
            merged = json.load(f)
        tickers = {t['ticker'] for t in merged}
        assert tickers == {'XXX', 'YYY'}

    def test_merge_output_readable_by_calc(self, tmp_path, requests_mock):
        """The merged output should be a valid input for capgains calc."""
        fa = str(tmp_path / "a.json")
        out = str(tmp_path / "merged.json")
        _write_json(fa, [
            _tx("2024-01-15", "AAA"),
            _tx("2024-06-15", "AAA", "SELL", qty=50, price=15.0),
        ])

        runner = CliRunner()
        result = runner.invoke(
            capgains, ['merge', fa, '-o', out]
        )
        assert result.exit_code == 0

        result = runner.invoke(capgains, ['show', out])
        assert result.exit_code == 0
        assert 'AAA' in result.output

    def test_merge_missing_output_option(self, tmp_path):
        fa = str(tmp_path / "a.json")
        _write_json(fa, [_tx("2024-01-01", "AAA")])

        runner = CliRunner()
        result = runner.invoke(capgains, ['merge', fa])
        assert result.exit_code == 2

    def test_merge_nonexistent_input(self):
        runner = CliRunner()
        result = runner.invoke(
            capgains,
            ['merge', '/nonexistent.json', '-o', '/tmp/out.json']
        )
        assert result.exit_code == 2

    def test_merge_summary_message(self, tmp_path):
        fa = str(tmp_path / "a.json")
        fb = str(tmp_path / "b.json")
        out = str(tmp_path / "merged.json")
        _write_json(fa, [_tx("2024-01-01", "AAA")])
        _write_json(fb, [
            _tx("2024-02-01", "BBB"),
            _tx("2024-03-01", "CCC"),
        ])

        runner = CliRunner()
        result = runner.invoke(
            capgains, ['merge', fa, fb, '-o', out]
        )
        assert '3 transactions' in result.output
        assert '2 files' in result.output
