# Bản sửa theo đúng phạm vi tin đã chấm

Phiên bản `observed-capital-v3`, ngày 07/11/2026.

## Hành vi hiện tại

Điểm từng mã được tổng hợp từ tin đã thu thập và chấm. Điểm danh mục là tổng đóng góp theo tỷ trọng vốn. Nếu mọi mã đều có điểm, dùng tỷ trọng vốn nhập đã chuẩn hóa. Nếu có mã chưa có điểm, chỉ chuẩn hóa trên phần vốn của các mã có điểm và ghi rõ phạm vi. Không gán điểm 0 cho dữ liệu vắng mặt. Không tạo điểm giả định hay khoảng cho tin chưa có.

API bỏ `bound`, `bound_rule`, `bound_is_not`, `min_coverage_for_score`. Cấu hình `COVERAGE_MIN_FOR_SCORE` không còn chặn điểm quan sát. `coverage` được giữ tên kỹ thuật để tương thích phần phạm vi, nhưng giao diện gọi “Vốn được đại diện”, không diễn giải thành tỷ lệ thông tin đã biết. API thêm `score_scope`, `represented_symbols`, `unscored_symbols`, `scope_note`.

Giao diện một danh mục và so sánh A/B đều dùng quy tắc mới. Đã bỏ đồ thị khoảng giả định, lời diễn giải chiều của cả danh mục từ khoảng và phép tính khoảng trong phần tính tay. Notebook Colab và script phát lại đã cập nhật hợp đồng dữ liệu. Hai tab bài mẫu, bộ lọc liên quan và quy tắc Tin + Giá không đổi trong đợt này.

## Kiểm chứng

- 158 kiểm thử đạt, gồm đối chiếu phép tính JavaScript với backend trên dữ liệu đủ, thiếu, điểm cân bằng, vốn 0 và hai cách phân bổ vốn.
- Đã kiểm tra trình duyệt bằng fixture: đủ dữ liệu; HRHO chưa có điểm; so sánh A/B trên cùng tin. Hiển thị đóng góp đúng, không có khoảng giả định. Fixture được ghi rõ trên trang.
- API live dùng RSS và FinBERT local: COMI 11 tiêu đề, ETEL 15, FWRY 8; vốn 50/30/20; điểm 0,3854454955. Đóng góp lần lượt 0,2279700836; 0,1340462331; 0,0234291788. Bản ghi ở `artifacts/observed_scope_live_check.json`. Không gọi đây là giá trị cố định cho lần chạy sau.
- Trang live đã mở và hiển thị trạng thái dữ liệu thật. Việc bấm chạy xác minh kết quả live trên UI bị gián đoạn vì Local browser use bị tắt trong Work settings. API live và giao diện fixture đã được kiểm tra riêng; không tuyên bố hoàn tất ca UI live này.

## Bàn giao tiếp theo

Slide và báo cáo cũ có khoảng giới hạn là tài liệu phiên bản trước, chưa phù hợp để trình bày bản mới. Cập nhật chúng sau code: ví dụ chính dùng ba cổ phiếu đều có điểm (50/30/20, điểm 0,6/−0,2/0,1 → tổng 0,26); trường hợp thiếu dữ liệu chỉ là thông báo phạm vi, không làm trọng tâm đóng góp.
