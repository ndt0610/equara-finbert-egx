# Rà soát demo ngày 06/11/2026

## Kết luận nghiệm thu

Chưa hoàn thiện để bàn giao cuối cùng. Đây là nguyên mẫu có luồng dữ liệu thật, phép tính danh mục có cấu trúc rõ, và bộ quy tắc Tin + Giá chạy được; còn lỗi đầu vào ảnh hưởng điểm/nhãn, vận hành chưa bền, thông tin hiển thị và tài liệu chưa thống nhất. Không quy đổi thành phần trăm hoàn thành vì chưa có danh sách nghiệm thu được cân trọng số.

Đợt này rà soát code và chạy kiểm tra, không thay đổi bộ quy tắc hay tự chọn lại ngưỡng. Đã cài pytest trong môi trường hiện hữu để chạy các kiểm thử được cung cấp. Đã khởi động lại backend để kiểm tra API. Không có EODHD News token trong tiến trình kiểm tra; các lần live dưới đây sử dụng nguồn thay thế đang cấu hình.

## Bằng chứng chạy hiện tại

- Bấm Tin + Giá/COMI trên trình duyệt thực tế ban đầu nhận network_error; kiểm tra HTTP xác nhận cổng 8124 không nhận kết nối. Trang còn mở và widget TradingView có giá không chứng minh backend hoạt động.
- Sau khởi động lại: health ok; API một mã COMI, danh mục COMI/ETEL/FWRY, danh mục theo vốn 50/30/20 và Tin + Giá ETEL đều trả HTTP 200. Việc khởi động lại chỉ chứng minh khôi phục được dịch vụ trong lượt này, chưa giải quyết sự ổn định qua các phiên làm việc.
- Danh mục theo vốn live: C=1; S=0,3589284727; khoảng giới hạn [S,S]. COMI 11 tin, ETEL 15 tin, FWRY 7 tin. Nhãn FinBERT của cả ba trung tính vẫn tương thích với điểm dương, vì nhãn dùng lớp xác suất lớn nhất còn điểm dùng P+−P−.
- Tin + Giá ETEL: ngày giá 05/11/2026; R5=+7,035807%; B=6,161523%; E=11,031452%; S=0,0707303861; N_eff=3,142558; 4 nhóm; nhãn Giữ do nhánh điểm tin cân bằng.
- Ledger ETEL: 118 bản ghi; 103 đã chấm; 41 chưa phân xử; 76 bối cảnh; 1 trùng; 0 loại ở bước thu thập. Các số đã chấm/chưa phân xử chồng lấn, không phải các nhóm có thể cộng với nhau. Bước quyết định riêng loại 77 bản bối cảnh, 14 bản chưa xác minh công ty và 23 bản ngoài cửa sổ ngày.

## Phát hiện cần xử lý

### P1 — Tin thể thao thật đã vào điểm ETEL

candidate_service.py chỉ loại mẫu TradingView “price and chart”, sau đó khớp alias và chấm tin. Không dùng đầy đủ luật thể thao/trang dữ liệu của relevance.py trong phần danh mục nâng cấp.

Lượt live có nhóm chứa tiêu đề: “Al Mokawloon Al Arab vs El Masria Lell Etesalat (Telecom Egypt) - Egypt Cup - OneFootball”, ngày 28/10/2026. Điểm headline 0,0692574251. Nó đi vào S và N_eff của cổ phiếu ETEL.

Tính lại trên cùng lô, chỉ bỏ bài này: S từ 0,0707303861 thành 0,0711282559; N_eff từ 3,142558 thành 2,270790. Nhãn vẫn Giữ trong ca này. Không được nói lỗi đã làm đổi nhãn live, nhưng nó làm sai điểm và số nhóm, đặc biệt số nhóm vượt/không vượt điều kiện 3 cho nhãn mạnh.

Cần: dùng chung cơ chế xác định đúng đối tượng/nội dung tài chính; thể thao và trang báo giá được giữ trong nhật ký với lý do, không vào điểm quyết định. Khớp tên không đủ để tuyên bố đã xác minh doanh nghiệp.

### P1 — Trọng số tuổi tin chỉ giảm tương đối

Trong rules.py: S=Σ(w·s)/Σw; N_eff=(Σw)^2/Σ(w²). Với một nhóm, S=s và N_eff=1 bất kể w. Nếu cả lô cùng già thêm một lượng thời gian, hệ số chung cũng triệt tiêu cho đến khi có bài vượt cửa sổ 30 ngày.

Probe tổng hợp (giá và xác suất giả lập, không phải kết quả thị trường): một bài S=0,85 ở tuổi 1 ngày và 29 ngày đều cho S=0,85 và Mua. Đây là tính chất của trung bình chuẩn hóa, không phải lỗi phép chia. Nó chưa đáp ứng cách hiểu “tin cũ thì toàn bộ bằng chứng yếu dần”.

Cần: phân biệt sắc thái S với mức đủ/mới của bằng chứng. Định nghĩa thêm độ mới tuyệt đối và điều kiện dữ liệu tối thiểu, rồi kiểm tra độ nhạy trước khi chốt mốc. Không tự nhân một hằng số mới để gọi là đã tối ưu.

### P1 — Nhãn Giữ trộn các trường hợp có mức rủi ro khác nhau

Probe bộ phân loại, S=−0,8; B=5%; E=10%; N_eff=4: R5=−9% cho Bán mạnh, R5=−11% cho Giữ. Code thực hiện đúng chủ trương tránh bán đuổi nhưng không có phép tính chứng minh giá đang giảm quá đà hoặc sẽ hồi.

S cân bằng thì Giữ ngay cả khi giá giảm mạnh. Tin tích cực kèm giá giảm mạnh cũng Giữ. Một nhãn đang bao gồm cân bằng, chưa xác nhận, xung đột và cực đoan.

Cần: giữ hệ năm nhãn người dùng yêu cầu, nhưng bổ sung trạng thái rủi ro/điều kiện chờ riêng và chốt lại ý nghĩa hành động của nhánh cực đoan. Phân vị lịch sử chỉ đo mức bất thường, không đo định giá hay quá phản ứng.

### P1 — Giá thô có thể làm đổi nhãn vì sự kiện doanh nghiệp

yahoo_daily.py dùng auto_adjust=False và Close, không đối soát cổ tức/chia tách trước khi tính R5, B, E. Lịch 5 phiên là 5 hàng dữ liệu có sẵn, chưa kiểm tra thiếu phiên/khối lượng giao dịch. Đây là rủi ro code đã xác định, chưa chứng minh đã xảy ra trong ETEL hiện tại.

Cần: tách giá hiển thị với chuỗi lợi suất đã xử lý sự kiện doanh nghiệp; kiểm tra lịch giao dịch, phiên thiếu, phiên không giao dịch và timestamp. Không coi mức đổi do chia tách là phản ứng tiêu cực của thị trường.

### P1 — Demo và cấu hình chưa bàn giao bền vững

Đã trực tiếp gặp backend dừng. Khởi động tách tiến trình từ công cụ cũng không duy trì được cổng ở lần kiểm tra sau; chưa xác định chắc nguyên nhân kết thúc tiến trình. Lần cuối khôi phục bằng phiên chạy uvicorn. Token EODHD News thiếu sau restart. Không nên tuyên bố EODHD đã sẵn sàng chỉ vì từng kết nối thành công trước đó.

Cần: một bộ chạy do người dùng chủ động mở và giữ sống, log lỗi, kiểm tra sẵn sàng, cấu hình nguồn có thể khôi phục an toàn, thông báo trạng thái hiện thời thay vì chỉ health lúc mở trang. Xác nhận chạy lại sau đóng/mở ứng dụng trước nghiệm thu.

### P2 — Luồng giải thích chưa thống nhất

- rules.py đã tạo S và nhãn từ nhóm tiêu đề tạm; group_headlines vẫn trả not_aggregated_events_unresolved và app.js ghi “Chưa cộng thành điểm công ty”. Cần ghi rõ lớp ứng viên, lớp đủ điều kiện, nhóm tạm và điểm dùng trong quy tắc.
- decision.excluded có lý do loại khỏi nhãn nhưng frontend chưa trình bày riêng đầy đủ danh sách này. “0 loại” ở collector không có nghĩa tất cả tin vào nhãn.
- app.js tạo biến provenance và tiêu đề “Các ngưỡng lấy từ đâu?” nhưng không append provenance; chỉ append các thẻ sources. Tiêu đề đã hứa không thực sự được đưa vào DOM.
- Công thức vẫn chủ yếu là câu chữ/dòng ký hiệu; chưa có biểu thức phân số và ví dụ thế số hoàn chỉnh. Câu “trung bình điểm nhóm sau khi nhân trọng số” cần làm rõ phép chia tổng trọng số.
- Nhiều khối chữ luôn mở; widget TradingView nằm trước kết quả, có nguồn/thời điểm khác giá backend. Dễ tưởng nhãn dựa trên giá trong widget. Cần bố cục kết luận → dữ liệu dùng tính → giải thích → chứng cứ chi tiết; ghi rõ nguồn giá nào đi vào nhãn.
- Có bản sao logic phân loại trong JavaScript dự phòng lẫn Python. Cần dùng một nguồn quy tắc, version và trace để tránh sửa một nơi rồi lệch nơi kia.

### P2 — Phạm vi còn giới hạn

STOCK_DIRECTORY có năm mã. Mã ngoài danh sách có thể lấy giá, nhưng Tin + Giá không thu tin công ty và không đủ nhóm để gán nhãn. Danh mục bị giới hạn tối đa năm vị thế theo schema. UI cần nêu đúng mức hỗ trợ, không tạo cảm giác mọi mã EGX đã phân tích được.

### P2 — Tài liệu và kiểm thử chưa đồng bộ

docs/TIN_GIA_V1_TRANG_THAI.md còn nói không có giá, không có nhãn và dùng EODHD cho giá. context_service.py còn docstring “nhãn luôn abstain”. Đây là nội dung lỗi thời so với triển khai hiện tại.

Chạy toàn bộ pytest bị chặn ở thu thập bởi thiếu matplotlib và artifacts/local_inference_api_results.json. Không có cơ sở công bố toàn bộ tests pass trên gói hiện tại.

Chạy riêng 4 tệp test_core.py, test_coverage.py, test_dedup_v3.py, test_live_data_display.py: 91 pass, 6 fail. Bốn fail liên quan test vẫn đặt EODHD_API_TOKEN trong khi code dùng EODHD_NEWS_API_TOKEN; hai fail về nội dung UI/chi tiết gauge cũ. Các fail này chưa chứng minh sáu lỗi thuật toán; chúng chứng minh bộ kiểm thử không còn đồng bộ. Trong thư mục tests hiện không tìm thấy kiểm thử gọi evaluate_rules hay luồng tin_gia.

## Những phần hợp lý nên giữ

- Tách danh mục theo vốn với quy tắc Tin + Giá là đúng yêu cầu.
- Danh mục: chuẩn hóa vốn, phân biệt có/không có tin, S trên phần vốn có tin và khoảng [C·S−(1−C), C·S+(1−C)] có cơ sở đại số rõ. C=100% làm khoảng co về một điểm không có nghĩa mô hình chắc chắn đúng.
- Không tự coi thiếu tin là trung tính/Giữ.
- Giá và điểm tin có thể truy lại nguồn/nhóm; bảng quy tắc có điều kiện rõ.
- Dùng B/E riêng từng mã có lý do thiết kế tốt hơn một mức % cố định cho mọi mã; lựa chọn P75/P90 vẫn là quy ước cần đánh giá, chưa phải mốc tối ưu được chứng minh.
- Tin bối cảnh để riêng là lựa chọn có thể bảo vệ được khi chưa mô hình hóa mức liên quan tới từng doanh nghiệp; hiện chưa đáp ứng một mô hình vĩ mô đầy đủ.

## Thứ tự hoàn thiện và điều kiện nghiệm thu

1. Sửa vòng đời demo/cấu hình, kiểm tra khởi động lại ổn định.
2. Sửa đúng đối tượng, loại thể thao/trang dữ liệu và thống nhất ledger: mỗi bài có trạng thái vào/không vào nhãn, lý do và group_id.
3. Chốt lại phân biệt sắc thái, độ mới, độ đủ bằng chứng và trạng thái rủi ro; giữ năm nhãn nhưng không để “Giữ” che các trạng thái đối nghịch.
4. Chuẩn hóa giá/phiên/sự kiện doanh nghiệp và cửa sổ tin. R5 hiện là cửa sổ chung; biến động 1/3/5 phiên từng bài chỉ là mô tả, không được dùng để nói bài gây ra X% giá.
5. Làm UI theo một câu chuyện nhất quán, có công thức chuẩn, ví dụ thế số và kết quả truy nguyên từng bước; cập nhật tài liệu vấn đáp cùng phiên bản.
6. Khôi phục môi trường test; sửa các test lỗi thời theo hợp đồng đã chốt; thêm kiểm thử ý nghĩa cho Tin + Giá (thể thao, sai doanh nghiệp, tin cũ, ngày tin, thiếu dữ liệu, ranh giới nhãn, cổ tức/chia tách). Chạy cả luồng người dùng thực tế.
7. Muốn tuyên bố hiệu quả đầu tư hoặc tối ưu ngưỡng: cần bộ dữ liệu theo thời điểm, đánh giá ngoài mẫu và so với giá-only/nắm giữ; 9 cấu hình độ nhạy không thay thế bước này. Bản quy tắc thử nghiệm không bắt buộc đợi bằng chứng lợi nhuận để tồn tại, nhưng phải ghi đúng mức bằng chứng.

Chưa sửa các phát hiện thuật toán trong đợt rà soát này. Bản báo cáo là căn cứ để chốt một đợt sửa có thứ tự, không phải biên bản nghiệm thu đạt.
