"""Prepare a source-reviewed AI dev draft. Outputs are never human gold labels."""
import csv
import hashlib
import json
from pathlib import Path

from scripts.prepare_us_dev_review import validate_draft

ROOT = Path('artifacts/evaluations/us_eval_20261115_v2')
EXPECTED_V3 = '3f510a0f8dbf4aa274563c2c326fcd8fd6f2b06d1943c53a7f2b3bb11cf723b6'
CASES = {
 'dce4a8e3305a95ca47176bf4': ('DIRECT_COMPANY_EVENT', 'Bài nguồn nêu lịch báo cáo quý của UNH; tiêu đề chỉ thông báo sắp công bố, chưa nêu kết quả.', 'https://www.benzinga.com/trading-ideas/previews/26/10/62305174/dow-jones-industrial-average-gets-spotlight-5-earnings-reports-representing-25-of-etfs-assets-on-deck'),
 '123f0629272ccfc60b57beb6': ('DIRECT_COMPANY_EVENT', 'Cùng bài nguồn, nêu lịch báo cáo quý của JPM; chưa nêu kết quả hay dự báo cụ thể.', 'https://www.benzinga.com/trading-ideas/previews/26/10/62305174/dow-jones-industrial-average-gets-spotlight-5-earnings-reports-representing-25-of-etfs-assets-on-deck'),
 '8e745d80568e741fab3169b7': ('SECTOR_MACRO_SPILLOVER', 'Bài điểm thị trường nêu nhóm năng lượng và CVX; giá trong phiên chưa chứng minh thay đổi giá trị cơ bản.', 'https://www.benzinga.com/etfs/sector-etfs/26/09/62083340/growth-leads-sectors-in-wednesday-trading-as-defensives-trail'),
}


def main():
    source=ROOT/'dev_codex_ai_review_v3.csv'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=EXPECTED_V3:
        raise ValueError('AI_DRAFT_V3_HASH_CHANGED')
    with source.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); rows=list(reader); fields=reader.fieldnames+['source_review_note','event_evidence_status']
    if len(rows)!=180 or not set(CASES).issubset({x['task_id'] for x in rows}):
        raise ValueError('AI_DRAFT_TASK_MISMATCH')
    for r in rows:
        ident=r['task_id'];r['source_review_note']='';r['event_evidence_status']=r['event_cluster_status']
        if ident in CASES:
            relevance,note,url=CASES[ident]
            r.update(target_relevance_ai=relevance,textual_tone_ai='NEUTRAL',economic_implication_ai='AMBIGUOUS_MIXED',
                event_category_ai='EARNINGS_GUIDANCE' if relevance=='DIRECT_COMPANY_EVENT' else 'MACRO_SECTOR',
                category_status='AI_SOURCE_REVIEWED_NEEDS_HUMAN',event_cluster_candidate='AI_SINGLE_'+ident,
                event_cluster_status='SINGLETON_UNVERIFIED',event_evidence_status='SINGLETON_UNVERIFIED',
                review_priority='HIGH',review_status='AI_SOURCE_REVIEWED_NEEDS_HUMAN',
                rationale_note=note,change_note=note,source_review_note=note+' '+url)
        elif r['event_cluster_status']=='AI_LINKED_PAIR_REVIEW':
            r['event_evidence_status']='PRIMARY_SOURCE_SUPPORTS_PAIR_NEEDS_HUMAN'
            url=('https://am.jpmorgan.com/jp/en/asset-management/institutional/about-us/qia-jpmorgan-20billion-strategic-partnership/'
                 if r['ticker']=='JPM' else 'https://australia.chevron.com/news/2026/chevron-signs-new-wa-gas-supply-agreement-with-south32')
            r['source_review_note']='Thông cáo doanh nghiệp phù hợp về đối tác, thời điểm và giá trị/khối lượng: '+url
        if ident in {'1b09ada84ab1febe77b2cdf4','a0924a532855a41bf11f532c'}:
            r['event_evidence_status']='SAME_HURRICANE_DIFFERENT_UPDATE_NEEDS_HUMAN'
            r['review_priority']='HIGH'
            r['source_review_note']='Cùng bão nhưng rút nhân sự/đóng cơ sở khác chi tiết; không tự gộp sự kiện.'
    validate_draft(rows)
    target=ROOT/'dev_codex_ai_review_v4.csv'
    with target.open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print(json.dumps({'rows':len(rows),'output':str(target),'unresolved_relevance':sum(not x['target_relevance_ai'] for x in rows),
        'ai_draft_not_gold':True,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__':
    main()
