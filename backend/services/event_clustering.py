"""Conservative event grouping: exact title or an explicit caller event key.

Text similarity is deliberately not treated as verified event identity.
"""
import re
from collections import defaultdict
from decimal import Decimal
from datetime import datetime
from urllib.parse import unquote, urlsplit

from backend.contracts.pit_models import EventCluster, NewsItem
from backend.services.numeric_headline_parser import parse_price_target_change

SOURCE_PRIORITY = {"sec_filing": 0, "issuer_release": 1, "news": 2}


def headline_score(item: NewsItem) -> Decimal:
    assert item.probabilities is not None
    return item.probabilities["positive"] - item.probabilities["negative"]


def _title_key(title: str) -> str:
    return " ".join(re.findall(r"\w+", title.casefold()))


def cluster_events(items: list[NewsItem]) -> list[EventCluster]:
    groups: dict[tuple[str, str], list[NewsItem]] = defaultdict(list)
    for item in items:
        if item.source_kind == "context" or item.probabilities is None:
            continue
        key = "event:" + item.event_key if item.event_key else "title:" + _title_key(item.title)
        groups[(item.ticker, key)].append(item)
    result = []
    for (ticker, key), members in sorted(groups.items()):
        ordered = sorted(members, key=lambda x: (x.ingested_at, x.item_id))
        first = ordered[0]
        primary = min(members, key=lambda x: (SOURCE_PRIORITY[x.source_kind], x.ingested_at, x.item_id))
        scores = [headline_score(x) for x in members]
        result.append(EventCluster(
            event_id=f"{ticker}:{key}", ticker=ticker,
            item_ids=tuple(x.item_id for x in ordered),
            earliest_ingested_at=first.ingested_at,
            first_item_id=first.item_id,
            primary_item_id=primary.item_id,
            cluster_score_method="equal_member_mean",
            first_item_score=headline_score(first),
            score=sum(scores, Decimal(0)) / Decimal(len(scores)),
            grouping_status="caller_event_key" if key.startswith("event:") else "exact_title",
            conflicting_headlines=any(x > 0 for x in scores) and any(x < 0 for x in scores),
        ))
    return result


# Phase 2 uses a separate, explainable grouping path. Phase 1 stays identical.
STOPWORDS = {"a", "an", "the", "on", "in", "of", "for", "to", "and", "with", "its", "as", "at", "by", "help", "helps"}
TOKEN_ALIASES = {"beats": "beat", "beating": "beat", "expectations": "estimate", "estimates": "estimate"}
GENERIC_EVENT_WORDS = {
    "analyst", "analysts", "price", "target", "rating", "stock", "stocks", "shares", "company", "companies",
    "update", "updates", "adjust", "adjusts", "maintains", "news", "what", "s", "going", "why", "is",
    "today", "session", "monday", "tuesday", "wednesday", "thursday", "friday", "falling", "trending",
    "pre", "market", "top", "here", "are", "forecasts", "files", "major", "holdings", "notification",
    "information", "technology", "whale", "activity", "lowers", "raises", "buy", "overweight", "outperform",
}
_BROKER_ACTION = re.compile(r"^(.+?)\s+(?:maintains|reiterates|downgrades|upgrades|lowers|raises|cuts|adjusts|updates)\b", re.I)
_RECURRING_TEMPLATE = re.compile(r"\b(?:today|monday|tuesday|wednesday|thursday|friday)\b", re.I)


def content_tokens(title: str, ticker: str, aliases: list[str] | None = None) -> set[str]:
    excluded = {ticker.casefold()}
    for alias in aliases or []:
        excluded.update(re.findall(r"[a-z0-9]+", alias.casefold()))
    words = re.findall(r"[a-z0-9]+", title.casefold())
    return {TOKEN_ALIASES.get(word, word) for word in words if word not in STOPWORDS | excluded}


def _canonical_url(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or '').lower().removeprefix('www.')
        path = re.sub(r'/+', '/', unquote(parts.path).casefold()).rstrip('/')
    except ValueError:
        return None
    return (host, path) if host and path else None


def _slug_tokens(value: str | None, ticker: str, aliases: list[str]) -> set[str]:
    url = _canonical_url(value)
    if not url:
        return set()
    slug = url[1].split('/')[-1]
    # Long hexadecimal IDs and article numbers carry no event meaning.
    words = [word for word in re.findall(r'[a-z0-9]+', slug)
             if not word.isdigit() and not re.fullmatch(r'[0-9a-f]{12,}', word)]
    return content_tokens(' '.join(words), ticker, aliases)


def _quantitative_anchors(title: str) -> set[str]:
    # Explicit amounts only. Calendar years and ordinal numbers are weak anchors.
    return {amount.replace(',', '') for amount in re.findall(r'\$\s*(\d[\d,]*(?:\.\d+)?)', title)}


def _article_ids(url: tuple[str, str] | None) -> set[str]:
    return {part for part in url[1].split('/') if re.fullmatch(r'\d{7,}', part)} if url else set()


def cluster_events_v2(items: list[dict], aliases_by_ticker: dict[str, list[str]] | None = None) -> list[dict]:
    """Complete-link content similarity avoids a bridge headline merging unrelated events."""
    aliases_by_ticker = aliases_by_ticker or {}
    groups: list[list[dict]] = []
    reasons: list[list[str]] = []
    for item in sorted(items, key=lambda x: (x["ticker"], x.get("published_at_utc") or "", x["item_id"])):
        chosen, reason = None, None
        for index, members in enumerate(groups):
            if members[0]["ticker"] != item["ticker"]:
                continue
            checks = [_pair_reason(item, other, aliases_by_ticker.get(item["ticker"], [])) for other in members]
            if all(checks):
                chosen, reason = index, checks[0]
                break
        if chosen is None:
            groups.append([item]); reasons.append(["STRUCTURAL_FILING" if item["item_type"] == "SEC_FILING" else "SINGLETON"])
        else:
            groups[chosen].append(item); reasons[chosen].append(reason)
            reasons[chosen] = [x for x in reasons[chosen] if x not in {"SINGLETON", "STRUCTURAL_FILING"}]
    result = []
    for members, why in zip(groups, reasons):
        ordered = sorted(members, key=lambda x: (x["ingested_at_utc"], x["item_id"]))
        scored = [x["net_score"] for x in members if x.get("scoring_status") == "SCORED" and x.get("net_score") is not None]
        primary = min(members, key=lambda x: ({"SEC_FILING": 0, "PRESS_RELEASE": 1, "NEWS_HEADLINE": 2}.get(x["item_type"], 3), x["ingested_at_utc"], x["item_id"]))
        result.append({
            "ticker": members[0]["ticker"], "item_ids": [x["item_id"] for x in ordered],
            "earliest_item_id": ordered[0]["item_id"], "primary_item_id": primary["item_id"],
            "clustering_reason": sorted(set(why)), "score": sum(scored) / len(scored) if scored else None,
            "has_conflicting_sentiment": any(x >= .25 for x in scored) and any(x <= -.25 for x in scored),
            "structural_only": not scored,
        })
    return result


def _pair_reason(a: dict, b: dict, aliases: list[str]) -> str | None:
    if a.get("external_event_key") and a["external_event_key"] == b.get("external_event_key"):
        return "SHARED_EXTERNAL_KEY"
    if a["item_type"] == "SEC_FILING" or b["item_type"] == "SEC_FILING":
        return None
    left_url, right_url = _canonical_url(a.get('source_url')), _canonical_url(b.get('source_url'))
    # An article-specific URL wins over differences in an abbreviated headline.
    article_slug_size = len(_slug_tokens(a.get('source_url'), a['ticker'], aliases))
    if left_url and left_url == right_url and (article_slug_size >= 3 or
                                               (article_slug_size >= 2 and _article_ids(left_url))):
        return "SHARED_CANONICAL_URL"
    left_target = parse_price_target_change(a["headline"])
    right_target = parse_price_target_change(b["headline"])
    if left_target and right_target and left_target.current != right_target.current:
        return None
    left_broker, right_broker = _BROKER_ACTION.search(a['headline']), _BROKER_ACTION.search(b['headline'])
    if left_broker and right_broker and left_broker.group(1).casefold() != right_broker.group(1).casefold():
        return None
    left_amounts, right_amounts = _quantitative_anchors(a['headline']), _quantitative_anchors(b['headline'])
    if left_amounts and right_amounts and not left_amounts & right_amounts:
        return None
    ids_a, ids_b = _article_ids(left_url), _article_ids(right_url)
    if ids_a and ids_b and ids_a.isdisjoint(ids_b) and (
        _RECURRING_TEMPLATE.search(a['headline']) or _RECURRING_TEMPLATE.search(b['headline'])
    ):
        return None
    if left_url and right_url and left_url[1].split('/')[-1] == right_url[1].split('/')[-1] and not (ids_a and ids_b and ids_a.isdisjoint(ids_b)):
        slug = _slug_tokens(a.get('source_url'), a['ticker'], aliases)
        try:
            slug_hours = abs((datetime.fromisoformat(a['published_at_utc']) -
                              datetime.fromisoformat(b['published_at_utc'])).total_seconds()) / 3600
        except (TypeError, ValueError):
            slug_hours = float('inf')
        if len(slug) >= 4 and slug_hours <= 36:
            return "SHARED_URL_SLUG"
    left = content_tokens(a["headline"], a["ticker"], aliases)
    right = content_tokens(b["headline"], b["ticker"], aliases)
    if not left or not right:
        return None
    try:
        hours = abs((datetime.fromisoformat(a["published_at_utc"]) - datetime.fromisoformat(b["published_at_utc"])).total_seconds()) / 3600
    except (TypeError, ValueError):
        return None
    if left == right and hours <= 24 and not (ids_a and ids_b and ids_a.isdisjoint(ids_b)):
        return "EXACT_NORMALIZED_MATCH"
    shared = left & right
    similarity = len(shared) / len(left | right)
    distinctive = shared - GENERIC_EVENT_WORDS
    if hours <= 24 and similarity >= .55 and len(distinctive) >= 2:
        return f"TOKEN_JACCARD_24H_{similarity:.2f}"
    short = left if len(left) <= len(right) else right
    containment = len(shared) / len(short)
    anchors = left_amounts & right_amounts
    if hours <= 36 and len(short) >= 3 and len(distinctive) >= 2:
        if containment >= .80:
            return f"TOKEN_CONTAINMENT_36H_{containment:.2f}"
        if anchors and containment >= .60:
            return f"QUANT_ANCHOR_MATCH_36H_{containment:.2f}"
    return None
