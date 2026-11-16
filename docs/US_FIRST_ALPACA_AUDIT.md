# Kiểm tra mẻ Alpaca đầu tiên

Ngày 15/11/2026. Capture ghi nhận 420 thanh giá và 652 bản ghi tin Alpaca, tất cả thuộc diện hồi cứu. Mốc quan sát giá sau cutoff của phiên 13/11 nên chưa có mẫu giá live PiT đủ điều kiện. Số 51 đã báo trước đó được đọc khi tiến trình đang ghi và không phải tổng cuối cùng.

Replay H=5 tạo 170 hàng panel, 70 hàng được đánh giá walk-forward và một kỳ rổ holdout có sự kiện. Không có khoảng tin cậy bootstrap lợi suất; không suy ra hiệu quả đầu tư từ phép thử này.

Batch gán nhãn có 200 tác vụ: 176 headline và 24 hồ sơ SEC cấu trúc. Bản dev có 144 tác vụ, holdout 56. Đối chiếu hai split thấy không trùng `item_id` hoặc `observation_id`, nhưng có 5 tiêu đề nguyên văn xuất hiện ở cả hai phía: 3 tiêu đề tin và 2 mẫu tiêu đề hồ sơ SEC. Các tiêu đề tin liên quan tới nhiều mã, vì chia theo ticker/tuần không đảm bảo tách bài hoặc sự kiện giữa các mã. Trùng tiêu đề SEC có thể chỉ do cách đặt tên hồ sơ chung, không tự chứng minh cùng sự kiện.

Không dùng split hiện tại để ước lượng hiệu quả tổng quát của FinBERT trước khi xử lý rò rỉ theo bài/sự kiện và kiểm tra các sự kiện gần ranh giới tuần. Giữ nguyên file gốc để kiểm toán. Không xem kết quả benchmark hay điều chỉnh mô hình theo holdout. Các CSV chưa có nhãn con người; cần hai lượt gán độc lập và phân xử theo giao thức Phase 2.5.

## Split v2 theo bài và cụm sự kiện

**Cập nhật: split v2 không còn đủ điều kiện làm holdout độc lập.** Rà soát thủ công phát hiện các tiêu đề khác nhau về cùng nhà máy biodiesel Chevron tại Ralston và cùng sự cố Outlook ở cả dev và holdout. Bộ kiểm tra tự động trước đây không bắt được. Benchmark từ chối hash holdout này; các CSV v2 giữ lại để kiểm toán.

## Split v3 có ràng buộc sự kiện đã rà soát

Batch gốc 200 tác vụ được chia lại sau khi thêm năm nhóm liên kết từ tiêu đề: Chevron Ralston, Microsoft Outlook, UnitedHealth/Surgery Partners, ExxonMobil Longtail và Eli Lilly Taltz/Zepbound. Danh sách `us_batch_reviewed_event_groups_v1.json` lưu `task_id` và được băm trong manifest của split. Kết quả 149 dev (132 tin) và 51 holdout (44 tin). Không nhóm nào trong năm nhóm bị chia đôi; `item_id` và tiêu đề tin nguyên văn không giao nhau giữa hai tập. Hash dev `785745016a0e2a2b948aee3ae5e9a7838764ed1d214bd1a96ecdf043a7221fc8`, holdout `bfdb4b2b3c50f5b08f9ea49f7c5e6addc9960b32f4f9cf9c422cc67b73c36aec`.

Đây là **bản chia có kiểm soát một số sự kiện đã nhận diện**, chưa phải chứng nhận không rò rỉ mọi sự kiện. Cần hoàn tất rà soát các cặp khác và gán nhãn độc lập trước khi gọi đây là holdout khóa. Báo cáo Track D đã đổi phạm vi so sánh sang toàn bộ bài của cùng mã qua các tuần, để một cặp bài cùng sự kiện vắt qua tuần có thể trở thành false split thay vì biến mất khỏi mẫu số.

Tách cạnh theo bài đa mã và cụm `cluster_events_v2` thay cho ràng buộc toàn bộ tuần. Split mới có 150 dev (133 tin, 17 SEC) và 50 holdout (43 tin, 7 SEC). Hash JSONL dev `f85da67e62a2bec98731ede148dc283533feab05f35df27f0eed2cca6046648f`; holdout `35a781cabb8c23c81950659c1b8d702db8a4fc0f69f5c31ba509fcbd9db69614`. Chạy lại trên ledger cho hash trùng và vượt kiểm tra giao nhau về ID, khóa sự kiện, URL, tiêu đề và token chuẩn hóa. Kiểm tra này chỉ bao phủ các quy tắc máy; sự kiện diễn đạt khác nhau vẫn có thể lọt qua, cần rà soát thủ công trước khi khóa đánh giá. Phân bổ dùng hash tất định, chưa tối ưu cân bằng từng mã và không phải holdout theo thời gian.

Đã tạo bốn CSV `us_{dev,holdout}_annotator_{a,b}_v2.csv`; thực hiện gán nhãn độc lập theo giao thức. Tránh xem hoặc điều chỉnh theo holdout trong lúc hiệu chỉnh development.

## Split v4 và kiểm toán điểm FinBERT

Danh sách 22 nhóm được đề xuất trong tệp người dùng đều đối chiếu được `task_id` với batch. Bảy nhóm vẫn cần phân xử vì cùng chủ đề chưa chứng minh cùng sự kiện: hai cuộc điều tra bảo hiểm khác nhau, Medicaid so với trợ cấp ACA, chiến dịch quảng bá Foundayo so với kết quả thử nghiệm, ba bài Anthropic khác nội dung, hai nhận định cổ phiếu 2027, hai bài Michael Burry khác trọng tâm, và hồ sơ Apple AI tại Trung Quốc so với thông qua quy định. Bản v4 dùng 15 nhóm rõ hơn, lưu trong `us_batch_curated_event_groups_v4.json`, để tránh ép các sự kiện độc lập thành một cụm. Kết quả 150 dev / 50 holdout, bốn phiếu CSV v4 đã được tạo. Chưa chứng nhận mọi sự kiện khác đã tách đúng.

Kiểm toán gom cụm tiếp theo trên cùng batch cho thấy phiên bản đầu khớp 0/21 cặp trong 15 nhóm chọn lọc, quy tắc mới khớp 4/21. Trên 22 nhóm ứng viên là 0/30 rồi 4/30; đây chỉ là chẩn đoán trong mẫu. Rà toàn bộ 652 tin phát hiện URL `/quote/NVDA` được hai bài khác sự kiện dùng chung, các mục “What's Going On” về doanh nghiệp khác nhau và các bản tin giá mục tiêu của các công ty chứng khoán khác nhau. Quy tắc mới chỉ xem URL bài viết cụ thể là tín hiệu mạnh, giữ đối chiếu từng cặp trong cụm, chặn mẫu tin lặp theo ngày có article ID khác nhau và kiểm tra tên nhà phân tích/số giá mục tiêu khi tiêu đề có đủ dữ liệu. Mười cụm nhiều bài còn lại trên toàn bộ ledger đã được rà tiêu đề; việc này không thay thế nhãn sự kiện độc lập.

Lexicon thủ công v2 có thêm cụm từ báo tài chính và phép so sánh giá mục tiêu tường minh; nó vẫn chỉ là baseline dễ kiểm tra, không phải từ điển Loughran–McDonald được cấp phép hay nhãn người. FinBERT trong ledger giữ nguyên, không ghi đè theo quy tắc số học. Dữ liệu batch và holdout đã được xem để sửa cả gom cụm lẫn lexicon, nên mọi phép đo trên split v4 sau sửa là mô tả trong mẫu; muốn benchmark độc lập phải khóa thuật toán trước rồi thu batch mới theo thời gian và gán nhãn mù.

`US_FINBERT_EMPIRICAL_LEDGER_AUDIT.md` đọc 652 điểm FinBERT thật trong ledger và phân tích 22 **nhóm ứng viên**. Bản báo cáo này đo phân phối và bất đồng mô hình, không đo độ chính xác. Snapshot API hiện mặc định loại các mẫu tin nghi nhiễu theo quy tắc hẹp, giữ `relevance_filter=none` để đối chiếu; lý do loại được ghi trong `excluded_items`. Quy tắc chưa được hiệu chuẩn bằng nhãn độc lập nên vẫn cần giám sát false positive trước khi dùng điểm vào quyết định tài chính.

## Triage mức liên quan của tiêu đề

Trên 150 tác vụ dev, quy tắc thử nghiệm nhận 53 tiêu đề có nhắc mã/tên theo từ điển, 80 tiêu đề không có từ khớp và 17 hồ sơ SEC. Đây không phải tỷ lệ gắn sai: một bài ngành có thể không nhắc tên công ty và từ điển có thể thiếu alias; việc xuất hiện tên cũng không chứng minh công ty là chủ thể chính. Bản rà soát `us_dev_relevance_triage_unvalidated.csv` để người đọc kiểm tra; không dùng làm nhãn chuẩn hay tự động loại dữ liệu khỏi điểm sản phẩm.

CLI nhận `--news-lookback-days 60`, và script mẻ đầu mặc định yêu cầu 60 ngày tin, tối đa 200 trang. Nếu còn trang tiếp theo sau giới hạn, bước tin báo lỗi thay vì khẳng định đã đủ dữ liệu. Các bản tin lịch sử thu về lần đầu vẫn là hồi cứu; không trở thành bằng chứng point-in-time. Chưa chạy quét 60 ngày hay benchmark sau thay đổi này.

## Thử nghiệm nhận diện tên và nhãn gợi ý

Từ điển bỏ hậu tố pháp lý và thêm một số alias. Batch dev có 97 tiêu đề khớp tên/sản phẩm, 15 khớp từ ngành, 21 chưa rõ và 17 SEC; đây là thống kê của quy tắc, không phải độ chính xác. Nhãn máy không phân biệt được đầy đủ chủ thể chính, so sánh phụ hay tác động ngành. Snapshot API và giao diện hiện mặc định lọc hẹp các mẫu nghi nhiễu, có lựa chọn `none` để đối chiếu điểm thô; quy tắc chưa được xác minh bằng nhãn người. Xem `artifacts/phase3/US_PHASE3_RELEVANCE_FILTER_COMPARISON.md`; không chọn phương pháp theo kết quả đã quan sát.

Hai file `us_{dev,holdout}_preannotated_draft_for_human_review.csv` chứa gợi ý máy; tone trống khi lexicon không có bằng chứng, hàm ý và cụm sự kiện để trống. Đây không phải nhãn chuẩn hay hai lượt gán nhãn độc lập. Khi người chấm nhìn gợi ý sẽ có nguy cơ neo quyết định; muốn đo độ chính xác với nhãn độc lập cần quy trình gán mù trước khi xem gợi ý. Không chạy benchmark so với chính lexicon/cụm đã tạo gợi ý vì chỉ số tự đối chiếu đó không đo được độ đúng với thực tế.
