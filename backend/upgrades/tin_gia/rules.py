"""Explainable, experimental holder rules. No forecast or causal-effect claim."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

VERSION = 'holder-news-price-rules-2'
LABELS = {'buy_strong': 'Mua mạnh', 'buy': 'Mua', 'hold': 'Giữ', 'sell': 'Bán', 'sell_strong': 'Bán mạnh'}


def quantile(values, p):
    values = sorted(values)
    i = (len(values)-1)*p
    lo = int(i)
    return values[lo] + (values[min(lo+1, len(values)-1)]-values[lo])*(i-lo)


def _classify_detail(score, move, normal, extreme, effective_n, moderate=.2, strong=.6):
    if score >= moderate:
        if move > normal:
            return ('hold', 'Tin tích cực nhưng giá đã tăng mạnh so với lịch sử: quy tắc tránh mua đuổi.',
                    {'code': 'positive_avoid_chasing', 'title': 'Tin tích cực nhưng giá đã tăng quá ngưỡng thường gặp',
                     'condition': 'Điểm tin từ +0,20 trở lên và mức tăng 5 phiên lớn hơn ngưỡng B của mã.',
                     'meaning': 'Quy tắc dừng ở Giữ để tránh mua đuổi; đây không phải dự báo giá sẽ giảm.'})
        if move < -normal:
            return ('hold', 'Tin tích cực nhưng giá giảm mạnh: hai bằng chứng trái chiều, giữ vị thế theo quy tắc chờ.',
                    {'code': 'positive_price_conflict', 'title': 'Tin tích cực nhưng giá giảm quá ngưỡng thường gặp',
                     'condition': 'Điểm tin từ +0,20 trở lên và mức giảm 5 phiên lớn hơn ngưỡng B của mã.',
                     'meaning': 'Tin và giá đang trái chiều nên quy tắc chọn Giữ để chờ thêm dữ liệu.'})
        if score >= strong and move > 0 and effective_n >= 3:
            return ('buy_strong', 'Tin tích cực mạnh, nhiều nhóm tin và giá tăng chưa vượt vùng lịch sử thường gặp.',
                    {'code': 'buy_strong', 'title': 'Đủ ba điều kiện Mua mạnh',
                     'condition': 'Điểm tin từ +0,60; giá 5 phiên tăng nhưng không vượt B; có ít nhất 3 nhóm tin hiệu dụng.',
                     'meaning': 'Đây là nhãn theo quy tắc thử nghiệm, chưa được chứng minh có lợi nhuận tốt hơn.'})
        return ('buy', 'Tin nghiêng tích cực và giá chưa tăng mạnh hoặc giảm mạnh trái chiều.',
                {'code': 'buy', 'title': 'Tin tích cực, giá chưa vượt ngưỡng tăng/giảm mạnh',
                 'condition': 'Điểm tin từ +0,20; giá 5 phiên nằm trong khoảng −B đến +B, nhưng chưa đủ mọi điều kiện Mua mạnh.',
                 'meaning': 'Với người đang nắm giữ, Mua nghĩa là quy tắc cho phép cân nhắc mua thêm.'})
    if score <= -moderate:
        if move < -normal:
            if score <= -strong and effective_n >= 3:
                return ('sell_strong', 'Tin tiêu cực mạnh, nhiều nhóm tin và giá xác nhận giảm đáng kể.',
                        {'code': 'sell_strong', 'title': 'Đủ ba điều kiện Bán mạnh',
                         'condition': 'Điểm tin từ −0,60 trở xuống; giá giảm quá B; có ít nhất 3 nhóm tin hiệu dụng.',
                         'meaning': 'Đây là nhãn theo quy tắc thử nghiệm, chưa được chứng minh có lợi nhuận tốt hơn.'})
            return ('sell', 'Tin tiêu cực đi cùng mức giảm đáng kể so với lịch sử.',
                    {'code': 'sell', 'title': 'Tin tiêu cực, giá giảm quá ngưỡng thường gặp',
                     'condition': 'Điểm tin từ −0,20 trở xuống và mức giảm 5 phiên vượt B.',
                     'meaning': 'Với người đang nắm giữ, Bán nghĩa là quy tắc cho phép cân nhắc giảm vị thế.'})
        return ('hold', 'Tin tiêu cực nhưng giá chưa giảm đáng kể: quy tắc chờ phản ứng rõ hơn.',
                {'code': 'negative_no_confirmation', 'title': 'Tin tiêu cực nhưng giá chưa giảm quá ngưỡng thường gặp',
                 'condition': 'Điểm tin từ −0,20 trở xuống, nhưng mức giảm 5 phiên chưa vượt B.',
                 'meaning': 'Tin và giá chưa cùng xác nhận hướng giảm nên quy tắc chọn Giữ.'})
    return ('hold', 'Điểm tin nằm trong vùng cân bằng theo quy ước; chưa có hướng tin đủ rõ để đổi vị thế.',
            {'code': 'neutral_sentiment', 'title': 'Điểm tin nằm trong vùng cân bằng',
             'condition': 'Điểm tin lớn hơn −0,20 và nhỏ hơn +0,20.',
             'meaning': 'Đây là nhánh quyết định Giữ; biến động giá vẫn được trình bày để đối chiếu, nhưng không đổi nhánh này.'})


def classify(score, move, normal, extreme, effective_n, moderate=.2, strong=.6):
    """Compatibility wrapper used by the sensitivity analysis."""
    label, explanation, _ = _classify_detail(score, move, normal, extreme, effective_n, moderate, strong)
    return label, explanation


def evaluate_rules(price, news):
    result = {'status': 'insufficient_data', 'label': None, 'method_version': VERSION,
              'method_status': 'experimental_rules_not_backtested', 'reason_codes': [],
              'method_note': 'Nhãn cho người đang nắm cổ phiếu: Mua là mua thêm, Bán là giảm vị thế. Quy tắc thử nghiệm chưa chứng minh hiệu quả đầu tư.',
              'agreed_method': ['Giá: so đóng cửa với năm hàng phiên trước, so mức biến động với lịch sử riêng của mã.',
                                'Tin: chỉ tin trực tiếp có ngày trước ngày giá; gom tiêu đề gần trùng thành nhóm tạm, mỗi nhóm một điểm.',
                                'Điểm nhóm = P(tích cực) − P(tiêu cực); giảm trọng số theo tuổi tin, vĩ mô chỉ làm bối cảnh.',
                                'Áp bảng quy tắc và báo độ nhạy; không diễn giải tương quan thành tác động nhân quả.']}
    if news.get('data_origin') == 'illustrative':
        result['status'] = 'illustrative_no_label'
        result['message'] = 'Tin đang ở dữ liệu minh họa; không ghép với giá thật để tạo nhãn.'
        return result
    bars = price.get('history', [])
    if price.get('status') != 'available' or price.get('price_kind') != 'daily_close' or len(bars) < 66:
        result['message'] = 'Cần giá ngày và ít nhất 60 biến động năm hàng phiên quá khứ để dựng vùng so sánh của mã.'
        return result
    cutoff = date.fromisoformat(bars[-1]['date'])
    closes = [float(x.get('adjusted_close', x['close'])) for x in bars]
    # Exclude latest move from its own reference distribution.
    past = [abs(closes[i]/closes[i-5]-1) for i in range(5, len(closes)-1)]
    normal, extreme = quantile(past, .75), quantile(past, .90)
    move = closes[-1]/closes[-6]-1
    groups, excluded = [], []
    for row in sorted(news.get('candidate_ledger', {}).get('candidates', []), key=lambda r: (r.get('published_at') or '', r.get('title') or '')):
        why = None
        if row.get('scope') != 'company_candidate': why = 'context_only'
        elif row.get('processing_state') in ('excluded', 'grouped'): why = 'excluded_or_duplicate'
        elif row.get('reason_code') != 'pending_event_review' or not row.get('matched_alias'): why = 'entity_not_verified'
        elif not row.get('probabilities'): why = 'unscored_or_entity_ambiguous'
        try:
            stamp = datetime.fromisoformat((row.get('published_at') or '').replace('Z', '+00:00'))
            if stamp.tzinfo is None: raise ValueError()
            day = stamp.astimezone(ZoneInfo('Africa/Cairo')).date()
            age = (cutoff-day).days
        except (ValueError, TypeError):
            age, day = None, None
            why = why or 'unknown_date'
        if age is not None and not 1 <= age <= 30: why = why or 'outside_prior_30_calendar_days'
        if why:
            excluded.append({'candidate_id': row.get('candidate_id'), 'reason': why})
            continue
        p = row['probabilities']
        score = float(p['positive'])-float(p['negative'])
        words = set(re.findall(r'\w+', row.get('title','').lower()))
        match = next((g for g in groups if abs((day-date.fromisoformat(g['date'])).days) <= 3
                      and words and len(words & g['_words'])/len(words | g['_words']) >= .8), None)
        member = {'candidate_id': row.get('candidate_id'), 'title': row.get('title'), 'url': row.get('url'), 'score': score}
        if match:
            match['members'].append(member)
            # Earliest publication prevents a reprint from refreshing old news.
            if day.isoformat() < match['date']:
                match['date'], match['age_days'] = day.isoformat(), age
        else:
            groups.append({'group_id': f'g{len(groups)+1}', 'date': day.isoformat(), 'age_days': age,
                           '_words': words, 'members': [member], 'grouping_status': 'provisional_headline_similarity'})
    if not groups:
        result.update(message='Chưa có nhóm tin trực tiếp đủ ngày và xác suất trong 30 ngày trước ngày giá; không biến thiếu tin thành nhãn Giữ.', excluded=excluded)
        return result
    for g in groups:
        g.pop('_words')
        g['score'] = sum(m['score'] for m in g['members'])/len(g['members'])
    def score_at(half_life):
        weights = [2**(-g['age_days']/half_life) for g in groups]
        return sum(w*g['score'] for w,g in zip(weights,groups))/sum(weights), sum(weights)**2/sum(w*w for w in weights)
    score, neff = score_at(7)
    freshness = sum(2**(-g['age_days']/7) for g in groups)/len(groups)
    evidence_score = score * freshness
    total_weight = sum(2**(-g['age_days']/7) for g in groups)
    for g in groups:
        g['normalized_weight'] = 2**(-g['age_days']/7)/total_weight
        g['score_contribution'] = g['normalized_weight']*g['score']
        previous = [i for i, bar in enumerate(bars) if bar['date'] < g['date']]
        anchor = previous[-1] if previous else None
        g['price_before_news'] = bars[anchor] if anchor is not None else None
        g['observed_reaction'] = {}
        if anchor is not None:
            after = [i for i, bar in enumerate(bars) if bar['date'] > g['date']]
            for horizon in (1, 3, 5):
                endpoint = after[horizon-1] if len(after) >= horizon else None
                g['observed_reaction'][f'{horizon}_sessions'] = (
                    {'end_date': bars[endpoint]['date'],
                     'return': closes[endpoint]/closes[anchor]-1,
                     'reference_date': bars[anchor]['date']}
                    if endpoint is not None else None
                )
        g['return_interpretation'] = 'Fixed 1/3/5 completed bars after publication date; same-day timing is excluded. Observed association only, not a causal effect. Windows overlap.'
    label, explanation, rule_path = _classify_detail(evidence_score, move, normal, extreme, neff)
    variants = []
    for half in (3.5, 7, 14):
        s,n = score_at(half)
        for moderate,strong in ((.15,.5),(.2,.6),(.25,.7)):
            f = sum(2**(-g['age_days']/half) for g in groups)/len(groups)
            alternate,_ = classify(s*f,move,normal,extreme,n,moderate,strong)
            variants.append({'half_life_days':half,'moderate':moderate,'strong':strong,'label':LABELS[alternate]})
    risk = 'extreme' if abs(move) > extreme else 'elevated' if abs(move) > normal else 'ordinary'
    result['risk'] = {'level':risk,'message': 'Biến động vượt ngưỡng lịch sử; nhãn Giữ không có nghĩa rủi ro thấp.' if risk != 'ordinary' else 'Biến động chưa vượt B; đây không phải bảo đảm an toàn.'}
    result['price_basis'] = price.get('return_basis', 'synthetic_or_legacy_close')
    result.update(status='experimental', label=LABELS[label], message=explanation, rule_path=rule_path,
                  groups=groups, excluded=excluded,
                  inputs={'sentiment':evidence_score,'raw_sentiment':score,'freshness':freshness,'group_count':len(groups),'five_session_return':move,'normal_move':normal,'extreme_move':extreme,'effective_groups':neff,'price_date':cutoff.isoformat()},
                  parameters={'window_calendar_days':30,'half_life_calendar_days':7,'sentiment_moderate':.2,'sentiment_strong':.6,
                              'normal_absolute_return_quantile':.75,'extreme_absolute_return_quantile':.90,'strong_min_effective_groups':3,
                              'similarity_jaccard':.8,'group_max_date_difference_days':3,
                              'evidence_rule':'D = S * F = sum(w_g * s_g) / number_of_groups; F = mean(w_g)',
                              'basis':'Initial design conventions, not optimized or validated EGX thresholds'},
                  sensitivity={'stable':len({v['label'] for v in variants})==1,'variants':variants},
                  limitations=['Nhóm tiêu đề gần trùng chưa phải sự kiện đã xác minh; có thể gộp nhầm hoặc bỏ sót trùng.',
                               'Giữ do bằng chứng trái chiều là quyết định chờ của quy tắc, không khẳng định rủi ro thấp.',
                               'Lợi suất dùng giá điều chỉnh do nguồn cung cấp nếu có; chưa đối soát độc lập sự kiện doanh nghiệp, chưa trừ phí.',
                               'Phân vị lịch sử mô tả mức biến động, không chứng minh giá đã quá đắt/rẻ hoặc sẽ đảo chiều.'])
    return result
