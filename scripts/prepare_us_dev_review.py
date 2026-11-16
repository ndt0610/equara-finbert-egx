"""Create an AI-only dev review draft; never produce human gold or edit source sheets."""
from __future__ import annotations
import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path('artifacts/evaluations/us_eval_20261115_v2')
EXPECTED_TASKS = '7d767b804eb5f0ea9eaf6898f54c30ac0b5e781ad856133bbe5d6fb056bcd43e'
CORRECTIONS = {
    '812b7c9fa63e4847fd247598': ('DIRECT_COMPANY_EVENT','NEUTRAL','AMBIGUOUS_MIXED','STAK bán khí cho hoạt động Exxon; điều khoản và lợi ích ròng cho XOM chưa rõ.'),
    '24ccafbdf01902cb012859cb': ('SECTOR_MACRO_SPILLOVER','NEUTRAL','AMBIGUOUS_MIXED','Tiêu đề không nêu NVIDIA; thông cáo GIGABYTE cho biết nền tảng dựa trên NVIDIA DGX Spark, tác động doanh thu chưa rõ.'),
    '4a6d160a38c361a777ac5363': ('DIRECT_COMPANY_EVENT','POSITIVE','POSITIVE','Tòa bác yêu cầu chặn quảng cáo của Lilly; tác động thương mại chưa định lượng.'),
    '2b594a3a90e68aa309e27845': ('DIRECT_COMPANY_EVENT','NEGATIVE','AMBIGUOUS_MIXED','Tin về kế nhiệm lãnh đạo NVIDIA, chưa rõ tác động hoạt động hay quyết định cuối.'),
    '3d8084432764e0c546d54f6e': ('DIRECT_COMPANY_EVENT','POSITIVE','POSITIVE','Lãnh đạo nêu kỳ vọng tăng trưởng dài hạn; là dự báo, không phải kết quả bảo đảm.'),
    'b0fe5ea39be8c676538f4de5': ('DIRECT_COMPANY_EVENT','POSITIVE','POSITIVE','Tin trực tiếp về kết quả phân tích Foundayo, không phải tin nhiễu.'),
    'd3630c5b6c4bccd2389b1a40': ('DIRECT_COMPANY_EVENT','NEUTRAL','AMBIGUOUS_MIXED','Microsoft phát hành bản vá lỗ hổng; rủi ro và lợi ích xử lý chưa được định lượng.'),
    'dce4a8e3305a95ca47176bf4': ('','NEUTRAL','','Tiêu đề ETF không nêu UNH; cần kiểm tra bài nguồn và mối liên quan.'),
    '123f0629272ccfc60b57beb6': ('','NEUTRAL','','Cùng tiêu đề với dòng UNH; cần kiểm tra bài nguồn và liên hệ với JPM.'),
    '8e745d80568e741fab3169b7': ('','NEUTRAL','','Diễn biến nhóm ngành không nêu CVX hoặc tác động cụ thể; cần kiểm tra liên hệ.'),
}
# Explicitly reviewed candidate links. These are not human gold event keys.
GROUPS = {
    'f9456d71559db8857fa0f2ea':'AI_JPM_QATAR_20B',
    '7b1b438a38b37051a1574cf4':'AI_JPM_QATAR_20B',
    '759b260c9b0a3ec4b17adfde':'AI_CVX_SOUTH32_GAS',
    '0c8e484cd9cc3de3b445e85d':'AI_CVX_SOUTH32_GAS',
}


def category(title: str, relevance: str) -> tuple[str, str]:
    if not relevance:
        return '', 'ABSTAIN_RELEVANCE'
    h = title.casefold()
    patterns = [
        ('ANALYST_RATING', r'\b(price target|analyst rating|initiates coverage|maintains (?:buy|neutral|overweight|underweight|outperform)|lowers price target|raises price target)\b'),
        ('EARNINGS_GUIDANCE', r'\b(earnings|quarterly results|financial results|q[1-4] 20\d\d|revenue guidance)\b'),
        ('REGULATORY_LEGAL', r'\b(court|lawsuit|fda approval|regulation|regulatory|tariffs|antitrust)\b'),
        ('MANAGEMENT_GOVERNANCE', r'\b(appoints|chief executive|interim ceo|cfo|board of directors|names .*partner)\b'),
        ('MA_RESTRUCTURING', r'\b(acquires|acquisition|merger|asset swap|restructur)\b'),
        ('PRODUCT_CONTRACT', r'\b(launches|unveils|agreement|contract|supply deal|partnership|phase 3|trial)\b'),
    ]
    if relevance == 'SECTOR_MACRO_SPILLOVER':
        return 'MACRO_SECTOR', 'AI_PROPOSED_REVIEW'
    for name, pattern in patterns:
        if re.search(pattern, h):
            return name, 'AI_PROPOSED_REVIEW'
    return 'OTHER', 'AI_DEFAULT_OTHER_REVIEW'


def validate_draft(rows):
    """Reject contradictions and gold-like labels before writing the AI draft."""
    tones, groups = {}, {}
    for row in rows:
        title = row['headline'].strip().casefold()
        tone = row['textual_tone_ai']
        if tone and title in tones and tones[title] != tone:
            raise ValueError('IDENTICAL_HEADLINE_TONE_CONFLICT')
        if tone:
            tones[title] = tone
        group = row['event_cluster_candidate']
        if group and group in groups and groups[group] != row['ticker']:
            raise ValueError('AI_CLUSTER_CROSSES_TICKERS')
        if group:
            groups[group] = row['ticker']
        rel, implication = row['target_relevance_ai'], row['economic_implication_ai']
        if rel == 'INCIDENTAL_OR_NOISE' and (implication != 'NOT_APPLICABLE' or group):
            raise ValueError('AI_IRRELEVANT_LABEL_CONFLICT')
        if not rel and (implication or group):
            raise ValueError('AI_UNRESOLVED_MUST_ABSTAIN')


def main():
    data = (ROOT/'dev.jsonl').read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED_TASKS:
        raise ValueError('DEV_TASK_HASH_CHANGED')
    tasks = {x['task_id']: x for x in map(json.loads,data.decode('utf8').splitlines())}
    with (ROOT/'dev_codex_ai_provisional_v2.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); rows=list(reader); fields=reader.fieldnames
    if len(rows) != 180 or len({r['task_id'] for r in rows}) != 180 or {r['task_id'] for r in rows} != set(tasks):
        raise ValueError('DRAFT_TASK_BINDING_MISMATCH')
    new_fields = fields + ['source_url','event_category_ai','category_status','event_cluster_candidate',
                           'event_cluster_status','first_mention_scope','review_priority','change_note']
    for r in rows:
        task=tasks[r['task_id']]
        if (r['headline'],r['ticker']) != (task['headline'],task['ticker']):
            raise ValueError('DRAFT_CONTENT_MISMATCH')
        r['source_url']=task.get('source_url') or ''
        if r['task_id'] in CORRECTIONS:
            rel,tone,impact,reason=CORRECTIONS[r['task_id']]
            r['target_relevance_ai'],r['textual_tone_ai'],r['economic_implication_ai']=rel,tone,impact
            r['change_note']=reason
            r['rationale_note']=reason
            r['review_status']='AI_CORRECTED_NEEDS_HUMAN_REVIEW' if rel else 'AI_ABSTAIN_RELEVANCE_REVIEW'
        else:
            r['change_note']=''
        r['event_category_ai'],r['category_status']=category(r['headline'],r['target_relevance_ai'])
        relevant=r['target_relevance_ai'] in ('DIRECT_COMPANY_EVENT','SECTOR_MACRO_SPILLOVER')
        if relevant:
            r['event_cluster_candidate']=GROUPS.get(r['task_id'],f"AI_SINGLE_{r['task_id']}")
            r['event_cluster_status']='AI_LINKED_PAIR_REVIEW' if r['task_id'] in GROUPS else 'SINGLETON_UNVERIFIED'
        else:
            r['event_cluster_candidate']=''
            r['event_cluster_status']='ABSTAIN_RELEVANCE' if not r['target_relevance_ai'] else 'NOT_APPLICABLE'
        r['first_mention']=''
        r['first_mention_scope']='NOT_ESTABLISHED'
        r['review_priority']='HIGH' if (not r['target_relevance_ai'] or r['economic_implication_ai']=='AMBIGUOUS_MIXED' or r['task_id'] in CORRECTIONS or r['event_cluster_status']=='AI_LINKED_PAIR_REVIEW') else 'STANDARD'
    validate_draft(rows)
    target=ROOT/'dev_codex_ai_review_v3.csv'
    with target.open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=new_fields);writer.writeheader();writer.writerows(rows)
    print(f'Prepared {len(rows)} AI drafts: {target}')


if __name__=='__main__':
    main()
