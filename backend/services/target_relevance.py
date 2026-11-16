"""Unvalidated headline triage for manual review; not a ground-truth label."""
import re

EXTRA_ALIASES = {
    'AAPL': ('apple', 'iphone', 'ipad', 'mac', 'apple intelligence', 'apple tv', 'tim cook'),
    'NVDA': ('nvidia', 'jensen huang'),
    'MSFT': ('microsoft', 'azure', 'outlook', 'windows'),
    'LLY': ('lilly', 'mounjaro', 'zepbound', 'kisunla', 'foundayo', 'taltz', 'orforglipron'),
    'UNH': ('unitedhealth', 'unitedhealthcare', 'optum'),
    'XOM': ('exxonmobil', 'exxon'),
    'JPM': ('jpmorgan', 'j.p. morgan'),
    'GS': ('goldman sachs',),
}


def company_stem(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name.casefold())
    if words and words[0] == 'the':
        words.pop(0)
    endings = {'inc', 'incorporated', 'corp', 'corporation', 'co', 'company', 'group', 'holdings', 'plc', 'ltd'}
    while words and words[-1] in endings:
        words.pop()
    return ' '.join(words)


def classify_target_relevance(headline: str, ticker: str, item_type: str, catalog: dict) -> str:
    if item_type == 'SEC_FILING':
        return 'UNSCORABLE_ADMIN_FILING'
    company = catalog.get(ticker)
    if not company:
        return 'REVIEW_REQUIRED'
    terms = [ticker, company['company_name'], company_stem(company['company_name']), *company.get('aliases', []), *EXTRA_ALIASES.get(ticker, ())]
    if any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', headline, re.IGNORECASE)
           for term in terms if term):
        return 'TARGET_MENTION_REVIEW'
    return 'NO_TARGET_MENTION_REVIEW'


def experimental_relevance(headline: str, ticker: str, item_type: str, catalog: dict) -> str:
    """Heuristic for exploratory comparisons only; UNKNOWN must not imply irrelevance."""
    triage = classify_target_relevance(headline, ticker, item_type, catalog)
    if triage == 'UNSCORABLE_ADMIN_FILING':
        return triage
    if ticker == 'CVX' and re.search(r'\bcarvolix\b', headline, re.I) and not re.search(r'\b(?:chevron|cvx)\b', headline, re.I):
        return 'POSSIBLE_NOISE_UNVERIFIED'
    # Only flag explicit analyst-subject constructions. Retain ambiguous/self-referential cases for review.
    bank = {'GS': r'goldman\s+sachs', 'JPM': r'(?:jpmorgan(?:\s+chase)?|j\.p\.\s*morgan)'}
    if ticker in bank:
        actor = bank[ticker]
        m = re.match(r'^\s*' + actor + r'\s+(?:maintains|raises|lowers|adjusts|initiates|downgrades|upgrades)\b(.+)', headline, re.I)
        if m:
            tail = m.group(1).strip()
            subject = re.search(r'\bon\s+(.+)', tail, re.I) if re.search(r'\b(?:rating|coverage|price target|buy|sell|neutral|overweight|underweight)\b', tail, re.I) else None
            target = subject.group(1) if subject else None
            if target is None and re.match(r'^\s*' + actor + r'\s+(?:downgrades|upgrades)\s+', headline, re.I):
                target = tail
            if target and not re.search(actor + r'|\b(?:gs|jpm|itself|its own|own stock|economy|inflation|outlook|market|sector)\b', target, re.I):
                return 'POSSIBLE_NOISE_UNVERIFIED'
    if re.search(r'\b(if you invested|how much you would have made|whale alerts?|whale activity)\b', headline, re.I):
        return 'POSSIBLE_NOISE_UNVERIFIED'
    other_companies = r'\b(micron|super micro|sandisk|lam research|broadcom|vertiv|mstr|nebius)\b'
    if triage == 'NO_TARGET_MENTION_REVIEW' and re.search(other_companies, headline, re.I):
        return 'POSSIBLE_NOISE_UNVERIFIED'
    if ticker == 'AAPL' and re.search(r'\bnvidia\b', headline, re.I) and re.search(r"\b(tim cook as nvidia|post.steve jobs|apple.s 2011 rally)\b", headline, re.I):
        return 'POSSIBLE_NOISE_UNVERIFIED'
    if triage == 'TARGET_MENTION_REVIEW':
        return 'DIRECT_MENTION_UNVERIFIED'
    if re.search(r'\b(sectors?|inflation|cpi|oil and gas|big oil|glp[ -]?1|health insurers|chip exports)\b', headline, re.I):
        return 'SECTOR_MENTION_UNVERIFIED'
    return 'UNKNOWN_REVIEW'
