# Equara US Phase 3.1: quét giá theo vintage và neo nhãn

Ngày 15/11/2026. Chạy từ gốc repo sau mỗi phiên NYSE, lý tưởng trong khoảng
16:20–20:00 ET (phiên đóng sớm: từ 13:20 ET). Lịch tĩnh trong repo chỉ phủ
2026–2028 và không biết trước ngày đóng cửa đột xuất. Nếu dùng Windows Task
Scheduler theo giờ Việt Nam, đặt **05:30 sáng Thứ Ba–Thứ Bảy** và bật tùy chọn
đánh thức máy: tương ứng 17:30 ET mùa đông, 18:30 ET mùa hè của phiên Mỹ ngày
trước. Cả hai đều sau giờ đóng cửa +20 phút và còn ít nhất 90 phút trước cutoff.
Không đặt 07:15 sáng Việt Nam quanh năm: mùa hè mốc đó là 20:15 ET, đã quá
cutoff 20:00 ET. Ngày nghỉ NYSE cần theo dõi health report; lịch chạy cố định
theo thứ trong tuần không tự biết ngày nghỉ thị trường.

```powershell
$env:SEC_EDGAR_USER_AGENT='EquaraResearch/1.0 (email-that-cua-ban@example.com)'
$env:ALPACA_API_KEY='...'
$env:ALPACA_SECRET_KEY='...'
$env:ALPACA_PRICE_FEED='sip'
.\.venv\Scripts\python.exe -m scripts.run_us_daily_capture --tickers AAPL,MSFT,NVDA,JPM,GS,XOM,CVX,UNH,LLY,CAT
```

Các lệnh minh họa dùng `.venv` trong repo; tạo môi trường theo README nếu chưa
có. Trên máy phát triển hiện tại, môi trường đã cài thư viện nằm ở
`C:\equara_tin_gia_env\Scripts\python.exe`, nên có thể thay phần
`.\.venv\Scripts\python.exe` bằng đường dẫn đó. Đặt biến môi trường và chạy
lệnh trong **cùng cửa sổ PowerShell**; không ghi khóa vào `.env.example` hoặc
file báo cáo.

Nếu SEC đã quét thành công và chỉ cần bổ sung Alpaca trong một phiên PowerShell
riêng, thêm `--skip-sec`. Lệnh sẽ lấy giá và tin, chấm headline mới, rồi in
health report mà không gọi lại SEC. Tùy chọn này hữu ích cho lượt bổ sung
đầu tiên; những ngày vận hành đủ ba nguồn thì bỏ tùy chọn.

Để tự động hóa **toàn bộ mẻ Alpaca đầu tiên** mà không dán khóa vào chat hoặc
lịch sử lệnh, mở PowerShell riêng tại repo và chạy:

```powershell
& .\scripts\run_private_first_alpaca_batch.ps1
```

Script hỏi API key và secret bằng nhập ẩn, chạy quét Alpaca với `--skip-sec`,
xóa biến khóa khỏi môi trường tiến trình, rồi tự chạy health check, replay
chẩn đoán và xuất batch/split/4 CSV gán nhãn. Mỗi lượt ghi vào thư mục riêng
`artifacts/first_alpaca_batch/<timestamp>` để không ghi đè hồ sơ cũ. Script
không cài lịch định kỳ; sau mẻ đầu, dùng CLI hằng ngày hoặc lập lịch khi nguồn
đã được kiểm tra. Nếu PowerShell chặn `.ps1` theo chính sách máy, có thể chạy
từng lệnh Python trong phần trước; không cần gửi khóa cho Codex.

`BA` trong bản gợi ý chưa thuộc danh mục 50 mã đã khóa của repo; `CAT` thay thế
để có một mã công nghiệp mà không sửa danh mục giữa kỳ. Không lưu khóa vào
repo. `--health-only` đọc sổ cái và in mức sẵn sàng mà không gọi mạng; mặc định
ghi `artifacts/phase3/daily_health_status.json`, tách khỏi báo cáo thu thập
`daily_capture_status.json`. Có thể chỉ định `--ledger` và `--output`. Nếu một nguồn lỗi, CLI tiếp tục các nguồn
khác, ghi loại lỗi trong JSON và trả mã thoát 1. Nút API giá Phase 2 vẫn là
quét hồi cứu; chỉ CLI này mới thử chứng nhận vintage live đúng ngày.

CLI quét cửa sổ giá Alpaca 60 ngày lịch **trước** vì vintage giá phải kịp
cutoff 20:00 ET. Sau đó CLI chạy SEC, Alpaca News và chấm bổ sung headline
chưa có điểm theo revision FinBERT cố định. Một phiên chỉ có đặc trưng tin
được nhận vào panel khi tin và điểm được lưu trước cutoff; quét giá đúng giờ
không bảo đảm các nguồn tin cũng hoàn tất đúng giờ.
Từng mã chỉ nhận `LIVE_CAPTURED_PIT` khi có **21 phiên liên tiếp**, OHLC raw và
adjusted dương/hữu hạn, feed SIP, và thời điểm nhận dữ liệu nằm sau phiên đóng
cộng 20 phút nhưng trước 20:00 ET cùng ngày. Tất cả thanh cùng lần quét có
`run_id`, mốc điều chỉnh và hash phản hồi, kể cả các thanh lịch sử nằm trong
cửa sổ. Đây là bằng chứng **Equara đã thấy vintage ấy lúc đó**, không chứng
nhận Alpaca không sửa dữ liệu về sau.

Panel Phase 3 lấy toàn bộ 21 thanh từ một `run_id` và một
`adjustment_asof_utc` trước cutoff. Kết quả nhãn lấy `OpenAdj[t+1]` và
`CloseAdj[t+H]` từ lần quét **đầu tiên có đủ cả hai thanh sau giờ đóng cửa
phiên thoát**. `label_available_at_utc` bằng thời điểm cả hai thanh/điều chỉnh
đã sẵn có. Nếu quên quét tối phiên thoát và hôm sau mới có cặp giá, nhãn sẽ
trưởng thành muộn; hệ thống không giả mốc quan sát sớm hơn thực tế.

Health report gồm số mẫu live đủ 21 phiên, chuỗi phiên đầy đủ liên tiếp theo
mã, số nhãn đã trưởng thành cho H=1/H=5, và mã thiếu vintage mới nhất. Nó
**chưa** chứng minh độ phủ tin đầy đủ hoặc khả năng khớp lệnh ở giá mở cửa.
Năm nhãn hành động vẫn khóa. Mẻ đầu tiên có thể tạo dữ liệu hồi cứu cho gán
nhãn văn bản, nhưng không tự tạo 20 phiên quyết định PiT quá khứ.

## Mẻ đầu tiên: kiểm tra cơ học, chưa kiểm định tín hiệu

Cửa sổ giá hằng ngày hiện là **60 ngày lịch**; thường chỉ đủ khoảng 40–45
phiên NYSE. Panel cần 20 phiên lịch sử và H=5 phiên sau quyết định, nên số
ngày quyết định có thể dùng chỉ khoảng 15–20. Để chạy thử replay, dùng mức
train nhỏ và ghi rõ đây là phép thử phần mềm:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_us_phase3_signal `
  --tickers AAPL,MSFT,NVDA,JPM,GS,XOM,CVX,UNH,LLY,CAT `
  --start 2026-09-15 --end 2026-11-13 `
  --min-train-sessions 6 --min-train-rows 20 `
  --allow-retrospective-diagnostic
```

Các ngày và số hàng thực tế phụ thuộc ngày quét, mã thiếu giá và quyền feed.
CLI in riêng số hàng holdout có sự kiện và số kỳ rổ có thể tính CI. Một lần
quét Alpaca News hiện chỉ yêu cầu **7 ngày tin**; tăng giá lên 150 ngày sẽ
không tạo thêm tin cho các ngày cũ. Với khoảng 100 phiên giá, panel khoảng 75
ngày và holdout 25% chỉ khoảng 19 ngày: tối đa khoảng 4 rổ không chồng lấn
H=5, còn ít hơn khi chỉ xét ngày có sự kiện. Hàm bootstrap lợi suất holdout
cần ít nhất 8 rổ, nên 150 ngày giá **không đủ** để kết luận lợi suất holdout
có ý nghĩa. Hơn nữa adapter hiện chặn lookback trên 90 ngày; không dùng
`--lookback-calendar-days 150` vì CLI chưa có tham số đó. Chúng ta sẽ tăng
cửa sổ khi đã có lý do thực nghiệm và đi kèm dữ liệu tin tương ứng.

Alpaca giới hạn News API ở **50 bài mỗi trang**, adapter đã sửa theo giới hạn
này và tiếp tục dùng `next_page_token`. Nguồn:
[Alpaca News API](https://docs.alpaca.markets/us/reference/news-3),
[Alpaca multi-symbol bars](https://docs.alpaca.markets/us/reference/stockbars).

Alpaca mô tả `adjustment=all` là điều chỉnh split, dividend và spin-off; tham
số `asof` của endpoint dùng **ghép mã chứng khoán đổi tên**, không phải đồng hồ
vintage điều chỉnh. Bằng chứng vintage ở đây do Equara lưu raw response và
thời điểm nhận trong ledger. Nguồn:
[Alpaca historical stock bars](https://docs.alpaca.markets/us/reference/stockbarsingle-1).
