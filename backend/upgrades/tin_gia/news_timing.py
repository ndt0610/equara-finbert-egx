"""Describe which news can be compared with a daily close, without causal claims."""
from datetime import date, datetime
from zoneinfo import ZoneInfo


def annotate_timing(candidates: list[dict], price_date: str | None) -> dict:
    counts: dict[str, int] = {}
    cutoff = date.fromisoformat(price_date) if price_date else None
    for row in candidates:
        try:
            published = datetime.fromisoformat((row.get('published_at') or '').replace('Z', '+00:00'))
            if published.tzinfo is None:
                raise ValueError('timezone missing')
            day = published.astimezone(ZoneInfo('Africa/Cairo')).date()
        except (ValueError, TypeError):
            day = None
        if cutoff is None or day is None:
            status = 'unknown_timing'
            explanation = 'Chưa đủ ngày giá/ngày tin để đối chiếu thứ tự thời gian.'
        elif day > cutoff:
            status = 'after_price_date'
            explanation = 'Tin ra sau ngày giá hiện có; chưa quan sát được giá phản ứng sau tin.'
        elif day == cutoff:
            status = 'same_day_order_unverified'
            explanation = 'Tin cùng ngày giá; chưa có giờ đóng cửa đã xác minh để kết luận giá đã phản ứng.'
        else:
            status = 'before_price_date'
            explanation = 'Tin có trước ngày giá; đây chỉ là thứ tự thời gian, chưa chứng minh quan hệ nhân quả.'
        row['price_timing'] = {'status': status, 'explanation': explanation, 'price_date': price_date}
        counts[status] = counts.get(status, 0) + 1
    return {'price_date': price_date, 'counts': counts, 'causal_effect_estimated': False}
