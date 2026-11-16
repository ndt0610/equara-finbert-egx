"""Add source-supported event judgments to an AI draft, not human gold."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.prepare_us_dev_review import validate_draft

ROOT = Path('artifacts/evaluations/us_eval_20261115_v2')
EXPECTED_V5 = 'd9a702b7db8168575454fa7a4fd9e446569932a63fb8948ffb7f59eda10bd079'
EXPECTED_PAIRS = '85b244a1727eecaa0ed79837395e3e659cbe2a52fdd536c401e6a20bae672116'
CAT = frozenset(('18dd42da97f95a324cf3c54e','a2f7880dfcc77fafe59e5c2f'))
CVX = frozenset(('a0924a532855a41bf11f532c','1b09ada84ab1febe77b2cdf4'))
LLY = frozenset(('b0fe5ea39be8c676538f4de5','ff29a93e5d013d29b1f3c51d'))
SOURCES = {
 CAT: ('DISTINCT_RELATED_SOURCE_SUPPORTED', '10 triệu USD đào tạo nhân lực; 1 tỷ USD nhà máy thiết bị. Thông báo liên quan nhưng khác nội dung và thời điểm.',
       'https://investors.caterpillar.com/news/news-details/2026/Caterpillar-Invests-in-North-Carolinas-Future-Manufacturing-Workforce/default.aspx ; https://www.caterpillar.com/en/news/corporate-press-releases/h/caterpillar-to-invest-one-billion-in-north-carolina-to-expand-cat-compact-manufacturing-capacity.html'),
 CVX: ('SAME_INCIDENT_DIFFERENT_UPDATES_SOURCE_SUPPORTED', 'Cùng ứng phó bão Isaias; một bản cập nhật dừng năm cơ sở, bài tổng hợp nhắc thông tin bốn cơ sở trước đó. Nhóm theo sự kiện nền nhưng không xóa khác biệt.',
       'https://www.marketscreener.com/news/chevron-hurricane-isaias-ce785ddcdb89f323 ; https://www.benzinga.com/trading-ideas/movers/26/10/62280322/shell-chevron-bp-pull-crews-as-hurricane-isaias-barrels-toward-gulf-coast-refineries'),
 LLY: ('DISTINCT_ANALYSES_SOURCE_SUPPORTED', 'Hai phân tích riêng: Foundayo so với semaglutide uống và Zepbound so với Wegovy HD.',
       'https://investor.lilly.com/node/54971/pdf ; https://investor.lilly.com/node/54976/pdf'),
}


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    src=ROOT/'dev_codex_ai_review_v5.csv'; pair_path=ROOT/'dev_event_pairs_review_v5.csv'
    if sha(src)!=EXPECTED_V5 or sha(pair_path)!=EXPECTED_PAIRS:
        raise ValueError('REVIEW_INPUT_HASH_CHANGED')
    with src.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); labels=list(reader); label_fields=reader.fieldnames+['v6_event_note']
    with pair_path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); pairs=list(reader); pair_fields=reader.fieldnames+['v6_decision','v6_note','v6_evidence']
    if len(labels)!=180 or len(pairs)!=15:
        raise ValueError('REVIEW_INPUT_SIZE_CHANGED')
    neighbours=defaultdict(list); present=set()
    for pair in pairs:
        key=frozenset((pair['a_id'],pair['b_id']))
        present.add(key)
        if key in SOURCES:
            verdict,note,evidence=SOURCES[key]
        else:
            verdict=pair['ai_pair_decision'];note=pair['decision_note'];evidence=''
        pair.update(v6_decision=verdict,v6_note=note,v6_evidence=evidence)
        for key_id in key: neighbours[key_id].append((verdict,note,evidence))
    if not set(SOURCES).issubset(present):
        raise ValueError('EXPECTED_PAIR_MISSING')
    by_id={row['task_id']:row for row in labels}
    if len(by_id)!=180:
        raise ValueError('DUPLICATE_TASK')
    for row in labels:
        ident=row['task_id']; row['v6_event_note']=''
        if ident in CVX:
            row['event_cluster_candidate']='AI_CVX_ISAIAS_202610'
            row['event_cluster_status']='AI_SAME_INCIDENT_DIFFERENT_UPDATES'
            row['event_evidence_status']='PRIMARY_SOURCE_INCIDENT_NEEDS_HUMAN'
            row['review_priority']='HIGH'
            row['v6_event_note']=SOURCES[CVX][1]
        elif ident in CAT:
            row['event_evidence_status']='DISTINCT_RELATED_PROGRAMS_SOURCE_SUPPORTED_NEEDS_HUMAN'
            row['review_priority']='HIGH'
            row['v6_event_note']=SOURCES[CAT][1]
        elif ident in LLY:
            row['event_evidence_status']='DISTINCT_DRUG_ANALYSES_SOURCE_SUPPORTED_NEEDS_HUMAN'
            row['v6_event_note']=SOURCES[LLY][1]
        if ident=='18dd42da97f95a324cf3c54e':
            row['rationale_note']='Tối đa 10 triệu USD đào tạo nhân lực, tách khỏi kế hoạch 1 tỷ USD xây năng lực; chi phí, lợi ích kinh tế chưa định lượng.'
            row['source_review_note']=SOURCES[CAT][2]
        if row['first_mention']:
            raise ValueError('FIRST_MENTION_NOT_VERIFIED')
    validate_draft(labels)
    fields=['row','task_id','ticker','headline','neighbour_count','ai_event_decisions','evidence','review_status']
    reviewed=[]
    for row in labels:
        if row['within_dev_review']!='AI_COMPARED_WITHIN_SAMPLE_HAS_CANDIDATE':
            continue
        matches=neighbours[row['task_id']]
        reviewed.append({'row':row['row'],'task_id':row['task_id'],'ticker':row['ticker'],'headline':row['headline'],
            'neighbour_count':len(matches),'ai_event_decisions':' | '.join(x[0]+': '+x[1] for x in matches),
            'evidence':' | '.join(x[2] for x in matches if x[2]),'review_status':'AI_REVIEWED_REQUIRES_HUMAN_CONFIRMATION'})
    if len(reviewed)!=17:
        raise ValueError('EXPECTED_17_CANDIDATES')
    for path,items,columns in ((ROOT/'dev_codex_ai_review_v6.csv',labels,label_fields),
                               (ROOT/'dev_event_pairs_review_v6.csv',pairs,pair_fields),
                               (ROOT/'dev_event_17_review_v6.csv',reviewed,fields)):
        with path.open('x',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(items)
    print(json.dumps({'status':'AI_PROVISIONAL_NOT_HUMAN_GOLD','dev_rows':len(labels),'candidate_groups_reviewed':len(reviewed),
        'pair_decisions':dict(Counter(x['v6_decision'] for x in pairs)), 'sha256':sha(ROOT/'dev_codex_ai_review_v6.csv')},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
