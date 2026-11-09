> TÀI LIỆU LỊCH SỬ, KHÔNG PHẢI TRẠNG THÁI HIỆN TẠI. Phiên bản rules-2 dùng Yahoo Adj Close, D=S×F và năm nhãn. Đọc SO_TAY_HOC_VA_VAN_DAP.md.

# Tin + Giá V1 — trạng thái triển khai

> Cập nhật mới nhất 05/11: các điểm tổng +0,422/+0,495 dưới đây là lịch sử bản thử. Phiên bản đang chạy đã để company.score và macro.score=null; chỉ hiện xác suất từng headline khi sự kiện chưa được xác nhận. Lượt cuối có 105 ứng viên, 89 headline chấm riêng (9 company, 80 context); CIB Kenya được giữ ở trạng thái chưa xác minh. Đã thêm widget TradingView để xem EGX delayed, script tải được nhưng chưa xác nhận hình ảnh vì browser bị tắt trong Work settings. Backend vẫn chưa nhận giá hiện hành. Phương án nguồn thay EODHD, công thức % và bước nối API nằm trong QUYET_DINH_NGUON_GIA_2026-11-05.md tại thư mục C3_windows_review_2026-11-04.

Cập nhật: 05/11/2026

## Mục đích

Tab riêng cho người đang nắm một mã EGX: nhìn sắc thái tin công ty, bối cảnh ngoài công ty và biến động giá ở những khung thời gian khác nhau. Nhóm thứ hai hiện được API đặt tên `macro`, nhưng nguồn RSS có thể chứa tin chính trị/xã hội; không được gọi toàn bộ nhóm này là kinh tế vĩ mô cho tới khi phạm vi được sửa. Tab không lấy tỷ trọng vốn C3 và không đặt lệnh.

## Đang có trong mã

- GET /api/v1/tin-gia/stock?symbol=COMI dùng adapter Tin + Giá độc lập, gọi hai truy vấn Google News theo mã, BBC RSS, Google News kinh tế; gọi EODHD News nếu có token. Mỗi response được chụp vào ledger trong response trước phân loại, kèm query/source, giờ nhận, tiêu đề/link/ngày đăng, xác suất (nếu chấm được), trạng thái và reason code. Phạm vi là response các query/feed đã gọi, không phải mọi bài trên Internet.
- Tin công ty đang hiện trung bình mô tả bằng nhau giữa các headline FinBERT đã chấm; không giảm theo tuổi, chưa gom sự kiện qua nhiều báo và không dùng để gắn nhãn. Tin ngoài công ty được chấm riêng từng headline nhưng không có điểm nhóm vì trộn nhiều loại bối cảnh khác nhau.
- Snapshot ledger chỉ nằm trong response của request hiện tại. Chưa lưu database lịch sử vì quyền retention/hiển thị nội dung nguồn chưa xác minh.
- Nếu máy đã cấu hình EODHD_API_TOKEN, backend gọi EODHD Live (Delayed) một lần để lấy snapshot giá, và một lần API EOD để lấy lịch sử giá ngày.
- HTTP 200 xác nhận token truy cập được endpoint/mã ở thời điểm request; nó không thay cho rà soát hợp đồng về quyền hiển thị hoặc tái phân phối.
- Từ snapshot và previousClose, backend tính biến động so với phiên trước. Nếu có đủ lịch sử, backend tính biến động so với giá đóng cửa năm phiên trước ngày snapshot.
- Giao diện hiển thị thời điểm nguồn/nhận, tình trạng trễ, hai nhóm sentiment riêng, biến động giá và biểu đồ lịch sử.
- Khi không có khóa hoặc nguồn trả lỗi, hệ thống hiển thị lý do và không dựng giá mẫu.

## Cách chạy bằng API

Khi backend đang chạy, ví dụ: GET http://127.0.0.1:8124/api/v1/tin-gia/stock?symbol=COMI

Khi EODHD_API_TOKEN chưa có trong môi trường tiến trình backend, response vẫn có thể trả bối cảnh tin nếu service FinBERT chạy được, nhưng phần price.status là unavailable. Không ghi khóa API vào file mã nguồn hay chia sẻ ảnh/log có chứa khóa.

Mỗi lần bấm “Đối chiếu Tin + Giá” khi có EODHD token có thể phát tối đa bốn request EODHD cho một mã: hai truy vấn news (công ty và general context), một snapshot delayed và một lịch sử ngày. Theo bảng giá hiện hành, EODHD liệt kê news ở mức 5 API calls mỗi request và Live/EOD ở mức 1; quyền/gói cụ thể phải kiểm tra trong tài khoản thực. Môi trường hiện tại không có token nên không gọi các endpoint này. Tab chỉ cập nhật khi người dùng bấm; không polling nền. Xem [EODHD News API](https://eodhd.com/financial-apis/stock-market-financial-news-api) và [bảng giá/API calls](https://eodhd.com/pricing).

## Lượt chạy thủ công trên Windows — 05/11/2026

- Runtime: Python 3.12 x64, venv dùng được tại `C:\equara_tin_gia_env`, FinBERT local/CPU. Không cấu hình `EODHD_API_TOKEN` hoặc `HF_TOKEN`.
- Fixture và live đã khởi động riêng. `/`, `/api/health`, và `/api/v1/tin-gia/stock?symbol=COMI` trả HTTP 200; Chromium mở tab Tin + Giá và gửi truy vấn được. Ở cửa sổ 319 px không thấy tràn ngang hoặc lỗi console; đây là smoke check thủ công, không phải kiểm thử toàn diện.
- Snapshot cũ khoảng 14:50 trả 3 headline công ty, điểm `+0,326`, và 2 headline bối cảnh `−0,901`. Rà soát sau đó xác định một headline là trang biểu đồ TradingView; hai bài còn lại nói về cùng thỏa thuận CIB/MNT-Halan. Điểm cũ là trung bình theo headline trước khi loại trang biểu đồ, không phải điểm sự kiện và không dùng làm bằng chứng quyết định.
- Snapshot API mới khoảng 15:26 trả 2 headline công ty, điểm trung bình headline `+0,495`; 2 headline bối cảnh `−0,901`; 1 trang TradingView được giữ riêng với lý do `market_data_chart_page`. Hai headline công ty đều mô tả cùng sự kiện CIB–MNT-Halan nên điểm `+0,495` vẫn có thể đếm một sự kiện hai lần. RSS thay đổi theo lần gọi; đây là ảnh chụp lô tại thời điểm đó, không phải mức đại diện dài hạn.
- Snapshot live COMI 15:56 dùng adapter mới: 105 bản ghi trong response (Google công ty bậc 1: 9; bậc 2: 15; BBC: 24; Google kinh tế: 57). EODHD News không được gọi vì thiếu token và trạng thái này được ghi trong ledger. Có 90 headline được chấm (10 công ty, 80 bối cảnh), 5 trang chart bị loại khỏi trung bình, 2 URL-tiêu đề trùng chính xác được nối về bản trước, 18 ứng viên chưa phân xử. Điểm công ty `+0,422` là trung bình headline ngang trọng số trong cửa sổ truy vấn 90 ngày; tin cũ nhất 78 ngày. Hai báo khác nhau cùng mô tả thỏa thuận CIB–MNT-Halan vẫn chưa được gộp sự kiện. Không có điểm chung cho context; mỗi headline được xem riêng.
- Chromium sau reload xác nhận disclosure ledger có danh sách trạng thái từng truy vấn và bản ghi, lý do, tuổi tin, giờ nhận, điểm từng headline. Lượt này ghi đúng response nguồn, không đại diện toàn thị trường và không được lưu qua request.
- `price.status=unavailable`; không có giá thực, `decision.status=not_ready`, `label=null`. Health báo model local `ProsusAI/finbert`, revision `0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031`, không gọi inference HTTP.
- Một số tin đang được gọi là nhóm `macro` có thể là tin chính trị/xã hội. Source UI đã đổi tên phần này thành “Tin bối cảnh ngoài công ty”; API enum vẫn `macro` và nhóm không đi vào nhãn hiện tại.
- Danh sách headline ở source UI nay thu gọn; thẻ sentiment thêm tuổi bài mới nhất/cũ nhất và từng hàng hiện p+, p−, p0, s. Đã reload, lấy lại live COMI và xác nhận các nội dung này trên Chromium. Chưa chạy pytest, E01–E90 hay bộ kiểm thử tự động/backtest/model evaluation. Không suy hiệu quả đầu tư từ mã HTTP 200, điểm sentiment hoặc kết quả Chromium.

## Giới hạn cần nói rõ khi demo

1. **Đây chưa phải giá real-time.** Tài liệu EODHD nói Live (Delayed) toàn cầu trễ khoảng 15–20 phút. WebSocket real-time của họ được tài liệu hóa cho cổ phiếu Mỹ và Châu Âu, không phải EGX. EODHD cũng cảnh báo một số giá toàn cầu có thể là indicative. Xem [Live (Delayed) API](https://eodhd.com/financial-apis/live-ohlcv-stocks-api), [Real-Time WebSocket API](https://eodhd.com/financial-apis/new-real-time-data-api-websockets), [nguồn và đối tác dữ liệu](https://eodhd.com/financial-apis/our-data-sources-and-data-partners).
2. **Chưa có nhãn Mua mạnh/Mua/Giữ/Bán/Bán mạnh.** Response cố ý trả decision.status=not_ready và label=null. Chưa có forecast lợi suất ngoài mẫu, hai loại khoảng đã hiệu chuẩn, bid/ask, chi phí và nguồn EGX intraday đã xác minh.
3. **Điểm FinBERT không phải dự báo giá.** Ledger hiện có mọi entry trong bốn response RSS đã gọi, nhưng RSS không bao phủ mọi tin. Luật hiện loại mẫu TradingView rõ và nối URL+tiêu đề giống hệt; chưa phân loại đầy đủ tin theo sự kiện, nên bài khác nguồn về cùng việc vẫn có thể đếm riêng trong số mô tả headline công ty. Tin bối cảnh có thể gồm chính trị/xã hội/địa chính trị; giao diện không gộp chúng thành một điểm chung và chưa đưa vào quyết định.
4. **Biến động giá không chứng minh tin gây ra biến động.** Đây là hai quan sát song song; cần thiết kế đánh giá ngoài mẫu mới có thể nói tin bổ sung giá trị dự báo.
5. **Mốc năm phiên dùng giá thô.** Mã hiện không truy vấn/điều chỉnh corporate action cho cửa sổ đó; hiển thị kèm cảnh báo và không đưa vào nhãn.
6. **Quyền dữ liệu và EGID chưa xác minh.** HTTP 200 từ EODHD chỉ chứng minh token nhận được phản hồi cho request đó, không chứng minh quyền hiển thị/tái phân phối trong sản phẩm. EGID chưa tích hợp: chưa có credential dự án, schema response kiểm chứng bằng dữ liệu thực hay bằng chứng entitlement. Tham khảo [EGID Swagger](https://ticker.egidegypt.com/index.html) và [trang dịch vụ EGID](https://egidegypt.com/index.html).
7. **Chưa có lượng vị thế `q` trong form.** Demo không biết người dùng đang nắm bao nhiêu cổ phiếu; form hiện chỉ chọn mã. Cần thêm lượng q và xác minh lot size/chi phí để nhãn áp dụng rõ cho kịch bản cụ thể, không giả định toàn bộ vị thế hoặc tài khoản.
8. **Ngưỡng kỹ thuật đang có không phải ngưỡng đầu tư.** 1,200 giây lấy đầu trên (20 phút) từ độ trễ 15–20 phút EODHD công bố. Mốc 180 giây cho tuổi response và 1,800 giây cho tuổi quote là hàng rào tạm thời để UI gắn “cũ”; quote-age 30 phút gồm biên dự phòng 10 phút sau độ trễ tối đa công bố. Cửa sổ lịch sử 30 ngày chỉ để đi qua cuối tuần/ngày nghỉ và lấy dư phiên so sánh 5 phiên. Chưa có log feed đủ dài để hiệu chỉnh; các số này không được dùng làm half-life, forecast horizon hay ngưỡng Mua/Bán.

## Không được kết luận từ bản hiện tại

- Không gọi điểm sentiment +0.3 là giá sẽ tăng 0.3%.
- Không gọi quote EODHD là giá trực tiếp/đã xác minh với sàn EGX.
- Không xem label=null là nhãn Giữ.
- Không tuyên bố dự báo, ngưỡng, hiệu quả đầu tư hay kết quả backtest đã được chứng minh.

## Cần có trước khi bật nhãn thật

- Nguồn giá EGX đúng quyền sử dụng, mapping mã, timestamp/cadence, bid/ask và trạng thái phiên.
- Lịch sử giá có thể tái dựng theo thời điểm, corporate actions, lịch giao dịch, phí và quy tắc lot size.
- Tin point-in-time có quyền lưu, timestamp lần đầu biết, gán nhãn người đánh giá và event ledger đã phân xử; nhật ký hiện tại chỉ theo request và `published_at` có thể khác `available_at`.
- So sánh M0 (giá), M1 (giá + tin công ty), M2 (M1 + tin vĩ mô đủ điều kiện) theo rolling-origin ngoài mẫu, cùng mốc ngày và benchmark nắm giữ/bán ra-tiền mặt.
- Hiệu chuẩn riêng bất định kỳ vọng và khoảng kết quả một lần; kiểm tra net-of-cost, theo mã/chế độ thị trường; chỉ chốt k_mua/k_ban nếu cải thiện ổn định và holdout cuối xác nhận.

Việc đã triển khai giao diện/API là bằng chứng phần mềm riêng; nó không phải bằng chứng rằng mô hình tạo lợi thế đầu tư.
