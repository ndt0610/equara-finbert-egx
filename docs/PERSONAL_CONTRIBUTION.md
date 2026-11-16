# Đóng góp cá nhân trong Equara

Equara là dự án cá nhân của Nguyễn Đình Tú, phát triển từ bài tập/ý tưởng phân tích tin tài chính EGX và mở rộng thành các luồng nghiên cứu riêng.

## Phạm vi cá nhân

- Xác định người dùng mục tiêu của luồng Tin + Giá là người đang nắm giữ cổ phiếu; đề xuất cách đưa điểm tin, tuổi tin và mức biến động 5 phiên vào một bảng quy tắc có thể giải thích.
- Đề ra yêu cầu cho luồng danh mục theo vốn: dùng cùng lô tin khi so sánh, thể hiện độ phủ và đóng góp theo từng mã, không để người xem nhầm trọng số tin với tỷ trọng vốn.
- Rà demo và phản biện trường hợp tin với giá trái chiều, thiếu dữ liệu, tin cũ/trùng, ngưỡng biến động và lý do tạo nhãn.
- Mở rộng phạm vi nghiên cứu sang danh mục Mỹ Phase 1 và các nhánh sổ cái/replay; các giai đoạn có trạng thái và giới hạn riêng trong tài liệu.

## Cách triển khai và ghi nhận công cụ

Tôi sử dụng công cụ AI (bao gồm Codex và Claude) để hỗ trợ đề xuất, viết/sửa mã, tài liệu và kiểm thử. Vai trò của tôi là xác định bài toán/phạm vi, đưa yêu cầu, rà giao diện và kết quả, phản biện lựa chọn phương pháp, kiểm tra các ví dụ và quyết định nội dung đưa vào demo. Không nên mô tả dự án là sản phẩm nhóm; cũng không nên nói toàn bộ mã do tôi tự viết thủ công.

FinBERT là mô hình pretrained của ProsusAI. Công thức giảm trọng số theo tuổi, phân vị lịch sử và cách gom chuỗi tiêu đề là các kỹ thuật có sẵn; đóng góp ở đây là lựa chọn, tích hợp và trình bày chúng cho bài toán demo này, không phải phát minh mô hình mới.

## Giới hạn cần nói cùng kết quả

Bộ quy tắc Tin + Giá hiện là thử nghiệm, chưa được kiểm định lợi nhuận ngoài mẫu. Nhóm tiêu đề gần trùng là phép ghép tạm; dữ liệu giá ngày chưa được đối soát độc lập mọi sự kiện doanh nghiệp. Phản ứng sau tin mô tả quan sát theo thời gian, không chứng minh quan hệ nhân quả. Các nhánh danh mục Mỹ, replay và annotation có chất lượng dữ liệu/trạng thái khác nhau; xem tài liệu Phase tương ứng trước khi trích dẫn số liệu.
