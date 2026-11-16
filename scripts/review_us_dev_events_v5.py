"""Record an AI review of event candidates within the frozen dev sample."""
from __future__ import annotations
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path('artifacts/evaluations/us_eval_20261115_v2')
EXPECTED_V4 = 'b4930ecaa9633cc987d56acb37a6eaefc38c12600407bea1267749f8e8979aec'

# Ordered candidate entries are bound to task IDs to avoid applying judgments to a different sort.
DECISIONS = {
 frozenset(('cac63cad497516be66ab8802','01de7bf5fec68d9b7f89ef05')): ('DISTINCT_DISCLOSURES','Các thông báo ASOS khác ngày và ID nguồn; không tự gộp.'),
 frozenset(('896af970a75709ba1a702538','01de7bf5fec68d9b7f89ef05')): ('DISTINCT_DISCLOSURES','Các thông báo ASOS khác ngày và ID nguồn; không tự gộp.'),
 frozenset(('896af970a75709ba1a702538','cac63cad497516be66ab8802')): ('DISTINCT_DISCLOSURES','Các thông báo ASOS khác ngày và ID nguồn; không tự gộp.'),
 frozenset(('7b1b438a38b37051a1574cf4','f9456d71559db8857fa0f2ea')): ('SAME_EVENT_SOURCE_SUPPORTED','Cùng thỏa thuận JPM/QIA 20 tỷ USD; có thông cáo JPM.'),
 frozenset(('0c8e484cd9cc3de3b445e85d','759b260c9b0a3ec4b17adfde')): ('SAME_EVENT_SOURCE_SUPPORTED','Cùng hợp đồng Chevron/South32; có thông cáo Chevron.'),
 frozenset(('a0924a532855a41bf11f532c','1b09ada84ab1febe77b2cdf4')): ('SAME_INCIDENT_DIFFERENT_UPDATE_UNRESOLVED','Cùng bão Isaias; khác cập nhật về rút người và dừng cơ sở, cần định nghĩa độ rộng sự kiện.'),
 frozenset(('18dd42da97f95a324cf3c54e','a2f7880dfcc77fafe59e5c2f')): ('RELATED_INVESTMENTS_UNRESOLVED','Cùng Bắc Carolina nhưng số tiền và thời điểm khác; chưa đủ nguồn để kết luận quan hệ đầu tư.'),
 frozenset(('b0fe5ea39be8c676538f4de5','ff29a93e5d013d29b1f3c51d')): ('RELATED_DISTINCT_DRUG_ANALYSES','Foundayo và Zepbound là hai thuốc; hai tiêu đề đề cập các phân tích khác nhau, cần xác nhận nghiên cứu.'),
}


def main():
    source=ROOT/'dev_codex_ai_review_v4.csv'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=EXPECTED_V4:
        raise ValueError('AI_DRAFT_V4_HASH_CHANGED')
    with source.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); labels=list(reader); fields=reader.fieldnames
    with (ROOT/'dev_event_pair_candidates_v5.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); pairs=list(reader); pair_fields=reader.fieldnames+['ai_pair_decision','decision_note']
    if len(labels)!=180 or len(pairs)!=15:
        raise ValueError('UNEXPECTED_INPUT_SIZE')
    by_id={r['task_id']:r for r in labels}
    if len(by_id)!=180 or any(r['a_id'] not in by_id or r['b_id'] not in by_id for r in pairs):
        raise ValueError('TASK_BINDING_MISMATCH')
    seen=set(); neighbours=defaultdict(list)
    for pair in pairs:
        key=frozenset((pair['a_id'],pair['b_id']))
        if key in seen or len(key)!=2:
            raise ValueError('DUPLICATE_PAIR')
        seen.add(key)
        decision,note=DECISIONS.get(key,('DISTINCT_MARKET_UPDATE_OR_TARGET',
            'Nội dung khớp mẫu chung nhưng khác ngày, bên phân tích, doanh nghiệp mục tiêu hoặc chủ đề; cần người rà.'))
        pair.update(ai_pair_decision=decision,decision_note=note)
        neighbours[pair['a_id']].append(decision); neighbours[pair['b_id']].append(decision)
    if not set(DECISIONS)<=seen:
        raise ValueError('REVIEWED_PAIR_NOT_FOUND')
    new_fields=fields+['within_dev_review','within_dev_candidate_count','event_review_warning']
    for label in labels:
        if label['event_evidence_status']=='SINGLETON_UNVERIFIED':
            candidate_decisions=neighbours[label['task_id']]
            label['within_dev_candidate_count']=str(len(candidate_decisions))
            label['within_dev_review']='AI_COMPARED_WITHIN_SAMPLE_HAS_CANDIDATE' if candidate_decisions else 'AI_COMPARED_WITHIN_SAMPLE_NO_CANDIDATE'
            label['event_review_warning']='Chỉ so với các task trong mẫu và quy tắc tìm kiếm; không chứng minh đơn lẻ, cần người xác nhận.'
            if any('UNRESOLVED' in x for x in candidate_decisions):
                label['review_priority']='HIGH'
        else:
            label['within_dev_review']=label['event_evidence_status']
            label['within_dev_candidate_count']=str(len(neighbours[label['task_id']]))
            label['event_review_warning']='Nhóm sự kiện là gợi ý AI, cần người xác nhận; first mention chưa xác định.'
    for path,rows,fieldnames in ((ROOT/'dev_event_pairs_review_v5.csv',pairs,pair_fields),
                                  (ROOT/'dev_codex_ai_review_v5.csv',labels,new_fields)):
        with path.open('x',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fieldnames);writer.writeheader();writer.writerows(rows)
    print(json.dumps({'rows':len(labels),'pair_count':len(pairs),'pair_decisions':dict(Counter(x['ai_pair_decision'] for x in pairs)),
                      'singleton_review':dict(Counter(x['within_dev_review'] for x in labels if x['event_evidence_status']=='SINGLETON_UNVERIFIED')),
                      'status':'AI_PROVISIONAL_NEEDS_INDEPENDENT_HUMAN_REVIEW'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
