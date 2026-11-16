"""Explicit price-target arithmetic in a headline; separate from model sentiment."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


_AMOUNT = r"\$?\s*(\d{1,4}(?:,\d{3})*(?:\.\d+)?)"
_TO_FROM = re.compile(r"\bto\s+" + _AMOUNT + r"\s+from\s+" + _AMOUNT + r"\b", re.I)
_FROM_TO = re.compile(r"\bfrom\s+" + _AMOUNT + r"\s+to\s+" + _AMOUNT + r"\b", re.I)
_TARGET = re.compile(r"\b(?:price\s+target|target\s+price|pt)\b", re.I)


@dataclass(frozen=True)
class NumericTargetChange:
    previous: Decimal
    current: Decimal
    direction: str


def parse_price_target_change(headline: str) -> NumericTargetChange | None:
    """Parse only explicit old/new price targets; do not infer an issuer benefit."""
    if not _TARGET.search(headline):
        return None
    for pattern, current_index, previous_index in ((_TO_FROM, 1, 2), (_FROM_TO, 2, 1)):
        for match in pattern.finditer(headline):
            if not _TARGET.search(headline[max(0, match.start() - 120):match.start()]):
                continue
            try:
                current = Decimal(match.group(current_index).replace(',', ''))
                previous = Decimal(match.group(previous_index).replace(',', ''))
            except InvalidOperation:
                continue
            direction = ('NUMERIC_TARGET_CUT' if current < previous else
                         'NUMERIC_TARGET_RAISE' if current > previous else 'NUMERIC_TARGET_UNCHANGED')
            return NumericTargetChange(previous, current, direction)
    return None
