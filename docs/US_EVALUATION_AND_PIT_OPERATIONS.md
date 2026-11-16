# Bộ đánh giá tin và thu thập PiT

## Bộ tác vụ ngày 15/11/2026

Thư mục `artifacts/evaluations/us_eval_20261115_v2` có 240 cặp tin–mã,
gồm 180 dev và 60 holdout, chọn theo từng mã từ 60 ngày dữ liệu đã thu thập.
Mẫu có chủ đích cân bằng theo mã, không đại diện tỷ lệ tin ngoài thị trường.
Đã loại item ID và tiêu đề trùng nguyên văn trong batch 200 tác vụ trước; có thể còn tin viết lại của sự kiện
đã từng xem. Chia theo nhóm liên kết tự động, chưa có xác nhận độc lập mọi cặp
sự kiện qua ranh giới, nên cần rà rò rỉ trước khi dùng holdout để báo cáo.
Không dùng bộ này để ước lượng khả năng dự báo lợi suất.

Hai CSV annotator A/B là phiếu trống. Hai người chấm độc lập theo
`docs/US_PHASE25_ANNOTATION_PROTOCOL.md`, không xem điểm mô hình hoặc nhãn của
nhau. Khởi đầu bằng 20 dòng dev, so sánh bất đồng, thống nhất quy tắc rồi chấm
lại độc lập; giữ holdout cho đến khi khóa quy tắc. Phân xử bất đồng, kiểm tra
và khóa bằng công cụ Phase 2.5 trước khi báo cáo. Không xem bản gợi ý tự động
như nhãn người. Nếu chỉ có một người, ghi rõ và không tính đó là hai người độc lập.

Ngày 15/11/2026: 20 dòng đầu dev đã xuất hiện cùng gợi ý nhãn trong chat và
được dùng để bổ sung quy tắc nghi nhiễu Carvolix và một số mẫu ngân hàng phân
tích cổ phiếu khác. Xem 20 dòng đó là ví dụ huấn luyện, không dùng để đo đồng
thuận mù hoặc kiểm định độc lập. Những nhãn gợi ý chưa được xác minh, chưa ghi
vào CSV và không phải gold; người chấm phải quyết định độc lập với các dòng
đánh giá còn lại. Kiểm tra thêm rò rỉ sự kiện trước khi khóa holdout.

Rà sơ bộ ngày 15/11/2026: `dev_codex_ai_provisional.csv` là nhãn nháp do AI
gán từ tiêu đề cho 180 tác vụ, không đọc điểm FinBERT; 100 hàm ý kinh tế và
một relevance được để trống khi chưa đủ căn cứ. Không nhập nhãn này như nhãn
người độc lập hay dùng làm gold. Các khóa sự kiện chỉ là gợi ý cục bộ chưa hoàn
chỉnh. Hai phiếu gán nhãn mù gốc không bị sửa.

Rà liên kết chéo: `cross_split_candidates.csv` có 32 cặp ứng viên tạo bằng
so sánh token trong 168 giờ và liên kết chính xác; `cross_split_ai_review.csv`
là rà sơ bộ của AI. Không phát hiện liên kết chính xác; các ứng viên tìm được
giống mẫu tin nhưng khác phiên, công ty hoặc nhà phân tích. Rà soát này có thể
bỏ sót cách viết khác hoặc sự kiện liên quan kéo dài quá 168 giờ, không chứng
minh holdout hoàn toàn độc lập. Cần người kiểm tra trước khi khóa benchmark.

Rà mở rộng tiếp: `dev_codex_ai_provisional_v2.csv` điền 100 hàm ý kinh tế
trước đó để trống, có giải thích theo tiêu đề; một dòng còn thiếu relevance.
Đây là ý kiến AI, không phải nhãn chuẩn. `cross_split_extended_review.csv`
ghi 74 cặp ứng viên, bao gồm các cặp nghi trùng Olumiant và Foundayo. Rà thêm
tìm thấy hai phát biểu của lãnh đạo Goldman trong cửa sổ cuộc gọi kết quả quý.
HOLDOUT V2 được đánh dấu không dùng benchmark do nguy cơ trùng sự kiện; xem
`HOLDOUT_BLOCKED_EVENT_OVERLAP.md`. Hai nguồn bài holdout về Lilly chưa mở
được, nên cần xác minh thêm. Không thay đổi split/manifest gốc; việc phân chia
lại các bài đã xem không tạo ra holdout hoàn toàn mới.

Rà tiếp dev: `dev_codex_ai_review_v3.csv` sửa 10 dòng sai/thiếu, trong đó tin
NVIDIA, UnitedHealth, Lilly và Microsoft từng bị đánh dấu nhầm không liên quan.
Dòng AI TOP ATOM có thêm bằng chứng từ thông cáo GIGABYTE: hệ thống dựa trên
NVIDIA DGX Spark; tone vẫn xét theo tiêu đề. Ba dòng còn để trống relevance và
hàm ý khi cần đọc nguồn. 137 khóa singleton chỉ là giả thuyết, 95 category
`OTHER` là gợi ý mặc định cần rà; first mention không suy từ mẫu không đầy đủ.
`dev_ai_review_priority_v3.csv` là 87 trường hợp ưu tiên, không có nghĩa những
dòng còn lại đã được xác thực. Không đổi hai phiếu mù và không khóa nhãn AI
thành gold. Danh mục nhóm JPM/Qatar và CVX/South32 là đề xuất cần người xác nhận;
hai tin CVX về bão nêu rút người và ngừng sản xuất nên tạm giữ riêng, liên hệ
về sự kiện nền cần người phân xử. Ba báo cáo nắm giữ ASOS của GS khác ngày và
khác ID nguồn, không tự gộp. Hai headline cá voi UNH giống hệt nhưng cách năm
ngày, không tự coi cùng sự kiện.

Rà v4: `dev_codex_ai_review_v4.csv` có gợi ý đủ bốn trục cho 180 dòng; nguồn
được mở để xem ba dòng còn thiếu. Đây là nhãn AI, body nguồn hiện tại không
được chứng minh là bản Equara lưu tại cutoff. Bốn dòng thuộc hai cặp JPM/Qatar,
CVX/South32 có thông cáo hỗ trợ; hai cập nhật bão giữ riêng chờ phân xử. 138
singleton chưa xác minh, first mention vẫn để trống. Xem `dev_event_source_review_v4.md`.
`dev_blind160.jsonl` và hai phiếu CSV tương ứng là mẫu chấm độc lập sau khi bỏ
20 dòng đã lộ; kiểm tra token bảy ngày không phát hiện trùng, nhưng không chứng
minh tuyệt đối không chung sự kiện. Chưa có nhãn người hay gold dev được khóa.

Rà v5: 138 singleton được so trong phạm vi mẫu dev với các mục liên quan;
121 mục không có cặp đạt ngưỡng và 17 có ứng viên. Không coi số không có ứng
viên là chứng minh không trùng. `dev_event_pairs_review_v5.csv` ghi 15 cặp AI
rà, còn cặp bão CVX và đầu tư CAT chưa xác định ranh giới sự kiện. Các cặp tin
nhiễu UNH lặp khuôn được kiểm tra riêng. `dev_codex_ai_review_v5.csv` vẫn là
nháp AI; `dev_ai_review_priority_v5.csv` là hàng ưu tiên sau khi chấm mù.
Xem `dev_event_audit_v5.md`; tập chưa có nhãn người hay gold được khóa.

## Vận hành hằng ngày

`scripts/run_us_pit_scheduled.ps1` kiểm tra phiên NYSE và chỉ quét trong khoảng
sau giờ đóng cửa +20 phút đến trước 20:00 ET. Chạy giá SIP trước, rồi SEC,
tin Alpaca và chấm phần thiếu. Mỗi lượt tạo JSON và log riêng trong
`artifacts/pit_daily`; lỗi hoặc vintage giá thiếu khiến tiến trình trả lỗi.
Lịch tĩnh chỉ phủ 2026–2028 và không biết đóng cửa đột xuất. Sổ cái health
không chứng minh độ phủ tin đầy đủ, hay mức giá có thể khớp tại phiên mở cửa.

Kịch bản giờ Việt Nam 05:30 thứ Ba–thứ Bảy nằm trong cửa sổ ET cả mùa hè và
mùa đông. Máy cần đang chạy, có mạng, đúng múi giờ; nếu lỡ phiên không gán lại
thời điểm quá khứ. Script đọc key mã hóa DPAPI trong
`%LOCALAPPDATA%\Equara\pit_credentials` dưới chính tài khoản Windows đang chạy;
khóa cũ đã xuất hiện trong chat nên nên thay tại Alpaca. Lịch Codex được tạo
05:30 giờ Việt Nam từ thứ Ba đến thứ Bảy; cần máy và Codex có khả năng chạy lúc
đó. Lịch không đảm bảo chạy khi máy tắt hoặc mất mạng, và cần theo dõi log.
