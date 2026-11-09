# Biên bản kiểm chứng rules-v2 — 06/11/2026

## Kết quả kiểm chứng

- Chạy toàn bộ pytest trên môi trường Windows: **155 passed in 8.93s**.
- Kiểm tra cú pháp JavaScript sau sửa lời giải thích: `node --check frontend/app.js` đạt.
- Mở trình duyệt tại http://127.0.0.1:8124/, chọn Tin + Giá, nhập ETEL và bấm chạy: trả kết quả live, không phải fixture.
- Lượt trình duyệt 21:44 ngày 06/11: giá Close 128,550 EGP ngày 05/11; đổi 1 phiên +0,43%; đổi 5 phiên +7,04%; S=0,0711; F=0,5588; D=0,0397; 3 nhóm, số nhóm hiệu dụng 2,2708; B=6,16%, E=11,03%; nhãn Giữ. Trang hiển thị bảng điều kiện, công thức phân số, nhánh đang áp dụng và danh sách không dùng trong nhãn.
- API kiểm chứng lưu các đại lượng tại `artifacts/rules_v2_live_check.json`: không còn tin bóng đá trong nhóm quyết định; ledger ghi 1 tin thể thao bị loại.
- Phiên này dùng RSS + FinBERT local CPU. **Chưa cấu hình hay kiểm chứng EODHD News trong lượt chạy này.** Khung TradingView tải nhưng hiện giá trống; số liệu tính nhãn đến từ Yahoo/yfinance, không lấy từ khung đó.

## Các sửa đổi quan trọng

1. Chặn tin thể thao và trang báo giá khỏi tập chấm tin công ty; giữ lý do trong nhật ký.
2. Tách sắc thái S và độ mới F; dùng D=S×F để cả lô tin cũ giảm sức nặng tuyệt đối. Kiểm thử một tin 1 ngày so với 29 ngày phát hiện lỗi mà trung bình chuẩn hóa đơn thuần không xử lý được.
3. Bỏ bước tự chuyển về Giữ khi tin tiêu cực và giá giảm vượt E; giữ nhãn theo điều kiện, cảnh báo rủi ro biến động riêng.
4. Lợi suất 5 phiên và ngưỡng lịch sử dùng Adj Close. Close vẫn được hiển thị dưới tên giá đóng cửa quan sát. Kiểm thử chia tách giả lập bảo vệ khỏi bước nhảy giá thô.
5. Backend là nơi quyết định nhãn; frontend trình bày trace, tránh hai bộ phân loại độc lập.
6. Bổ sung công thức MathML, nguồn gốc ngưỡng, tập tin không vào nhãn và lời giải thích các đại lượng.
7. Thêm `RUN_DEMO.cmd` và `scripts/run_demo.ps1` để người dùng chủ động chạy máy chủ; giữ cửa sổ đó mở. Máy chủ chạy trong phiên công cụ trước đây đã dừng, nên không thể chỉ dựa vào việc từng mở URL thành công.

## Phạm vi chưa được chứng minh

Đây là bản demo hoạt động theo bộ quy tắc, chưa phải chiến lược đã chứng minh lợi nhuận. 155 kiểm thử chứng minh hành vi phần mềm trên các ca kiểm thử, không chứng minh ngưỡng tối ưu hay hiệu quả đầu tư.

Ngưỡng ±0,2/±0,6; tuổi 7/30 ngày; 5 phiên; phân vị 75/90%; tối thiểu 3 nhóm hiệu dụng vẫn là lựa chọn thiết kế. Gom tiêu đề gần trùng chưa xác minh đúng sự kiện; lọc tên chưa hoàn hảo; dữ liệu lịch sử chưa đối soát đầy đủ lịch phiên và corporate actions độc lập. Tập mã có alias kiểm chứng vẫn giới hạn; không coi nhập được mã bất kỳ là hỗ trợ đầy đủ toàn thị trường.

Giá dùng cho nhãn là giá ngày. Nguồn ngoài có thể lỗi/chậm và thay đổi nội dung; không bảo đảm real time hoặc demo luôn sẵn sàng khi máy chủ bị tắt. Nhãn thiếu dữ liệu phải là chưa gán nhãn, không mặc định Giữ.

## Tài liệu học và trình bày

Đọc `SO_TAY_HOC_VA_VAN_DAP.md`: bài gốc → FinBERT và công thức → danh mục theo vốn/độ phủ → Tin + Giá → đóng góp cá nhân → kịch bản 8–10 phút → câu hỏi vấn đáp. Các ví dụ giả lập được tách khỏi kết quả tin thật. Không trình bày quy ước thiết kế như định luật khoa học hoặc nhận mô hình FinBERT là đóng góp của bản thân.
