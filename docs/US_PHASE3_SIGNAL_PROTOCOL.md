# Equara US Phase 3: kiểm định thông tin sự kiện theo thời gian

Ngày 15/11/2026. Đây là **khung nghiên cứu chạy offline**, chưa có kết quả trên
dữ liệu thật và chưa cấp quyền cho năm nhãn hành động. Sổ cái mặc định chưa có
chuỗi live đủ dài. Mẻ SEC/Alpaca kéo hồi cứu hôm nay không chứng minh rằng tin,
điểm FinBERT hay bản giá điều chỉnh đã sẵn có ở các quyết định trong quá khứ.

## Giả thuyết và thiết kế

Giả thuyết chính: với cùng hàng `(ticker, decision_date)` và cùng fold theo thời
gian, thêm thông tin sự kiện vào đặc trưng giá giúp dự báo lợi suất sau chi phí
trên 5 phiên NYSE. Hai chân trời 1 và 20 phiên chỉ dùng để kiểm tra độ nhạy.
Tại 20:00 ET sau phiên `t`, đặc trưng giá gồm lợi suất 1/5/20 phiên, độ lệch
chuẩn 20 biến động ngày và phân vị 75/90 của độ lớn biến động ngày. Cần đủ
21 giá đóng cửa điều chỉnh liên tiếp, mỗi bản giá và bản điều chỉnh phải được
thu nhận trước cutoff. Sự kiện cần `published_at`, `ingested_at` và
`scored_at` trước cutoff; SEC chỉ là tín hiệu cấu trúc nếu chưa có nội dung
được chấm. Cụm sự kiện không có điểm giữ giá trị thiếu, không gán bằng 0.

Nhánh đối chứng vận hành là tiền mặt và rổ đều trọng số các mã đủ dữ liệu.
Hai mô hình dự báo trên cùng mẫu là `price` và `price_news`. Ridge ước lượng
lợi suất gộp; logistic L2 ước lượng xác suất lợi suất ròng sau 10 bps mỗi chiều
dương. Chuẩn hóa đặc trưng chỉ học trong tập train của từng fold. Bốn biến thể
tin được đăng ký trước: trung bình điểm cụm (chính), giảm theo tuổi với bán rã
3 hoặc 7 ngày, và điểm bài được chấm đầu tiên trong mỗi cụm. Không chọn biến
thể thắng dựa trên holdout.

Lợi suất mục tiêu chính là `CloseAdj[t+H] / OpenAdj[t+1] - 1`. Bản tính độ nhạy
dùng `CloseAdj[t+1]` làm giá vào. Chi phí minh họa là 0, 10, 25 bps *mỗi
chiều*; lợi suất ròng lấy lợi suất gộp trừ hai lần chi phí. Giá điều chỉnh và
chi phí tuyến tính là **proxy ex post**, chưa phải lệnh khớp hay dòng tiền cổ
tức/split kiểm toán được. Chỉ số danh mục giả định mua rổ đều trọng số sau
quyết định, thanh lý hoàn toàn sau H phiên, không mở các rổ chồng lấn. Đây là
kiểm tra kinh tế của một quy tắc đơn giản, không phải mô phỏng tài khoản.

## Chống rò rỉ và cổng báo cáo

Mẫu train tại `T` chỉ được nhận khi `t + H <= T` **và** nhãn đã được quan sát
trước cutoff của `T`. 25% phiên quyết định cuối là holdout theo thời gian;
tại đầu holdout, cả tập train lẫn mốc khả dụng nhãn đều được đóng băng. Khi
thiếu train, fold bị bỏ với lý do. Báo cáo nêu cả số mẫu bị loại vì thiếu giá,
toàn bộ mẫu đánh giá, mẫu có sự kiện, holdout và holdout có sự kiện.

Báo cáo so chênh Brier, log loss, AUC và Spearman IC của hai nhánh. Khoảng
95% dùng moving block bootstrap theo ngày quyết định; cùng một ngày lấy cả
các mã để giữ phụ thuộc chéo. Chẩn đoán danh mục gồm lợi suất ròng, IR theo
kỳ so rổ đều trọng số, vòng quay, drawdown, tỷ lệ kỳ lỗ, và phân rã năm/quý/mã.
Khoảng lợi suất ròng dùng block bootstrap trên các kỳ rổ không chồng lấn;
thiếu tối thiểu 8 kỳ thì trả `null`, không suy diễn ý nghĩa thống kê.

Nếu bất kỳ đặc trưng nào đến từ `EXPLORATORY_RETROSPECTIVE_NON_PIT`, fixture,
IEX hoặc được tải/chấm sau cutoff, báo cáo gắn
`EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY`. Dữ liệu live PiT có thể nhận
`PIT_COMPLIANT_RESEARCH_RUN`, nhưng **không tự vượt cổng hành động**: cần Brier
cải thiện trên holdout có sự kiện, lợi suất ròng sau 20 bps round trip dương
có khoảng bất định đủ mạnh, và bằng chứng về giá mở cửa có thể thực hiện được.
API giá Phase 2 vẫn gắn lô quét lịch sử thông thường là hồi cứu. Phase 3.1 có
CLI ghi **vintage giá đúng ngày**: toàn bộ cửa sổ điều chỉnh 21 phiên từ một
đợt quét SIP sau giờ đóng cửa +20 phút và trước cutoff 20:00 ET mới được gắn
`LIVE_CAPTURED_PIT`. Một đợt quét muộn hoặc thiếu phiên vẫn là hồi cứu.
Panel chọn một vintage đồng nhất cho đặc trưng và neo nhãn vào vintage hoàn
chỉnh đầu tiên sau phiên thoát; các lần tải lại sau đó không làm trôi nhãn.
Còn cần giám sát đủ lần quét tin trên từng mã/ngày và hồ sơ giá vào lệnh. Bản
này
chưa có dữ liệu fill/quote tại mở cửa nên luôn xuất
`KEEP_DESCRIPTIVE_ONLY — FIVE_LABELS_REMAIN_EXPERIMENTAL`. Các kiểm tra cổng
trong JSON là chẩn đoán tiền đề, không phải xác nhận tín hiệu đầu tư.

## Chạy

Sau khi sổ cái có dữ liệu, chạy từ gốc repo:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_us_phase3_signal --tickers AAPL,MSFT,NVDA,JPM,GS,XOM,CVX,UNH,LLY,CAT --start 2026-11-16 --end 2027-03-31
```

Khi cần kiểm tra cơ học trên dữ liệu hồi cứu, thêm
`--allow-retrospective-diagnostic`. Một lô quét hồi cứu có thể chứa nhiều phiên
giá, nhưng `label_available_at_utc` thật của mọi mẫu chỉ là ngày quét. Trong
chế độ này, bộ kiểm định dùng **mốc giả định 20:00 ET của phiên thoát** để tạo
các fold replay; đây là giả định ex post, không phải bằng chứng nhãn đã sẵn có
khi đó. Panel vẫn giữ timestamp thật; JSON báo rõ
`HYPOTHETICAL_EXIT_SESSION_20_ET_EX_POST_DIAGNOSTIC` và luôn đóng dấu
`EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY` khi có hàng dữ liệu. Không được dùng
metric của replay này để công bố tín hiệu out-of-sample hay phát nhãn hành động.
`--horizon 1` hoặc `20` là kiểm tra độ nhạy. `--cutoff-et 20:00` là mặc định.
Ba file đầu ra trong `artifacts/phase3/`: panel JSON có ID chứng cứ, báo cáo
JSON có metric/CI và hash, summary Markdown có cấp hiệu lực. Nếu ledger chưa
tồn tại, lệnh báo lỗi rõ; nếu chưa đủ mẫu, báo cáo ghi số fold bằng 0.

Không nhập email SEC hoặc khóa Alpaca vào lệnh hay repo. Xem
[Phase 2](US_PHASE2_STATUS.md) về cấu hình nguồn và [Phase 2.5](US_PHASE25_ANNOTATION_PROTOCOL.md)
về benchmark văn bản. Lịch NYSE tĩnh của repo chỉ phủ 2026–2028 và không xử lý
đóng cửa đột xuất; chuỗi giá/tin cần được giám sát hàng ngày trước nghiên cứu
live. Dữ liệu kết quả chỉ có ý nghĩa khi độ phủ và sai lệch do mẫu thiếu đã
được thẩm định riêng.

Vận hành hàng ngày: [US_PHASE31_DAILY_CAPTURE.md](US_PHASE31_DAILY_CAPTURE.md).
