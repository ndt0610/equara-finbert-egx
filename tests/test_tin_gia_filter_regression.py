"""Real failure regression: football/quote pages must never reach FinBERT for ETEL."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.providers.news import NewsItem
from backend.upgrades.tin_gia.candidate_service import TinGiaCandidateService


def test_etel_football_and_quote_are_retained_but_not_scored():
    scored = []

    class Inference:
        async def classify_many(self, titles):
            scored.extend(titles)
            return [{'positive': .7, 'negative': .1, 'neutral': .2} for _ in titles]

    service = TinGiaCandidateService(SimpleNamespace(
        news=SimpleNamespace(settings=SimpleNamespace(eodhd_tin_gia_news_api_token=None)),
        inference=Inference()))
    titles = [
        'Al Mokawloon Al Arab vs El Masria Lell Etesalat (Telecom Egypt) - Egypt Cup - OneFootball',
        'Telecom Egypt Equity Price and Quote - London Stock Exchange',
        'Telecom Egypt expands fibre network',
    ]

    async def rss(**kwargs):
        if kwargs['query_id'] != 'google_company_tier1':
            return []
        return [dict(item=NewsItem(title=title, url=f'https://example.org/{i}',
                                  published_at=datetime.now(timezone.utc).isoformat(), source='Google News RSS',
                                  kind='micro', symbol='ETEL.EGX'),
                     provider='Google News RSS', query_id=kwargs['query_id'], query_url=None,
                     query_tier=1, received_at=datetime.now(timezone.utc).isoformat(),
                     provider_index=i, scope='company_candidate') for i, title in enumerate(titles)]

    service._rss_candidates = rss
    result = asyncio.run(service.collect('ETEL.EGX'))
    assert scored == [titles[2]]
    assert len(result['candidates']) == 3
    assert [r['reason_code'] for r in result['candidates'][:2]] == ['sports', 'not_news_page']
    assert result['counts']['excluded'] == 2
    assert result['counts']['scored'] == 1
