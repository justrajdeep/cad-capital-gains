import csv
from click import ClickException
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .transaction import Transaction
from .transactions import Transactions


class TransactionsReader:
    """An interface that converts a CSV-file with transaction entries into a
    list of Transactions.
    """
    columns = [
        "date",
        "description",
        "ticker",
        "action",
        "qty",
        "price",
        "commission",
        "currency"
    ]
    source_column = "source"

    @classmethod
    def _is_header_row(cls, entry):
        """Return true when row looks like CSV header."""
        cols = [x.strip().lower() for x in entry]
        base = cls.columns
        if len(cols) == len(base):
            return cols == base
        if len(cols) == len(base) + 1:
            return cols == base + [cls.source_column]
        return False

    @classmethod
    def get_transactions(cls, csv_file):
        """Convert the CSV-file entries into a list of Transactions."""
        transactions = []
        try:
            with open(csv_file, newline='') as f:
                reader = csv.reader(f)
                last_date = None
                for entry_no, entry in enumerate(reader):
                    if entry_no == 0 and cls._is_header_row(entry):
                        continue
                    actual_num_columns = len(entry)
                    expected_num_columns = len(cls.columns)
                    expected_with_source = expected_num_columns + 1
                    if actual_num_columns not in (
                        expected_num_columns,
                        expected_with_source,
                    ):
                        # Accept legacy 8-column CSVs and optional source
                        # (9th) column; reject everything else.
                        raise ClickException(
                            "Transaction entry {}: expected {} or {} columns, entry has {}"  # noqa: E501
                            .format(entry_no,
                                    expected_num_columns,
                                    expected_with_source,
                                    actual_num_columns))
                    if actual_num_columns == expected_with_source:
                        entry = entry[:expected_num_columns]
                    date_idx = cls.columns.index("date")
                    date_str = entry[date_idx]
                    try:
                        entry[date_idx] = datetime.strptime(
                            date_str.split(" ")[0],
                            '%Y-%m-%d').date()
                    except ValueError:
                        raise ClickException(
                            "The date ({}) was not entered in the correct format (YYYY-MM-DD)"  # noqa: E501
                            .format(date_str))
                    qty_idx = cls.columns.index("qty")
                    qty_str = entry[qty_idx]
                    try:
                        entry[qty_idx] = Decimal(qty_str)
                    except InvalidOperation:
                        raise ClickException(
                            "The quantity entered {} is not a valid number"
                            .format(qty_str))
                    price_idx = cls.columns.index("price")
                    price_str = entry[price_idx]
                    try:
                        entry[price_idx] = Decimal(price_str)
                    except InvalidOperation:
                        raise ClickException(
                            "The price entered {} is not a valid number"
                            .format(price_str))
                    commission_idx = cls.columns.index("commission")
                    commission_str = entry[commission_idx]
                    try:
                        entry[commission_idx] = Decimal(commission_str)
                    except InvalidOperation:
                        raise ClickException(
                            "The commission entered {} is not a valid number"
                            .format(commission_str))
                    transaction = Transaction(*entry)
                    if last_date:
                        if transaction.date < last_date:
                            raise ClickException(
                                "Transactions were not entered in chronological order")  # noqa: E501
                    last_date = transaction.date
                    transactions.append(transaction)
            return Transactions(transactions)
        except FileNotFoundError:
            raise ClickException("File not found: {}".format(csv_file))
        except OSError:
            raise OSError("Could not open {} for reading".format(csv_file))
