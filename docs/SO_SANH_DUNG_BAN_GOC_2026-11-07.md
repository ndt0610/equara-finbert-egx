# So sánh trực tiếp bản gốc và nâng cấp

Luồng giao diện hiện tại: frontend/original-capital.js, dùng GET /api/sentiment/portfolio. Giữ một response trong bộ nhớ trang cho hai tab cùng danh sách mã (không lưu đĩa). Nút lấy lô mới thay response chung. Không gọi endpoint coverage mở rộng từ form theo vốn nữa. Endpoint coverage v3 và các hàm cũ giữ cho tái lập phiên cũ, không phải phép tính đang hiển thị ở tab theo vốn.

Công thức: x=p+−p−; K=số mã, w_i=vốn chuẩn hóa; q_micro=K*w_i, q_macro=1; S=Σqx/Σq. Chia đều thì q đều1 và bằng đúng gốc. Số tin vẫn ảnh hưởng trọng số hiệu dụng. Không gọi là Σw_i*mean(x_i); không khẳng định đo tác động lên giá. Tin + Giá và bộ chọn tin/FinBERT gốc không đổi.

Đã xem UI thật: gốc 0.0263538006693; nâng cấp50/50 cùng điểm;80/20 hiển thị0.160209. Cùng 3 tiêu đề: 2 COMI, 1 macro, 0 ETEL. Không gán điểm cho ETEL.

Slide và script hiện hành: presentation_upgrade/ban_7_slide_chot, build_seven_final.py và build_seven_handout.py ở thư mục workspace. Các bộ slide trước là lịch sử và không đại diện công thức hiện tại.
