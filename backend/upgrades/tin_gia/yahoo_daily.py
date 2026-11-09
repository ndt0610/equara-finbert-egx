"""Observed EGX daily bars via yfinance. This source never supplies an intraday quote."""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo


class YahooDailyError(RuntimeError):
    pass


def _fetch(symbol: str) -> dict:
    import yfinance as yf

    provider_symbol = symbol.removesuffix('.EGX') + '.CA'
    ticker = yf.Ticker(provider_symbol)
    frame = ticker.history(period='1y', interval='1d', auto_adjust=False, timeout=15)
    if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise YahooDailyError('Không nhận được lịch sử ngày hợp lệ.')
    metadata = ticker.get_history_metadata()
    if metadata.get('symbol') != provider_symbol or metadata.get('currency') != 'EGP' or metadata.get('exchangeName') != 'CAI':
        raise YahooDailyError('Mã, sàn hoặc tiền tệ Yahoo không khớp EGX/EGP.')
    bars = []
    cairo_today = datetime.now(ZoneInfo('Africa/Cairo')).date()
    for stamp, row in frame.iterrows():
        # A daily bar for today may still be forming. Until the exchange close is
        # independently verified, this adapter uses completed prior-date bars only.
        if stamp.date() >= cairo_today:
            continue
        close = float(row['Close'])
        if not math.isfinite(close) or close <= 0:
            raise YahooDailyError('Lịch sử có giá đóng cửa không hợp lệ.')
        adjusted = float(row.get('Adj Close', float('nan')))
        if not math.isfinite(adjusted) or adjusted <= 0:
            raise YahooDailyError('Nguồn thiếu giá điều chỉnh hợp lệ; chưa tính lợi suất cho nhãn.')
        bars.append({'date': stamp.date().isoformat(), 'close': str(Decimal(str(close))),
                     'adjusted_close': str(Decimal(str(adjusted)))})
    if len(bars) < 6:
        raise YahooDailyError('Chưa đủ sáu giá đóng cửa để so sánh năm phiên.')
    latest_date = datetime.fromisoformat(bars[-1]['date']).date()
    if (cairo_today - latest_date).days > 4:
        raise YahooDailyError('Giá đóng cửa cuối cùng đã cũ hơn bốn ngày lịch; không phát nhãn từ dữ liệu quá cũ.')
    now = datetime.now(timezone.utc).isoformat()
    last = Decimal(bars[-1]['close'])
    prev = Decimal(bars[-2]['close'])
    five = Decimal(bars[-6]['adjusted_close'])
    adjusted_last = Decimal(bars[-1]['adjusted_close'])
    return {
        'status': 'available', 'source': 'Yahoo Finance (daily via yfinance)',
        'source_docs': {'history': 'https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html'},
        'price_kind': 'daily_close', 'quote_values': {'last': str(last)},
        'as_of_date': bars[-1]['date'],
        'freshness': {'mode': 'prior_day_close', 'calendar_age_days': (cairo_today-latest_date).days,
                      'intraday': False, 'timestamp_precision': 'date'},
        'quote': {'badge': {'kind': 'delayed', 'text': 'Đóng cửa ngày ' + bars[-1]['date']},
                  'source_event_at': None, 'received_at': now},
        'daily_change': {'absolute': str(last-prev), 'fraction': str(last/prev-1),
                         'reference_close': bars[-2], 'basis': 'raw close vs previous available daily bar'},
        'five_session_change': {'fraction': str(adjusted_last/five-1), 'reference_close': bars[-6],
                                'basis': 'provider adjusted close vs fifth prior available daily bar'},
        'return_basis': 'Yahoo Adj Close; last five available completed daily bars',
        'history': bars, 'history_status': 'available', 'provider_calls': 1,
        'fetched_at': now,
        'warnings': ['Giá cuối ngày, không phải giá trong phiên. Ngày giá: ' + bars[-1]['date'] + '.',
                     'Yahoo qua yfinance là truy cập không chính thức; cần đối soát lịch phiên, cổ tức và chia tách trước nghiên cứu giao dịch.',
                     'Chưa có bid/ask nên chưa tính được giá mua hoặc bán thực thi.'],
    }


async def fetch_daily(symbol: str) -> dict:
    try:
        return await asyncio.to_thread(_fetch, symbol)
    except YahooDailyError:
        raise
    except Exception:
        raise YahooDailyError('Yahoo không trả lịch sử ngày dùng được trong lượt này.') from None
