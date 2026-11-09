"""Phần C, bước 1: luật lọc "tin này có nói về đúng doanh nghiệp không" (bản 3).

Chỉ tab "Danh mục theo vốn" và API v2 dùng luật này. Tab 1, tab 2 và API gốc vẫn dùng bộ lọc
của bản tái dựng (`backend.providers.news.old_alias_filter`), để còn đối chứng.

Luật bản 3, xét lần lượt; bản ghi bị loại ở bước đầu tiên không đạt và ghi đúng một lý do (lý do đầu tiên khớp,
không phải mọi lý do; `pattern_flags` cho biết thêm tiêu đề có khớp mẫu trang dữ liệu hay thể thao không):

1. Cũ hơn cửa sổ tin (mặc định 90 ngày, giống bản tái dựng). Tin không có ngày, hoặc ngày không đọc được,
   vẫn được giữ, giống bản tái dựng, và giao diện ghi "không rõ ngày".
1b. Thiếu tiêu đề (rỗng sau khi bỏ dấu câu): FinBERT không có chữ để chấm. (Mới ở bản 3.)
2. Bản lặp trong cùng lượt. Khóa: URL đã chuẩn hóa (chữ thường ở scheme/host, bỏ `?…`, `#…` và dấu "/" cuối);
   chỉ khi bản ghi không có URL mới dùng tiêu đề đã bỏ dấu câu. Hai URL khác nhau không bao giờ bị gộp, kể cả khi
   cùng tiêu đề. Bản ghi quá hạn (bước 1) hoặc thiếu tiêu đề (bước 1b) không vào nhóm trùng, nên không che
   được bản dùng được. Mỗi nhóm giữ đúng một bản: bản có ngày đọc được mới nhất; bản không ngày chỉ được
   chọn khi cả nhóm không có ngày; hòa thì bậc truy vấn thấp hơn, rồi tiêu đề, rồi URL, rồi các trường còn
   lại. Kết quả không phụ thuộc thứ tự bản ghi đến.
3. Tên công ty hoặc alias không có trong TIÊU ĐỀ. Lý do: FinBERT chỉ chấm tiêu đề, nên tiêu đề
   phải nói về công ty. So theo nguyên từ, không phân biệt hoa thường: "CIB" khớp "CIB's" nhưng
   "COMI" không khớp "coming" (bộ lọc cũ so chuỗi con nên khớp cả "coming").
3b. Tên chỉ khớp một alias "trùng tên" mà tiêu đề không nhắc Ai Cập. Ví dụ thật: "ADIB" và
   "Abu Dhabi Islamic Bank" còn là tên ngân hàng mẹ niêm yết ở Abu Dhabi; tin "ADIB markets new
   AT1 as call date looms" là tin của ngân hàng mẹ, không phải ADIB Egypt trên EGX. (Mới ở bản 2.)
4. Tiêu đề có từ khóa thể thao (một danh sách chung cho mọi mã). Ví dụ: Telecom Egypt còn là tên
   một câu lạc bộ bóng đá.
5. Tiêu đề là trang dữ liệu chứ không phải tin: trang báo giá, biểu đồ, dữ liệu lịch sử. Ví dụ thật
   ngày 03/11: "... Equity Price and Quote - London Stock Exchange". Ví dụ thật ngày 04/11 (Codex, Windows,
   truy vấn rộng): "Fawry For Banking Technology And Electronic Payment Estimates – EGX:FWRY - TradingView";
   chỉ loại khi tên trang đứng ngay trước "– SÀN:MÃ", không loại theo chữ "estimates" đứng một mình.

Bản 2 (04/11/2026) sửa các lỗi logic đã biết từ bản 1, trước khi có bất kỳ phiếu gán nhãn nào: bản 1
giữ tin của ngân hàng mẹ ADIB ở UAE cho mã ADIB Egypt, và giữ trang dữ liệu TradingView "… Estimates –
EGX:FWRY". Bản 2 cũng thêm vài từ chỉ có trong tin thể thao ("round of 32", "relegation") và luật riêng
cho tin vĩ mô (`judge_macro`).

Bản 3 (04/11/2026) chỉ sửa bước loại trùng, theo phát hiện của Codex: bản 2 ghi khóa vào tập đã thấy TRƯỚC khi
xét tuổi, nên một bản quá hạn đến trước có thể che bản còn hạn cùng khóa, và kết quả phụ thuộc thứ tự bản ghi;
tiêu đề rỗng bị ghi là "trùng". Bản 3 xét thiếu tiêu đề trước trùng, để một bản không tiêu đề không che
được bản có tiêu đề cùng URL. Các luật tên, alias, thể thao, trang dữ liệu và tin vĩ mô giữ nguyên. Tab 1, tab 2
và ô "cách bài báo" vẫn dùng `backend.providers.news.deduplicate` của bản tái dựng, không đổi.

Vì sao chỉ ADIB cần nhắc Ai Cập: tên dùng để truy vấn ("Abu Dhabi Islamic Bank Egypt") bắt đầu bằng đúng
tên đầy đủ của ngân hàng mẹ, một tổ chức có nhiều tin riêng, nên truy vấn có thể kéo tin của ngân hàng mẹ
về. "CIB" không cần: truy vấn dùng "Commercial International Bank", và tin thật ngày 03/11 "CIB Commits Up
to USD 38.2M to MNT-Halan’s Proposed Offering" là tin đúng của COMI mà không có chữ nào chỉ Ai Cập.

Giới hạn đã biết của bản 2 (phải đo bằng phiếu gán nhãn trước khi sửa, không tự chỉnh theo cảm giác):
- Alias "E-finance" cũng là một danh từ chung ("Nigeria's e-finance push" vẫn được giữ). Chưa thấy ca
  thật nào trong dữ liệu; truy vấn dùng tên pháp lý đầy đủ. Chưa bắt nhắc Ai Cập, phải đo trước.
- Tiêu đề ADIB có chữ Ai Cập nhưng nói về ngân hàng mẹ ("ADIB, Egypt's sovereign fund sign MoU") vẫn giữ.
- Tin vĩ mô xét từ khóa trong tiêu đề: tin chính trị có một từ kinh tế vẫn giữ ("Egypt jails journalist
  over report on inflation"); tin kinh tế không có từ trong danh sách bị loại ("Egypt, UAE sign $35 billion
  Ras El-Hekma deal").
- Nhiều tiêu đề cùng một sự kiện (ví dụ cùng một đợt chào bán) vẫn được tính nhiều lần; chỉ bản lặp cùng
  khóa (bước 2) bị bỏ. Cùng một tin đăng ở hai báo có hai URL nên vẫn tính hai lần.
- Bản ghi ghi ngày "trong tương lai" (nguồn ghi sai ngày) được ưu tiên trong nhóm trùng vì là bản mới nhất.
- Hai bản cùng URL mà khác tiêu đề: chỉ tiêu đề của bản được chọn đi qua các luật sau.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from backend.providers.news import NewsItem, _canonical_url, _normalize_title, old_alias_filter

RULES_VERSION = "relevance-v3"

# Từ khóa thể thao chung cho mọi mã. Cố ý KHÔNG có "match" và "goal" vì tin kinh doanh hay dùng
# ("match expectations", "growth goal"). "league table" là bảng xếp hạng ngân hàng, không phải thể thao.
SPORTS_PATTERNS: tuple[str, ...] = (
    r"football",
    r"soccer",
    r"league(?!\s+tables?)",
    r"cup",
    r"fc",
    r"sc",
    r"club",
    r"stadium",
    r"striker",
    r"goalkeeper",
    r"coach",
    r"derby",
    r"basketball",
    r"volleyball",
    r"handball",
    r"olympics?",
    r"kick-?off",
    r"round of \d+",
    r"relegation",
    r"quarter-?finals?",
    r"semi-?finals?",
)

# Alias "trùng tên": khớp alias này thôi chưa đủ, tiêu đề phải nhắc Ai Cập (CONTEXT_PATTERNS).
# Khóa là alias viết thường; giá trị là lý do hiện cho người xem.
AMBIGUOUS_ALIASES: dict[str, str] = {
    "adib": "tên ngân hàng mẹ Abu Dhabi Islamic Bank niêm yết ở Abu Dhabi (UAE)",
    "abu dhabi islamic bank": "tên ngân hàng mẹ niêm yết ở Abu Dhabi (UAE)",
}
CONTEXT_PATTERNS: tuple[str, ...] = (r"egypt(?:ian)?", r"misr", r"egx", r"cairo", r"egp")

# Tin vĩ mô (judge_macro): tiêu đề phải có ít nhất một từ về kinh tế hay thị trường. Lý do: ô vĩ mô
# ghi "bối cảnh kinh tế Ai Cập"; ở cả hai lượt chạy thật 01/11 và 03/11, 2/2 tin vĩ mô là tin chính trị
# (tự do báo chí, viện trợ quân sự) và FinBERT chấm chúng −0,9. Danh sách là lựa chọn của nhóm, phải đo
# bằng phiếu gán nhãn. Cố ý không có "aid" (viện trợ quân sự), "deal" (thỏa thuận ngừng bắn), "gas" đơn
# lẻ (hơi cay).
ECONOMIC_PATTERNS: tuple[str, ...] = (
    r"econom(?:y|ic|ics|ies)",
    r"inflation",
    r"interest rates?",
    r"(?:policy|key|lending|deposit) rates?",
    r"rate (?:cut|hike|rise|decision)s?",
    r"central bank",
    r"cbe",
    r"monetary",
    r"fiscal",
    r"pound",
    r"currenc(?:y|ies)",
    r"exchange rates?",
    r"devaluation",
    r"imf",
    r"world bank",
    r"gdp",
    r"growth",
    r"recession",
    r"budget",
    r"deficit",
    r"debts?",
    r"bonds?",
    r"eurobonds?",
    r"sukuk",
    r"treasur(?:y|ies)",
    r"t-bills?",
    r"invest(?:ment|ments|ors?)?",
    r"fdi",
    r"exports?",
    r"imports?",
    r"trade",
    r"tariffs?",
    r"touris(?:m|ts?)",
    r"suez canal",
    r"remittances?",
    r"oil",
    r"natural gas",
    r"lng",
    r"fuel",
    r"subsid(?:y|ies)",
    r"prices?",
    r"stocks?",
    r"shares?",
    r"egx",
    r"bourse",
    r"markets?",
    r"banks?",
    r"banking",
    r"privati[sz]ation",
    r"ipos?",
    r"loans?",
    r"credit ratings?",
    r"moody'?s",
    r"fitch",
    r"s&p",
    r"unemployment",
    r"jobs",
    r"wages?",
    r"manufacturing",
    r"pmi",
    r"reserves",
    r"taxe?s?",
    r"vat",
    r"revenues?",
)

# Trang dữ liệu, không phải tin. "chart" chỉ xét dạng số ít vì "charts" còn là động từ
# ("Telecom Egypt charts growth plan").
NON_NEWS_PATTERNS: tuple[str, ...] = (
    r"quotes?",
    r"chart",
    r"(?:stock|share|price|interactive|live) charts",
    r"historical (?:data|prices?)",
    r"price history",
    r"seasonal returns?",
    r"seasonality",
    r"price today",
    r"dividend history",
    # Trang dữ liệu kiểu TradingView: tên trang ngay trước dấu gạch và mã sàn:mã ("… Estimates – EGX:FWRY").
    # Chỉ khớp đúng dạng này, nên tin "Fawry beats estimates" hay "Fawry (EGX:FWRY) beats estimates" vẫn giữ.
    r"(?:estimates|forecasts?|financials|statistics|key stats|profile|overview|technicals|dividends)\s*[–—|-]\s*[a-z]{2,10}:[a-z0-9._-]{1,12}",
)

REASONS: dict[str, str] = {
    "duplicate": "Bản lặp của một bản ghi khác trong lượt này (cùng URL; khi không có URL thì cùng tiêu đề)",
    "missing_title": "Thiếu tiêu đề, không có chữ để chấm",
    "stale": "Cũ hơn {days} ngày",
    "name_only_in_description": "Tên công ty chỉ có trong phần mô tả, không có trong tiêu đề",
    "name_not_in_title": "Tiêu đề không nhắc tên công ty",
    "ambiguous_name": "Tên “{alias}” còn là {note}; tiêu đề không nhắc Ai Cập",
    "sports": "Tin thể thao ({term})",
    "not_news_page": "Trang dữ liệu (báo giá, biểu đồ), không phải tin ({term})",
    "not_economic": "Tin chung về Ai Cập, tiêu đề không nói về kinh tế hay thị trường",
}


def _word_regex(patterns: Iterable[str]) -> re.Pattern[str]:
    joined = "|".join(f"(?:{p})" for p in patterns)
    return re.compile(rf"(?<![\w])(?:{joined})(?![\w])", re.IGNORECASE)


_SPORTS_RE = _word_regex(SPORTS_PATTERNS)
_NON_NEWS_RE = _word_regex(NON_NEWS_PATTERNS)
_CONTEXT_RE = _word_regex(CONTEXT_PATTERNS)
_ECONOMIC_RE = _word_regex(ECONOMIC_PATTERNS)


def alias_regex(aliases: Sequence[str]) -> re.Pattern[str]:
    """Khớp nguyên từ, không phân biệt hoa thường. Alias dài xếp trước để ghi đúng alias khớp."""
    ordered = sorted({a.strip() for a in aliases if a and a.strip()}, key=len, reverse=True)
    if not ordered:
        return re.compile(r"(?!x)x")
    return _word_regex(re.escape(a) for a in ordered)


def name_in_title(title: str, aliases: Sequence[str]) -> str | None:
    found = alias_regex(aliases).search(title or "")
    return found.group(0) if found else None


def unambiguous_match(title: str, aliases: Sequence[str]) -> tuple[str | None, str | None]:
    """(alias khớp, alias trùng tên đầu tiên). Trả alias khớp khi có ít nhất một alias không trùng tên,
    hoặc alias trùng tên đi kèm từ chỉ Ai Cập trong tiêu đề; nếu không, trả (None, alias trùng tên)."""
    matches = [m.group(0) for m in alias_regex(aliases).finditer(title or "")]
    if not matches:
        return None, None
    clear = [m for m in matches if m.casefold() not in AMBIGUOUS_ALIASES]
    if clear:
        return clear[0], None
    if _CONTEXT_RE.search(title or ""):
        return matches[0], None
    return None, matches[0]


@dataclass
class Verdict:
    keep: bool
    reason_code: str | None
    reason: str | None
    matched_alias: str | None
    old_filter_keep: bool  # bộ lọc của bản tái dựng có giữ tin này không (để so ở phép thử T1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _published(item: NewsItem) -> datetime | None:
    """Ngày đăng đọc được, theo UTC; None khi không có ngày hoặc ngày không đọc được."""
    if not item.published_at:
        return None
    try:
        moment = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _is_stale(item: NewsItem, now: datetime, lookback_days: int) -> bool:
    moment = _published(item)
    return moment is not None and (now - moment).total_seconds() / 86400 > lookback_days


def dedup_key(item: NewsItem) -> str:
    """Khóa loại trùng: URL đã chuẩn hóa; chỉ khi không có URL mới dùng tiêu đề đã bỏ dấu câu. "" = không có khóa."""
    return _canonical_url(item.url) or _normalize_title(item.title or "")


def _copy_order(item: NewsItem, rank: int) -> tuple[Any, ...]:
    """Thứ tự chọn bản giữ lại trong một nhóm trùng (nhỏ hơn = được chọn).

    Bản có ngày đọc được trước bản không ngày; trong bản có ngày, ngày mới nhất trước; hòa thì bậc truy vấn
    thấp hơn, rồi tiêu đề, rồi URL, rồi các trường còn lại. Mọi khóa đều lấy từ chính bản ghi, nên kết quả không
    phụ thuộc thứ tự đến (hai bản giống hệt nhau ở mọi trường thì chọn bản nào cũng như nhau).
    """
    moment = _published(item)
    return (
        0 if moment is not None else 1,
        -moment.timestamp() if moment is not None else 0.0,
        rank,
        _normalize_title(item.title or ""),
        item.title or "",
        item.url or "",
        item.source or "",
        item.published_at or "",
        item.description or "",
        item.kind or "",
        item.symbol or "",
    )


def _has_title(item: NewsItem) -> bool:
    return bool(_normalize_title(item.title or "").strip())


def _duplicate_flags(
    items: Sequence[NewsItem], ranks: Sequence[int], now: datetime, lookback_days: int
) -> tuple[list[bool], list[bool], list[bool]]:
    """(quá hạn, thiếu tiêu đề, trùng) cho từng bản ghi.

    Bản quá hạn hoặc thiếu tiêu đề không vào nhóm trùng, nên không che được bản dùng được cùng khóa.
    """
    stale = [_is_stale(item, now, lookback_days) for item in items]
    untitled = [not _has_title(item) for item in items]
    groups: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        key = "" if stale[index] or untitled[index] else dedup_key(item)
        if key:
            groups.setdefault(key, []).append(index)
    duplicate = [False] * len(items)
    for members in groups.values():
        if len(members) > 1:
            best = min(members, key=lambda i: _copy_order(items[i], ranks[i]))
            for index in members:
                duplicate[index] = index != best
    return stale, untitled, duplicate


def _judge_content(item: NewsItem, aliases: Sequence[str], old_keep: bool) -> Verdict:
    """Các luật sau bước quá hạn, thiếu tiêu đề và trùng: tên, alias trùng tên, thể thao, trang dữ liệu."""

    def reject(code: str, **fmt: Any) -> Verdict:
        return Verdict(False, code, REASONS[code].format(**fmt), None, old_keep)

    if name_in_title(item.title, aliases) is None:
        if item.description and name_in_title(item.description, aliases):
            return reject("name_only_in_description")
        return reject("name_not_in_title")
    matched, ambiguous = unambiguous_match(item.title, aliases)
    if matched is None:
        return reject("ambiguous_name", alias=ambiguous, note=AMBIGUOUS_ALIASES[ambiguous.casefold()])

    sports = _SPORTS_RE.search(item.title)
    if sports:
        return reject("sports", term=sports.group(0))

    non_news = _NON_NEWS_RE.search(item.title)
    if non_news:
        return reject("not_news_page", term=non_news.group(0))

    return Verdict(True, None, None, matched, old_keep)


def screen(
    items: Sequence[NewsItem],
    aliases: Sequence[str],
    *,
    now: datetime | None = None,
    lookback_days: int = 90,
    ranks: Sequence[int] | None = None,
) -> list[Verdict]:
    """Xét mọi ứng viên của một mã theo luật bản 3. Trả một Verdict cho từng bản ghi, đúng thứ tự đầu vào.

    `ranks`: bậc truy vấn của từng bản ghi (1, 2, ...), chỉ dùng để phá hòa khi chọn bản giữ trong nhóm trùng.
    """
    now = now or datetime.now(timezone.utc)
    ranks = list(ranks) if ranks is not None else [0] * len(items)
    if len(ranks) != len(items):
        raise ValueError("ranks phải dài bằng items")
    stale, untitled, duplicate = _duplicate_flags(items, ranks, now, lookback_days)
    verdicts: list[Verdict] = []
    for index, item in enumerate(items):
        old_keep = old_alias_filter(item, tuple(aliases))
        if stale[index]:
            verdicts.append(Verdict(False, "stale", REASONS["stale"].format(days=lookback_days), None, old_keep))
        elif untitled[index]:
            verdicts.append(Verdict(False, "missing_title", REASONS["missing_title"], None, old_keep))
        elif duplicate[index]:
            verdicts.append(Verdict(False, "duplicate", REASONS["duplicate"], None, old_keep))
        else:
            verdicts.append(_judge_content(item, aliases, old_keep))
    return verdicts


def judge(item: NewsItem, aliases: Sequence[str], *, now: datetime | None = None, lookback_days: int = 90) -> Verdict:
    """Xét MỘT ứng viên đứng riêng (không có bản ghi khác để so trùng). Nhiều ứng viên: dùng `screen`."""
    return screen([item], aliases, now=now, lookback_days=lookback_days)[0]


def _judge_macro_content(item: NewsItem) -> Verdict:
    def reject(code: str) -> Verdict:
        return Verdict(False, code, REASONS[code], None, True)

    term = _ECONOMIC_RE.search(item.title or "")
    if term is None:
        return reject("not_economic")
    return Verdict(True, None, None, term.group(0), True)


def screen_macro(
    items: Sequence[NewsItem],
    *,
    now: datetime | None = None,
    lookback_days: int = 90,
) -> list[Verdict]:
    """Tin vĩ mô: quá hạn, thiếu tiêu đề, trùng (cùng chính sách với `screen`), hoặc tiêu đề không nói về kinh tế."""
    now = now or datetime.now(timezone.utc)
    stale, untitled, duplicate = _duplicate_flags(items, [0] * len(items), now, lookback_days)
    verdicts: list[Verdict] = []
    for index, item in enumerate(items):
        if stale[index]:
            verdicts.append(Verdict(False, "stale", REASONS["stale"].format(days=lookback_days), None, True))
        elif untitled[index]:
            verdicts.append(Verdict(False, "missing_title", REASONS["missing_title"], None, True))
        elif duplicate[index]:
            verdicts.append(Verdict(False, "duplicate", REASONS["duplicate"], None, True))
        else:
            verdicts.append(_judge_macro_content(item))
    return verdicts


def judge_macro(item: NewsItem, *, now: datetime | None = None, lookback_days: int = 90) -> Verdict:
    """Xét MỘT tin vĩ mô đứng riêng. Nhiều tin: dùng `screen_macro`."""
    return screen_macro([item], now=now, lookback_days=lookback_days)[0]


def split_candidates(
    items: Iterable[NewsItem],
    aliases: Sequence[str],
    *,
    now: datetime | None = None,
    lookback_days: int = 90,
) -> tuple[list[tuple[NewsItem, Verdict]], list[tuple[NewsItem, Verdict]]]:
    """Chia ứng viên thành (giữ, loại), giữ nguyên thứ tự đầu vào."""
    items = list(items)
    verdicts = screen(items, aliases, now=now, lookback_days=lookback_days)
    kept = [(item, v) for item, v in zip(items, verdicts) if v.keep]
    rejected = [(item, v) for item, v in zip(items, verdicts) if not v.keep]
    return kept, rejected


def pattern_flags(title: str | None) -> list[str]:
    """Dấu hiệu phụ của một tiêu đề, tính độc lập với thứ tự luật: có khớp mẫu trang dữ liệu, mẫu thể thao không.

    Chỉ để hiển thị cạnh lý do đầu tiên (ví dụ trang giá bị ghi "không nhắc tên" vì luật tên xét trước).
    Không đổi quyết định lọc và không dùng để đếm.
    """
    flags: list[str] = []
    if _NON_NEWS_RE.search(title or ""):
        flags.append("not_news_page")
    if _SPORTS_RE.search(title or ""):
        flags.append("sports")
    return flags
