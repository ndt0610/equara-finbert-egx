# Danh mục Mỹ Phase 2: thu thập và truy nguyên theo thời điểm

Ngày 15/11/2026. API fixture Phase 1 và mọi tab EGX giữ riêng. Phase 2 thêm
`POST /api/v3/us/capture` (nguồn `sec`, `alpaca_news`, `alpaca_prices`) và
`POST /api/v3/us/snapshot`. Nút thu thập trong tab Mỹ chỉ quét mã đang nhập;
API nhận `tickers: []` để quét toàn bộ 50 mã. Không tự gọi mạng khi mở trang.

## Thiết lập

```powershell
$env:SEC_EDGAR_USER_AGENT='EquaraResearch/1.0 (dia-chi-email-that@example.com)'
$env:ALPACA_API_KEY='...'
$env:ALPACA_SECRET_KEY='...'
$env:ALPACA_PRICE_FEED='sip'
```

SEC bắt buộc User-Agent có địa chỉ liên hệ và giới hạn 5 request/giây. Nếu thiếu,
API trả `PROVIDER_UNCONFIGURED` và không gửi request. Alpaca là tùy chọn; thiếu
khóa cũng trả trạng thái đó. Feed giá mặc định `sip`; muốn dùng `iex` phải đặt
rõ biến môi trường. IEX chỉ là một nơi khớp lệnh, nên snapshot không công bố
NAV hoàn chỉnh khi vị thế có giá IEX. API giá trả lỗi nếu gói dữ liệu không
cho phép feed SIP. Historical SIP trên Alpaca Basic yêu cầu mốc `end` cách
hiện tại ít nhất 15 phút; adapter mặc định lùi 20 phút, nhận `end_ts_utc`
tùy chọn và báo rõ lỗi quyền truy cập. Không có khóa nào được ghi vào ledger.

Sổ cái mặc định tại `artifacts/pit_ledger/equara_us_pit.sqlite3`. Bốn bảng
`ingestion_runs`, `raw_news_events`, `sentiment_scores`, `eod_price_bars`
chặn UPDATE/DELETE bằng trigger SQLite. Mỗi lần thu thập có run ID, mốc bắt
đầu/kết thúc, hash SHA-256 của bytes phản hồi (cho adapter HTTP), nguồn, cấp
PiT và tag quyền sử dụng. `PitLedger.export_run_jsonl` xuất lại metadata và
quan sát của một run cùng hash file xuất. Nên sao lưu ledger như một hồ sơ bằng
chứng; trigger không ngăn người có quyền sửa trực tiếp file hoặc thay mã nguồn.

## Hợp đồng thời gian

- Snapshot chỉ nhận sự kiện có mốc nguồn/quan sát hợp lệ và `ingested_at` trước
  cutoff. Điểm FinBERT chỉ được dùng khi `scored_at` trước cutoff ở chế độ nghiêm.
- SEC `acceptanceDateTime` được giữ **nguyên văn** trong
  `provider_accepted_raw`; `provider_accepted_at_utc` để trống khi chưa xác
  minh cách mã hóa múi giờ. `published_at_utc` của hồ sơ SEC dùng giờ Equara
  thấy hồ sơ lần đầu, ghi rõ cơ sở `EQUARA_FIRST_OBSERVED_UPPER_BOUND`. Đây là
  cận trên bảo thủ cho khả dụng, không phải giờ SEC công bố. `source_filing_date`
  ngăn hồ sơ cũ mới tải hôm nay giả làm tin mới trong cửa sổ 7 ngày.
- Lần quét đầu của từng mã là `EXPLORATORY_RETROSPECTIVE_NON_PIT`. Hồ sơ mới
  sau một lần quét thành công chỉ được gắn `LIVE_CAPTURED_PIT` nếu ngày nộp
  không cũ hơn ngày của baseline. Không dùng giờ SEC chấp nhận làm bằng chứng
  nhà đầu tư đã thấy hồ sơ đúng giây đó.
- Tin sau giờ đóng cửa NYSE, kể cả phiên 13:00 ET, được gắn phiên giao dịch
  khả thi tiếp theo. Snapshot cuối tuần vẫn dùng phiên hoàn tất trước đó và
  có thể nhận tin được Equara thu thập trong cuối tuần.
- Cửa sổ tin mặc định 7 ngày. Những mục bị loại được trả với lý do, nhưng
  `snapshot_sha256` chỉ băm dữ liệu **được chấp nhận** và cấu hình; dữ liệu mới
  đến sau cutoff không làm đổi hash lịch sử.

## Cách đọc kết quả

SEC 8-K/10-Q/10-K/6-K hiện là sự kiện cấu trúc
`UNSCORED_STRUCTURAL_FILING`. Chưa trích xuất Exhibit 99.1 hoặc nội dung
đủ nghĩa để chấm. Tin Alpaca có tiêu đề mới được chấm bằng local
`ProsusAI/finbert` revision được ghim. Sắc thái là điểm ngôn ngữ, không phải
ước lượng tác động lên giá hay khuyến nghị giao dịch.

Vị thế dùng `close_raw` để nhân số cổ phiếu. `R5` dùng `close_adj` từ sáu phiên
NYSE liên tiếp và chỉ khi bản điều chỉnh đã được thu nhận trước cutoff. Không
trộn giá cũ/thiếu hoặc IEX vào NAV hoàn chỉnh. Giá điều chỉnh lịch sử được tải
hôm nay là dữ liệu nghiên cứu hồi cứu, không chứng minh bản điều chỉnh đó có
sẵn ở cutoff cũ.

Khi đủ giá hợp lệ, snapshot tính độ phủ vốn và sắc thái theo vốn từ `close_raw`.
Điểm trên phần có tin và đóng góp trên toàn bộ vốn là hai số khác nhau; mã
không có tin giữ `null`, không tự nhận điểm trung tính.

Gom cụm v2 loại ticker và tên công ty, bỏ từ nối, chuẩn hóa vài biến thể rõ
ràng (`beats`→`beat`, `expectations`→`estimate`), rồi dùng khóa sự kiện, tiêu đề
chuẩn hóa hoặc Jaccard ≥0,55 trong 24 giờ. Cụm dùng phép so từng cặp để tránh
một tiêu đề cầu nối nhập hai sự kiện không giống nhau. Lý do gom được trả trên
UI. Đây vẫn là suy đoán sự kiện, cần kiểm định bằng tập gán nhãn độc lập.

## Giới hạn trước khi dùng cho nghiên cứu tài chính nghiêm túc

Chưa có nguồn giá miễn phí đủ tin cậy cho NAV chuẩn nếu không có quyền SIP.
Chưa tự thu thập định kỳ hoặc giám sát lỗi mạng. Một lần nhấn thu thập không
chứng minh dữ liệu tồn tại trong quá khứ. Tin Alpaca cần xác minh điều khoản
hiển thị/lưu trữ cho cách triển khai cụ thể; UI chỉ hiện headline và liên kết.
SEC cho truy cập và tái sử dụng nội dung hồ sơ công khai, nhưng việc đồng nhất
mọi tài liệu đính kèm với "public domain" là kết luận rộng hơn cần xem xét.
Lịch NYSE trong repo chỉ bao phủ 2026–2028 và không phản ánh đóng cửa đột xuất.

Nguồn đối chiếu: [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)
(không có mốc đầu tiên xuất hiện trên sec.gov, giới hạn truy cập),
[SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbarsingle-1)
(raw/all và phân trang),
[Alpaca historical news](https://docs.alpaca.markets/us/docs/historical-news-data).

Kiểm thử offline: `tests/test_us_phase2_pit_and_provenance.py`. Chưa gọi nguồn
live thật vì máy chạy cần User-Agent/email và/hoặc khóa Alpaca do chủ dự án
cấu hình.
