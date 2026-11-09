# [CHẨN ĐOÁN] EODHD có tin cho mã Ai Cập không? Google News trả bao nhiêu tin? Tin có phải lấy lúc này không?
# Dán vào MỘT ô Colab mới và chạy. Không cần chạy ô nào khác, không cần file zip.
# Khóa EODHD đọc từ Colab Secrets (tên EODHD_API_TOKEN) và KHÔNG bao giờ được in ra.
# Tốn khoảng 10 đến 20 lượt EODHD (2 request; gói Free có 20 lượt/ngày cộng 500 lượt thưởng). Google News miễn phí.
import json, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

NOW = datetime.now(timezone.utc)
VN = timezone(timedelta(hours=7))
print("Giờ chạy ô này:", NOW.astimezone(VN).strftime("%d/%m/%Y %H:%M:%S"), "(giờ VN)\n")


def http_get(url, timeout=20):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read(), round((time.perf_counter() - started) * 1000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), round((time.perf_counter() - started) * 1000)
    except Exception as exc:  # không in nội dung lỗi vì có thể chứa địa chỉ kèm khóa
        return None, type(exc).__name__.encode(), round((time.perf_counter() - started) * 1000)


# ---------- 1. EODHD: so mã Mỹ (đối chứng) với mã Ai Cập, cùng khóa, cùng lúc ----------
print("=== 1. EODHD News API ===")
try:
    from google.colab import userdata
    _key = userdata.get("EODHD_API_TOKEN")
except Exception:
    _key = None

eodhd = {}
if not _key:
    print("KHÔNG đọc được Secret EODHD_API_TOKEN, nên phần 1 không gửi request nào tới EODHD.")
    print("Cách bật: bấm biểu tượng chìa khóa ở thanh bên trái Colab, bật 'Notebook access' cho EODHD_API_TOKEN")
    print("(mỗi notebook mới phải bật lại), rồi chạy lại ô này.")
else:
    for symbol in ("AAPL.US", "COMI.EGX"):
        url = "https://eodhd.com/api/news?" + urllib.parse.urlencode({"s": symbol, "limit": 3, "fmt": "json", "api_token": _key})
        code, body, ms = http_get(url)
        text = body.decode("utf-8", "replace").replace(_key, "***")
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, list):
            eodhd[symbol] = len(data)
            print(f"{symbol}: HTTP {code}, {len(data)} tin, {ms} ms")
            for row in data[:3]:
                print("    ", str(row.get("date", ""))[:16], "|", str(row.get("title", ""))[:100])
        else:
            eodhd[symbol] = None
            print(f"{symbol}: HTTP {code}, không phải danh sách tin. Nội dung (đã che khóa): {text[:200]}")
    _key = None

if eodhd:
    us, eg = eodhd.get("AAPL.US"), eodhd.get("COMI.EGX")
    # Chỉ nói điều phép thử này chứng minh được, không suy ra nguyên nhân.
    if us and eg == 0:
        print("=> Cùng khóa, cùng lúc: AAPL.US có tin, COMI.EGX trả 0 tin.")
        print("   Chứng minh được: khóa hợp lệ, còn lượt, và lấy được tin cho ít nhất một mã. Truy vấn COMI.EGX lúc này không có kết quả.")
        print("   Chưa chứng minh được: EODHD thiếu tin về mã Ai Cập, hay gói của bạn không mở tin cho sàn EGX. Trang EODHD không công bố điều này.")
    elif us == 0 and eg == 0:
        print("=> Cả hai mã đều 0 tin. Chưa đủ căn cứ để quy cho gói tài khoản hay cho mã EGX.")
    elif eg:
        print("=> COMI.EGX có tin lúc này. Web app sẽ dùng EODHD trước, đúng như bài báo.")
    else:
        print("=> Có lỗi HTTP (401 = khóa sai, 402 = hết lượt trong ngày). Xem mã HTTP ở trên.")

# ---------- 2. Google News RSS: đúng truy vấn web app đang dùng, đếm tin sau lọc ----------
print("\n=== 2. Google News RSS (không cần khóa) ===")
COMPANIES = {
    "COMI.EGX": ("Commercial International Bank", ("COMI", "CIB", "Commercial International Bank")),
    "ETEL.EGX": ("Telecom Egypt", ("ETEL", "Telecom Egypt")),
    "FWRY.EGX": ("Fawry", ("FWRY", "Fawry")),
}
CUTOFF = NOW - timedelta(days=90)


def google_news(query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    code, body, ms = http_get(url)
    items = []
    if code == 200:
        for node in ET.fromstring(body).iter("item"):
            try:
                published = parsedate_to_datetime(node.findtext("pubDate"))
            except Exception:
                published = None
            items.append((node.findtext("title") or "", node.findtext("description") or "", published))
    return url, code, ms, items


def kept_after_filter(items, aliases):
    return [i for i in items
            if any(a.casefold() in f"{i[0]} {i[1]}".casefold() for a in aliases)
            and (i[2] is None or i[2] >= CUTOFF)]


for symbol, (name, aliases) in COMPANIES.items():
    url, code, ms, items = google_news(f'"{name}" Egypt EGX stock when:90d')
    kept = kept_after_filter(items, aliases)
    dates = [i[2] for i in kept if i[2]]
    newest = max(dates).astimezone(VN).strftime("%d/%m %H:%M") if dates else "không có"
    wide_url, wide_code, _, wide_items = google_news(f'"{name}" when:90d')
    wide_kept = kept_after_filter(wide_items, aliases)
    print(f"{symbol}: HTTP {code}, {ms} ms | truy vấn web app: feed trả {len(items)}, giữ {len(kept)} tin, mới nhất đăng {newest} (giờ VN)")
    print(f"          truy vấn rộng hơn (chỉ để đo, web app chưa dùng): HTTP {wide_code}, giữ {len(wide_kept)} tin")
    for title, _, published in sorted(kept, key=lambda i: i[2] or CUTOFF, reverse=True)[:2]:
        print("    ", published.astimezone(VN).strftime("%d/%m") if published else "--/--", "|", title[:100])
    print("     Mở đúng truy vấn này trên trình duyệt để so:", url)

print("\nBài báo yêu cầu 10–15 tiêu đề cho một mã (micro + macro). Chép toàn bộ kết quả ô này gửi lại để chốt cách xử lý.")
