from scripts.audit_us_dev_events import find_candidates


def event(task_id, headline, published, url):
    return {'task_id':task_id, 'observation_id':task_id, 'item_id':task_id, 'ticker':'CVX',
            'headline':headline, 'published_at_utc':published, 'ingested_at_utc':published,
            'item_type':'NEWS_HEADLINE', 'source_url':url}


def test_audit_surfaces_rewrites_but_not_shared_generic_ticker_page():
    tasks=[event('a','Chevron signs South32 gas supply agreement','2026-10-27T12:00:00+00:00','https://example.org/quote/CVX'),
           event('b','South32 signs Chevron gas supply agreement','2026-10-27T14:00:00+00:00','https://example.org/quote/CVX'),
           event('c','Chevron announces unchanged dividend','2026-10-27T15:00:00+00:00','https://example.org/quote/CVX')]
    labels={x['task_id']:{'target_relevance_ai':'DIRECT_COMPANY_EVENT'} for x in tasks}
    raw={x['task_id']:{'external_event_key':None} for x in tasks}
    catalog={'CVX':{'company_name':'Chevron Corporation','aliases':['Chevron']}}
    pairs=find_candidates(tasks,labels,raw,catalog)
    assert {frozenset((x['a_id'],x['b_id'])) for x in pairs}=={frozenset(('a','b'))}
