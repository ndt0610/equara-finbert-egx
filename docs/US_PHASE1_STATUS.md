# US Phase 1 — hợp đồng và phạm vi (15/11/2026)

## Kết quả người dùng nhìn thấy

Tab Mỹ là công cụ **mô tả**: giá trị từng vị thế, tỷ trọng vốn cổ phiếu, số sự
kiện tin được đại diện, sắc thái tiêu đề, phần vốn chưa có tin, và kịch bản giá
trước phí. Năm nhãn mua/bán của EGX nằm trong tab nghiên cứu cũ, không đi vào
điểm hay kết luận của danh mục Mỹ.

Fixture có hai tiêu đề AAPL giống nhau, một tiêu đề MSFT và một tin bối cảnh.
Các tiêu đề và xác suất là số giả lập, không phải kết quả model. Người dùng
nhập giá tham chiếu giả định; không có nguồn giá Mỹ live trong Phase 1.

## Phép tính

Với vốn cổ phiếu `E = Σ quantity_i × price_i > 0`, `w_i = V_i/E`. Mã có
ít nhất một cụm tin hợp lệ có điểm `s_i`; mã còn lại có `s_i = null`.
`C = Σ_(covered) w_i`; `S_covered = Σ_(covered) w_i s_i / C` nếu
`C > 0`, còn lại `null`. `raw_equity_weighted_score = Σ_(covered) w_i s_i`
chỉ là đóng góp của phần có tin trên toàn bộ vốn cổ phiếu; nếu `C = 0` trường
này cũng là `null` để không ngụ ý trung tính. UI luôn ghép điểm với độ phủ.
Tiền mặt thuộc NAV, nhưng không mang sắc thái tin cổ phiếu.

Trong một mã, mỗi cụm sự kiện có một điểm, rồi lấy trung bình ngang các cụm.
Phase 1 chỉ tự gom tiêu đề giống hệt sau chuẩn hóa; `event_key` do caller
khai báo có thể gom thêm, nhưng không được xác minh tự động. Điểm cụm hiện là
trung bình các bài trong cụm. Hợp đồng lưu riêng bài được nhận đầu tiên và bài
đại diện ưu tiên theo SEC filing → thông cáo công ty → báo chí; thứ tự nguồn
không được diễn giải là thứ tự xuất hiện trên thị trường. Không có suy luận
nhân quả về tác động của tin lên giá.

Kịch bản: `new_NAV = cash + Σ V_i(1+r_i)`,
`ΔNAV = Σ V_i r_i`. Ví dụ AAPL 10.000 USD tăng 5% và MSFT 2.500 USD giảm 4%
cho `ΔNAV = +400 USD`, tương đương `+3,2%` khi không có tiền mặt. Kịch bản
không tính phí, cổ tức, thuế, FX hoặc khớp lệnh.

Panel cũ dùng `q = K × w_i` mỗi bài công ty và `q = 1` mỗi bài bối cảnh,
cho thấy số bài làm lệch tỷ trọng hiệu dụng. Cả hai dùng cùng input đã qua
kiểm tra thời gian, nhưng phép tính cũ vẫn đếm mỗi bài một phiếu.

## Nguồn, thời gian và giới hạn

- Universe: 50 mã được chọn ngày 15/11/2026, mapping lấy từ
  [SEC](https://www.sec.gov/files/company_tickers_exchange.json). Chưa xác
  minh riêng loại chứng khoán, vốn hóa, thanh khoản và quyền dùng dữ liệu giá.
  Không coi rổ hiện tại là thành phần lịch sử của một chỉ số.
- Calendar: [NYSE 2026–2028](https://www.nyse.com/trade/hours-calendars),
  giờ New York, ngày nghỉ và đóng sớm theo lịch công bố. Hệ thống từ chối năm
  ngoài phạm vi. Đóng cửa đột xuất cần cập nhật lịch.
- Tin đủ điều kiện nếu có ba xác suất hợp lệ, ngày đăng, lúc nhận và lúc chấm
  có timezone, thứ tự thời gian nhất quán và đều không sau quyết định. Tin
  không đủ điều kiện được ghi reason code.
- Giá tham chiếu phải có thời điểm nguồn và lúc nhận không sau quyết định.
  Chỉ quyết định sau khi phiên chính hoàn tất. Lịch chỉ trả **phiên có thể
  giao dịch sớm nhất**, không khẳng định khớp ở Open hoặc bất kỳ giá nào.
- `LIVE_CAPTURED_PIT` là nhãn caller có thể gửi trong request. API không
  xác thực chữ ký hay receipt nguồn, nên phản hồi luôn nói rõ provenance do
  caller khai báo; không gọi dữ liệu là PiT đã kiểm chứng.

## Trước Phase 2/3

Chốt nguồn tin và giá Mỹ có quyền dùng; đưa vào adapter và receipt bất biến
theo thời điểm nhận thực. Đánh giá định danh mã và sự kiện trên tập gán nhãn
độc lập. Muốn kiểm định giao dịch phải có giá vào/ra thực thi sau quyết định,
corporate actions, chi phí, so sánh price-only và kiểm thử ngoài mẫu.
