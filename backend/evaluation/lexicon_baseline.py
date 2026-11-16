"""Small fixed, inspectable headline baseline; no licensed external lexicon copied."""
from __future__ import annotations

import re

from backend.services.numeric_headline_parser import parse_price_target_change

LABELS = ("POSITIVE", "NEUTRAL", "NEGATIVE")
VERSION = "manual-financial-phrases-v2"
PHRASES = {
    ("beats", "estimates"): 1, ("beat", "estimates"): 1, ("raises", "guidance"): 1,
    ("raises", "outlook"): 1, ("profit", "rises"): 1, ("revenue", "grows"): 1,
    ("margin", "expands"): 1, ("wins", "contract"): 1, ("contract", "win"): 1,
    ("approval",): 1, ("approved",): 1, ("upgrade",): 1,
    ("misses", "estimates"): -1, ("miss", "estimates"): -1,
    ("cuts", "guidance"): -1, ("cuts", "outlook"): -1,
    ("profit", "falls"): -1, ("revenue", "falls"): -1,
    ("less", "than", "expected"): -1, ("antitrust", "probe"): -1,
    ("lawsuit",): -1, ("probe",): -1, ("downgrade",): -1,
    ("bankruptcy",): -1, ("layoffs",): -1,
    ("raises", "price", "target"): 1, ("raises", "target", "price"): 1,
    ("lowers", "price", "target"): -1, ("lowers", "target", "price"): -1,
    ("price", "target", "raised"): 1, ("price", "target", "lowered"): -1,
    ("price", "target", "cut"): -1, ("target", "price", "cut"): -1,
    ("beats",): 1, ("beat",): 1, ("misses",): -1, ("missed",): -1,
    ("upgrades",): 1, ("upgraded",): 1, ("downgrades",): -1, ("downgraded",): -1,
    ("approves",): 1, ("clearance",): 1, ("efficacy",): 1,
    ("expands",): 1, ("expansion",): 1, ("launches",): 1,
    ("rallies",): 1, ("jumps",): 1, ("recovery",): 1, ("restores",): 1,
    ("slashes",): -1, ("rejects",): -1, ("rejected",): -1,
    ("outage",): -1, ("investigation",): -1, ("investigates",): -1,
    ("inquiry",): -1, ("warns",): -1, ("warning",): -1,
    ("selloff",): -1, ("sinks",): -1, ("falls",): -1,
    ("crisis",): -1, ("discontinues",): -1,
}
NEGATORS = {"not", "no", "never", "fails", "failed", "without"}


def predict_lexicon(headline: str) -> dict:
    tokens = re.findall(r"[a-z0-9]+", headline.casefold())
    phrases = sorted(PHRASES, key=lambda phrase: (-len(phrase), phrase))
    used = set()
    evidence = []
    total = 0
    for index in range(len(tokens)):
        if index in used:
            continue
        for phrase in phrases:
            span = range(index, index + len(phrase))
            if any(position in used for position in span) or tuple(tokens[index:index + len(phrase)]) != phrase:
                continue
            polarity = PHRASES[phrase]
            if any(word in NEGATORS for word in tokens[max(0, index - 3):index]):
                polarity *= -1
            total += polarity
            used.update(span)
            evidence.append({"phrase": " ".join(phrase), "polarity": polarity})
            break
    target_change = parse_price_target_change(headline)
    if target_change and target_change.direction != 'NUMERIC_TARGET_UNCHANGED':
        polarity = -1 if target_change.direction == 'NUMERIC_TARGET_CUT' else 1
        total += polarity
        evidence.append({"phrase": f"{target_change.direction}:{target_change.previous}->{target_change.current}",
                         "polarity": polarity})
    label = "POSITIVE" if total > 0 else "NEGATIVE" if total < 0 else "NEUTRAL"
    return {"label": label, "probabilities": {name: float(name == label) for name in LABELS},
            "evidence": evidence, "baseline_version": VERSION}
