# Đóng góp cá nhân trong dự án

Chủ dự án xác định nhu cầu cho người đang nắm cổ phiếu, đề xuất hai hướng nâng cấp gồm phản ánh phân bổ vốn và đối chiếu tin với diễn biến giá. Chủ dự án phản biện qua demo, yêu cầu dùng cùng tin khi so sánh, phát hiện sự khác biệt giữa vốn nhập với tỷ trọng tin, yêu cầu công thức và lý do phân loại có thể giải thích trước người xem.

## Sản phẩm kỹ thuật trong phạm vi nâng cấp

1. Luồng danh mục dùng lại lô tin gốc, bảo toàn điểm khi chia vốn đều, hỗ trợ thay vốn và truy nguyên đóng góp từng tin.
2. Luồng Tin + Giá riêng, thu thập ứng viên, xác định doanh nghiệp, theo dõi thời gian, gom gần trùng và giảm trọng số tuổi tin.
3. Quy tắc năm nhãn với công thức, điều kiện, dữ liệu và nguyên nhân tạo nhãn được hiển thị.
4. Giao diện so sánh, tài liệu giải thích và bộ kiểm thử cho các hành vi đã triển khai.

## Cách ghi nhận tác giả

Phần xác định bài toán, yêu cầu, phản biện và quyết định phạm vi thuộc đóng góp của chủ dự án. Việc đề xuất chi tiết thuật toán, viết mã, tài liệu và kiểm thử có hỗ trợ đáng kể từ Codex và Claude. Người trình bày cần nêu đúng mức tham gia thực tế và hiểu các quyết định đang bảo vệ. Repository chưa xác định phân công từng thành viên theo từng commit, vì mã được đóng gói từ phiên làm việc cộng tác.

FinBERT là mô hình kế thừa của ProsusAI. Phép trung bình trọng số, suy giảm mũ và phân vị là kỹ thuật có sẵn. Đóng góp của đồ án nằm ở việc lựa chọn, tích hợp và giải thích chúng cho trường hợp sử dụng, cùng phản biện giới hạn qua demo.

## Vấn đề còn mở

Danh mục hiện giữ nguyên trung bình từng bài của gốc nên số bài và vĩ mô vẫn ảnh hưởng điểm. Kết quả chưa phản ánh vốn thuần theo từng mã khi thiếu tin. Tin + Giá dùng các ngưỡng thử nghiệm và chưa được đánh giá lợi nhuận ngoài mẫu. Những hạn chế này là phần cần trình bày cùng kết quả.
