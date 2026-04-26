"""Action strings accepted for CSV/JSON transaction input.

Keep in sync with :class:`TransactionsReader` validation and with any code
that builds rows for ``capgains`` (e.g. statement importers).
"""

VALID_INPUT_ACTIONS = frozenset(
    ('BUY', 'SELL', 'JOURNAL', 'JOURNAL_IN', 'JOURNAL_OUT'),
)
