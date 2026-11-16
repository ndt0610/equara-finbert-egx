# Trạng thái hiện tại

Ngày 15/11/2026 đã thêm tab **Danh mục Mỹ Phase 1** và API descriptive riêng,
dùng fixture minh họa, 50 mã được chọn từ bảng mapping SEC, lịch NYSE 2026–2028,
công thức độ phủ vốn và kịch bản giá. Phase 2 bổ sung thu thập SEC/Alpaca theo
nút bấm, ledger SQLite chỉ thêm, snapshot PiT và panel truy nguyên. Chưa có
bằng chứng vận hành liên tục hoặc kiểm định khả năng giao dịch. Xem
[US_PHASE1_STATUS.md](US_PHASE1_STATUS.md) và [US_PHASE2_STATUS.md](US_PHASE2_STATUS.md).
Phase 2.5 bổ sung giao thức gán nhãn mù, khóa nhãn và benchmark hai trục;
chưa có kết quả benchmark thực. Xem
[US_PHASE25_ANNOTATION_PROTOCOL.md](US_PHASE25_ANNOTATION_PROTOCOL.md).
Phase 3 đã có khung panel PiT, walk-forward có purge nhãn, đối chứng giá/tin,
bootstrap và chẩn đoán sau phí. Chưa có dữ liệu live đủ dài hoặc kết quả tín hiệu
thực; mọi nhãn hành động vẫn thử nghiệm. Xem
[US_PHASE3_SIGNAL_PROTOCOL.md](US_PHASE3_SIGNAL_PROTOCOL.md).
Phase 3.1 bổ sung quét giá SIP đúng ngày theo vintage 21 phiên, neo nhãn vào
lần quét hoàn chỉnh đầu tiên sau phiên thoát, CLI và health report. Chưa chạy
nguồn live vì máy chưa có thông tin cấu hình nguồn. Xem
[US_PHASE31_DAILY_CAPTURE.md](US_PHASE31_DAILY_CAPTURE.md).
SEC pilot đầu tiên đã thu 814 hồ sơ hồi cứu; lỗi xuất `source_filing_date`
trong phiếu gán nhãn được sửa ở exporter, không ở sổ cái. Bộ v1 đã cách ly,
bộ v2 đối chiếu đúng 25/25 hàng. Xem
[US_SEC_PILOT_EXPORT_CORRECTION.md](US_SEC_PILOT_EXPORT_CORRECTION.md).
Các tab EGX cũ vẫn tồn tại để đối chiếu, gồm cả năm nhãn quy tắc thử nghiệm
ở tab riêng.

## Bản đóng gói EGX ngày 09/11/2026

Bản đóng gói lấy từ demo C3_3_2_tin_gia sau sửa so sánh trực tiếp với bản gốc ngày 07/11. Tab danh mục theo vốn hiện chạy frontend/original-capital.js và endpoint bản gốc. Các module coverage, notebook và tài liệu theo ngày là hồ sơ các bước nghiên cứu trước và có công thức khác. Đọc README để xác định hành vi hiện tại.

Gói bao gồm toàn bộ mã nguồn các module, script và kiểm thử của thư mục demo. Môi trường ảo, model tải xuống, khóa truy cập, cache và nhật ký máy được tạo tại nơi chạy. Snapshot trong docs/du_lieu_03-11 dùng cho kiểm thử tái lập lịch sử.

Các launcher lịch sử có đường dẫn Windows của máy phát triển. Hướng dẫn lệnh Python tương đối trong README dùng cho máy mới. Các script audit/replay có thể cần snapshot bổ sung. Tài liệu lịch sử trình bày các quyết định tại thời điểm ghi, cần đối chiếu với README hiện hành.
