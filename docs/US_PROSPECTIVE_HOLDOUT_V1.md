# Kế hoạch holdout tương lai — khóa trước thu thập

Đăng ký ngày 15/11/2026 theo giờ Việt Nam. Mục tiêu là chuẩn bị tập đánh giá
tin tách khỏi dev đã xem, không dùng để chứng minh hiệu quả dự báo lợi suất.
Không gọi tập này độc lập hoàn toàn khi còn chưa kiểm tra trùng sự kiện và
chưa có người gán nhãn độc lập.

- Cửa sổ công bố: 20 phiên NYSE từ 16/11 đến hết 14/12/2026 theo giờ New York.
- Chỉ nhận tiêu đề của 10 mã AAPL, MSFT, NVDA, JPM, GS, XOM, CVX, UNH, LLY,
  CAT, có `LIVE_CAPTURED_PIT`, được công bố trong ngày phiên và Equara nhận
  không muộn hơn 20:00 ET cùng ngày. Không dùng hồ sơ SEC cấu trúc để tính
  hiệu năng tone; chúng cần bài kiểm thử riêng.
- Chọn tối đa 60 cặp bài–mã, mục tiêu sáu cặp mỗi mã, xếp hạng ngẫu nhiên cố
  định theo SHA-256 với seed `equara-holdout-prospective-2026-v1`. Nếu mã thiếu
  sáu mục, không bù bằng mã khác và công bố mức thiếu. Đây là mẫu cân bằng,
  không ước lượng tỷ lệ lỗi toàn thị trường.
- Không chọn trước 20:05 ET ngày 14/12/2026. Nếu chưa đủ sáu mục mỗi mã thì
  xuất trạng thái thiếu, không lén kéo dài cửa sổ hoặc đổi seed. Có thể mở khóa
  xuất bộ nhỏ hơn bằng một quyết định công khai sau thời điểm kết thúc.
- Loại ID, tiêu đề chuẩn hóa, URL chuẩn hóa và event key đã xuất hiện trong
  batch Alpaca 200 mục cũ hoặc batch dev/holdout v2 đã xem. So khớp thêm sự kiện
  qua nội dung; bất kỳ cặp nghi trùng nào cũng cách ly để người độc lập rà.
  Dữ liệu đã công bố trong ngày gần ranh giới hoặc cùng sự kiện kéo dài có thể
  vẫn trùng ngữ nghĩa, nên chỉ các kiểm tra tự động không chứng minh độc lập.
- Không đọc dự đoán hoặc điểm FinBERT khi chọn và gán nhãn. Hai người chấm
  độc lập, phân xử bất đồng, khóa nhãn kèm hash; báo cáo số mẫu mỗi lớp,
  đồng thuận và khoảng bất định trước khi so model. Không sử dụng holdout để
  sửa quy tắc hay lựa chọn model.
- Chỉ đóng tập nhãn sau khi khóa rubric và bản dev. Nếu dev chưa được con người
  chấm và phân xử, tập tương lai chỉ là **ứng viên**, không là benchmark hoàn tất.

Nguồn có thể thiếu hoặc máy không chạy. Timestamp và trạng thái capture phải
được kiểm tra; số ngày có đủ giá 21 phiên không chứng minh quét tin đầy đủ.
Điều kiện xét PiT ở trên xác nhận lúc Equara nhận tiêu đề, không tự chứng minh
toàn bộ dữ liệu thị trường hay nhãn lợi suất sẵn có. Các nguồn có thể sửa tin;
giữ nguyên ID quan sát và timestamp thực, không xóa ledger.
