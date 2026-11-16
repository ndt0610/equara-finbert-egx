# Sửa ngày nộp trong SEC pilot ngày 15/11/2026

## Kết luận kiểm toán

Lô `us_sec_pilot_2026-11-15.jsonl` ban đầu có 25/25 tác vụ mang sai
`source_filing_date=2019-05-02`. **Sổ cái và adapter SEC đúng**: adapter lấy
`filings.recent.filingDate[i]` cùng chỉ số với `accessionNumber[i]`; sổ cái có
587 ngày nộp khác nhau, trong đó chỉ một hồ sơ mang ngày 02/05/2019. Lỗi ở
`blind_export.py`: khi dựng tác vụ sau khi chọn mẫu, vòng lặp thứ hai tái sử
dụng biến `source_day` của vòng lặp trước thay vì lấy ngày từ từng `row`.

Không xóa, di chuyển hoặc quét lại `equara_us_pit.sqlite3`. Làm vậy sẽ làm
mất mốc Equara **thực sự nhìn thấy** hồ sơ đầu tiên, vô ích đối với lỗi nằm
ngoài ledger. SEC mô tả `submissions` là các mảng dữ liệu theo cột, nên việc
ghép `filingDate[i]` với accession cùng `i` là hợp đồng đúng:
[SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

## Bản cũ và bản sửa

Mười file batch, manifest, split và CSV cũ được giữ nguyên trong
`artifacts/evaluations/quarantine_sec_pilot_date_error_2026-11-15/` với nhãn
`INVALID_DO_NOT_ANNOTATE.md`. Không có nhãn con người trong các CSV đó.

Bộ mới là `artifacts/evaluations/us_sec_pilot_v2_2026-11-15.jsonl`, SHA-256
`316563eb070652d2c6942049df5d678a61d55a1d8899ca9850b4de6574d8752e`.
Có 25 hồ sơ, 13 ngày nộp từ 15/10 đến 13/11/2026; đối chiếu bằng
`observation_id` cho thấy **0 sai khác** với ledger. Split giữ 18 tác vụ dev
và 7 holdout; bốn CSV mới có hậu tố `v2` đã được tạo. Không dùng bộ 25 hồ sơ
cấu trúc này để đo FinBERT tone hay giá trị tín hiệu lợi suất.

## Replay SEC theo ngày, chỉ để chẩn đoán

Với hồ sơ SEC cũ mà Equara mới tải hôm nay, `published_at_utc` là mốc nhìn
thấy đầu tiên, nên PiT nghiêm ngặt vẫn loại khỏi quyết định lịch sử. Chỉ khi
`allow_retrospective_diagnostic=True`, Phase 3 mới cho phép đặt **hồ sơ SEC
cấu trúc** vào cửa sổ lịch sử theo `source_filing_date` ở độ phân giải ngày,
đồng thời thêm `RETROSPECTIVE_EVENT_USED`. Ngày nộp không chứng minh hồ sơ đã
công khai trước cutoff 20:00 ET; vì vậy báo cáo vẫn phải là
`EXPLORATORY_NON_PIT_DIAGNOSTIC_ONLY`. Kiểm tra với dữ liệu thật tại AAPL
05/11/2026: 0 hồ sơ ở chế độ nghiêm, 2 hồ sơ ở replay chẩn đoán.
