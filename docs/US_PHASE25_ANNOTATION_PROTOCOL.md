# Phase 2.5 — gán nhãn mù hai chiều và kiểm định FinBERT

Ngày 15/11/2026. Đây là **giao thức đánh giá**, chưa phải kết quả thực nghiệm.
Không có 150–200 nhãn chuẩn hoặc chỉ số hiệu năng thật cho đến khi thu được tin,
con người gán nhãn và khóa tập dữ liệu. Không dùng kết quả ở đây để phát tín
hiệu mua/bán hay kết luận về lợi suất.

## Câu hỏi và đơn vị gán nhãn

Một tác vụ là một cặp `(observation_id, ticker)` và headline đã thấy ở cutoff.
`observation_id` khóa đúng phiên bản quan sát trong ledger; `item_id` có thể
được thu thập lại ở lần quét khác. Người chấm đọc **headline tại thời điểm
quan sát**, doanh nghiệp mục tiêu, nguồn và liên kết gốc nếu cần. Không xem
xác suất FinBERT, điểm net, cụm máy, biểu đồ giá sau sự kiện hay phản ứng giá.

Điền độc lập bốn quyết định:

1. `target_relevance`: `DIRECT_COMPANY_EVENT` nếu sự kiện trực tiếp của doanh
   nghiệp; `SECTOR_MACRO_SPILLOVER` nếu ngành/vĩ mô có kênh tác động rõ tới
   mã; `INCIDENTAL_OR_NOISE` nếu chỉ được nhắc kèm; `UNSCORABLE_ADMIN_FILING`
   cho tiêu đề hồ sơ SEC hành chính không có văn bản để chấm.
2. `textual_tone`: sắc thái **câu chữ** `POSITIVE/NEUTRAL/NEGATIVE`, không suy
   từ giá cổ phiếu. Hồ sơ hành chính không có tone thì để `null`, không điền
   `NEUTRAL` giả.
3. `economic_implication`: hàm ý kỳ vọng đối với dòng tiền, rủi ro hoặc giá
   trị cơ bản của **mã đang xét**, cùng ba hướng trên, `AMBIGUOUS_MIXED` khi
   có tín hiệu đối nghịch/thiếu ngữ cảnh, `NOT_APPLICABLE` khi mã chỉ được
   nhắc thoáng qua hoặc hồ sơ hành chính không đủ nghĩa. Đây là nhận định có
   điều kiện từ headline, **không phải** lợi suất đã quan sát.
4. `gold_event_cluster_key`: cùng mã và cùng cửa sổ, các headline mô tả cùng
   một sự kiện nhận cùng khóa; khác sự kiện nhận khóa khác. Chỉ dùng cho mục
   trực tiếp hoặc lan tỏa. Người chấm đặt khóa trước khi xem cụm máy.

`event_category` ghi loại sự kiện. Khi tone khác implication hoặc implication
`AMBIGUOUS_MIXED`, bắt buộc ghi `rationale_note` ngắn. Ví dụ “cắt giảm nhân sự
để cải thiện biên lợi nhuận” có thể tone âm, implication dương nhưng cần giải
thích điều kiện; không tự coi mọi lần sa thải là tích cực. Tin dầu tăng giá có
thể implication dương với XOM và âm với doanh nghiệp tiêu thụ nhiên liệu;
hai cặp `(ticker, headline)` được chấm riêng.

## Quy trình khóa trước khi đánh giá

1. Thu thập SEC/Alpaca theo Phase 2. Giá SIP là nguồn riêng; không cần giá để
   bắt đầu gán nhãn headline. Nếu lấy giá bằng Alpaca Basic, historical SIP
   cần `end` cách hiện tại ít nhất 15 phút theo [Alpaca FAQ](https://docs.alpaca.markets/us/v1.4.2/docs/market-data-faq).
   Adapter mặc định lùi 20 phút và hỗ trợ `end_ts_utc` rõ ràng. Lỗi quyền truy
   cập được trả nguyên mã HTTP cùng hướng xử lý, không lặng lẽ đổi sang IEX.
2. Xuất batch mù từ bảng `raw_news_events`. Bộ xuất không đọc bảng
   `sentiment_scores`; chỉ xuất các trường trong `BlindAnnotationTaskItem`.
   Mặc định lấy tối đa 200 headline trong 30 ngày, phân tầng theo mã và loại
   bài. Muốn đo tỷ lệ hồ sơ hành chính không chấm được, dùng
   `--include-structural`. Bản xuất và manifest không được ghi đè.
3. Chia batch thành development và holdout **trước khi gán nhãn**, giữ toàn bộ
   `(ticker, ISO week)` trong cùng split. Cửa sổ tuần là biện pháp giảm rò rỉ
   sự kiện, chưa đảm bảo hai tin cùng sự kiện ở ranh giới tuần được tách đúng;
   rà thủ công các cụm sát ranh giới trước khi khóa.
4. Hai người gán nhãn độc lập hoặc một người gán hai vòng tách ngày và ID.
   Tính đồng thuận và Cohen's Kappa theo từng trục. Bất đồng về relevance,
   tone, implication, category hoặc khóa sự kiện được đưa vào hàng đợi phân
   xử. Thêm một bản ghi `is_adjudicated=true` cho quyết định cuối; bộ đánh giá
   từ chối bất đồng chưa phân xử.
   Kappa relevance dùng mọi cặp đã chấm; Kappa tone chỉ dùng cặp cả hai có
   tone; Kappa implication chỉ dùng cặp cả hai có implication áp dụng. Luôn
   đọc kèm số cặp của từng phép tính để tránh tỷ lệ đồng thuận bị thổi phồng
   bởi hồ sơ hành chính.
5. Kiểm tra hợp đồng, khóa JSONL với SHA-256 và manifest ràng buộc **cả bytes
   tác vụ lẫn bytes nhãn**. File khóa và manifest không được ghi đè qua công
   cụ khóa. SHA-256 phát hiện sửa đổi ngoài ý muốn; không phải chữ ký số chống
   người có quyền sửa đồng thời cả hai file.
6. Chạy benchmark. Majority baseline của holdout bắt buộc học lớp phổ biến
   từ development đã khóa. Cấm dùng holdout để sửa lexicon, ngưỡng Jaccard,
   chọn revision FinBERT hay chọn lại mẫu.

```powershell
& .\.venv\Scripts\python.exe -m scripts.export_blind_annotation_batch `
  --output artifacts/evaluations/us_batch.jsonl --tickers AAPL,MSFT,NVDA,JPM,XOM `
  --limit 200 --lookback-days 30 --include-structural

& .\.venv\Scripts\python.exe -m scripts.split_us_annotation_batch `
  --batch artifacts/evaluations/us_batch.jsonl `
  --dev-output artifacts/evaluations/us_dev_tasks.jsonl `
  --holdout-output artifacts/evaluations/us_holdout_tasks.jsonl

& .\.venv\Scripts\python.exe -m scripts.us_annotation_sheet prepare `
  --tasks artifacts/evaluations/us_dev_tasks.jsonl `
  --csv artifacts/evaluations/us_dev_annotator_a.csv --annotator-id annotator_a

# Điền các cột nhãn trong CSV, rồi nhập lại qua kiểm tra Pydantic:
& .\.venv\Scripts\python.exe -m scripts.us_annotation_sheet import `
  --tasks artifacts/evaluations/us_dev_tasks.jsonl `
  --csv artifacts/evaluations/us_dev_annotator_a.csv `
  --draft-labels artifacts/evaluations/us_dev_annotator_a.jsonl

# Lặp lại cho annotator_b và bản phân xử nếu cần, rồi khóa từng split:
& .\.venv\Scripts\python.exe -m scripts.lock_us_annotation_labels `
  --tasks artifacts/evaluations/us_dev_tasks.jsonl `
  --draft-labels artifacts/evaluations/us_dev_annotator_a.jsonl `
  --draft-labels artifacts/evaluations/us_dev_annotator_b.jsonl `
  --locked-labels artifacts/evaluations/us_dev_locked.jsonl `
  --manifest artifacts/evaluations/us_dev_gold_manifest.json `
  --dataset-id us-dev-v1 --split CALIBRATION_DEV

& .\.venv\Scripts\python.exe -m scripts.run_us_phase25_benchmark `
  --tasks artifacts/evaluations/us_holdout_tasks.jsonl `
  --locked-labels artifacts/evaluations/us_holdout_locked.jsonl `
  --manifest artifacts/evaluations/us_holdout_gold_manifest.json `
  --dev-tasks artifacts/evaluations/us_dev_tasks.jsonl `
  --dev-labels artifacts/evaluations/us_dev_locked.jsonl `
  --dev-manifest artifacts/evaluations/us_dev_gold_manifest.json
```

Ví dụ lệnh giả định đã khóa holdout bằng lệnh tương tự development. Đường dẫn
ledger mặc định là `artifacts/pit_ledger/equara_us_pit.sqlite3`; mọi script
nhận `--ledger` nếu cần dùng bản sao kiểm toán. Nếu cột `annotated_at_utc`
để trống trong CSV, công cụ nhập ghi thời điểm nhập file làm mốc gán nhãn;
người chấm có thể điền mốc thật để lưu chính xác hơn.
Phiếu phân xử có thể chỉ giữ các dòng bất đồng, đổi `annotator_id` sang người
phân xử, đặt `is_adjudicated=true`, rồi nhập với `--allow-partial`. Đưa file
JSONL phân xử vào lệnh khóa bằng thêm một `--draft-labels`.

## Cách đọc báo cáo

Track A so với `textual_tone`; Track B chỉ dùng mục liên quan có implication
ba hướng; Track C đếm các cặp lệch tone/implication và lỗi FinBERT trên tập
con đó; Track D so cụm Jaccard v2 với khóa người chấm trong cùng mã/cửa sổ.
Báo cáo có confusion matrix 3×3, precision/recall/F1 từng lớp, Macro-F1,
lỗi đoán ngược `POSITIVE↔NEGATIVE`, Brier đa lớp, ECE năm bins và độ phủ
dự đoán. Lexicon và majority dùng xác suất one-hot chỉ để có cùng giao diện
thống kê; các giá trị này **chưa hiệu chuẩn**.
Độ phủ ở đây có mẫu số là **cặp mã–bài được gán nhãn**, không phải toàn bộ
tin xuất hiện trên thị trường hay toàn bộ sự kiện của doanh nghiệp.

False merge rate được định nghĩa là `FP/(TP+FP)` trên cặp máy gộp; false split
rate là `FN/(TP+FN)` trên cặp chuẩn cần gộp. Pairwise Precision/Recall/F1 là
chỉ số chính, ARI được báo trung bình theo cửa sổ. Với tập nhỏ hoặc các lớp
mất cân bằng, cần thêm khoảng tin cậy và phân tích từng mã trước khi kết luận
một mô hình tốt hơn mô hình khác. Một số trục có thể có `NO_SCORED_ITEMS`;
không gán điểm 0 hoặc nhãn neutral cho các mục thiếu dự đoán.
