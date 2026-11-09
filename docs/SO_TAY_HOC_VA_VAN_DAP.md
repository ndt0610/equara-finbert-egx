# Sổ tay hiểu và bảo vệ dự án Equara

Phiên bản: holder-news-price-rules-2, 06/11/2026. Đọc theo thứ tự, tự tính lại ví dụ trước khi học câu trả lời vấn đáp.

## 1. Mình đang giải quyết bài toán gì, cho ai?

Đối tượng là người đang nắm cổ phiếu Ai Cập (EGX), đọc tiêu đề tiếng Anh và cần biết tin tìm được đang nghiêng tích cực hay tiêu cực, phần vốn nào có thông tin, và tin có đồng hướng với diễn biến giá hay không. Chưa phải sản phẩm đã đánh giá cho thị trường Việt Nam, tin tiếng Việt hay giao dịch trong ngày.

Có ba sản phẩm trí tuệ khác nhau: tái dựng kiến trúc bài gốc; nâng cấp danh mục theo vốn và độ phủ; nâng cấp Tin + Giá cho một mã. Hai nâng cấp phục vụ hai câu hỏi khác nhau. Không lấy tỷ trọng vốn để gán nhãn cho từng cổ phiếu trong Tin + Giá.

## 2. Bài gốc thật sự nói gì?

Nguồn chính: Mohamed Hendawy, “Building AI-Powered Financial Sentiment Analysis with Hugging Face and FinBERT”, Medium, 06/03/2026. Đã đọc trực tiếp bản PDF `CODEX_BAN_GIAO/bai_bao_goc/Topic 1 - SLM.pdf`, trang 1–5 có nội dung; trang 6 là chân trang. Đây là bài mô tả kiến trúc kỹ thuật, không phải bài thực nghiệm chứng minh lợi nhuận.

Trang 1 giải thích FinBERT và ba nhãn. Trang 2 mô tả ba tầng: gom tin → suy luận NLP → tổng hợp/API. Trang 3 là trình tự yêu cầu một mã. Trang 4 mô tả fallback nguồn, top 10–15 tiêu đề, top_k=3, softmax và danh mục tối đa 5 mã, mỗi mã 1–2 tiêu đề. Trang 5 minh họa 4 tin vĩ mô + 2 tin mỗi mã, và đánh đổi giữa gọi dịch vụ bên ngoài với tự chạy model.

Luồng bài gốc: người dùng mở mã → frontend gọi REST API → backend lấy tin doanh nghiệp từ EODHD, dự phòng Google; lấy bối cảnh Ai Cập từ EODHD, dự phòng BBC rồi Google → gộp/loại trùng → gửi tiêu đề tới FinBERT qua Hugging Face → nhận ba xác suất mỗi tiêu đề → tổng hợp và trả JSON → giao diện hiển thị sắc thái.

EODHD trong luồng này là nguồn tin; nó không thay FinBERT. Hugging Face là nơi phục vụ mô hình; FinBERT là mô hình. Docker nếu sử dụng là công cụ đóng gói môi trường, không tự tạo ra nguồn giá thời gian thực.

Bài không công bố đầy đủ mã gốc, công thức tổng hợp chi tiết, thử nghiệm ngưỡng Mua/Bán hay kết quả backtest. Vì thế công thức trung bình trong bản tái dựng phải gọi đúng là lựa chọn tái dựng, không gán cho tác giả khi bài không nêu.

## 3. Hiểu FinBERT và phép tính bài mẫu

FinBERT tạo ba logit z. Softmax chuyển chúng thành các số không âm có tổng bằng 1:

\[p_k=\frac{e^{z_k}}{\sum_{j\in\{+,0,-\}}e^{z_j}}\]

`top_k=3` lấy cả ba lớp, không phải lấy ba bài báo. Softmax không tự chứng minh xác suất đã hiệu chuẩn đúng trên EGX. Model đọc sắc thái ngôn ngữ, không trực tiếp đo giá sẽ tăng bao nhiêu.

Điểm một tiêu đề trong bản tái dựng:

\[s_i=p_i^+-p_i^-\in[-1,1]\]

Ví dụ p+=(0,65), p−=(0,20), p0=(0,15): s=0,45. Nghĩa là xác suất lớp tích cực vượt lớp tiêu cực 0,45; không nghĩa giá tăng 45% hoặc xác suất sinh lời 65%.

Với n tiêu đề, bản tái dựng lấy trung bình từng xác suất. Điểm tổng bằng trung bình s. Nhãn là lớp có xác suất trung bình lớn nhất. Ví dụ p+=0,35, p−=0,10, p0=0,55: điểm +0,25 nhưng nhãn vẫn trung tính. Hai đại lượng trả lời hai câu hỏi khác nhau nên không mâu thuẫn.

Tại sao trung bình? Dễ giải thích và tái lập khi bài chưa mô tả trọng số. Nhược điểm: một tin vĩ mô và một tin công ty có sức nặng ngang nhau; mã có nhiều bài có thể chi phối kết quả; tỷ trọng vốn chưa được phản ánh.

## 4. Nâng cấp 1: danh mục theo vốn và độ phủ

Vấn đề: người có 80% vốn ở A và 20% ở B không nên bị mô tả giống người có 20% A và 80% B chỉ vì họ đọc cùng các tiêu đề. Đồng thời, không tìm thấy tin B không có nghĩa B trung tính.

Luồng: nhập mã và vốn → chuẩn hóa tỷ trọng → thu ứng viên theo từng mã, truy vấn rộng hơn khi ít tin → lọc ngày, tên/alias, thể thao, trang dữ liệu, trùng → FinBERT → điểm từng mã → độ phủ và đóng góp theo vốn → khoảng giới hạn do phần vốn thiếu tin. Tin vĩ mô hiển thị riêng, chưa tự gán hệ số tác động lên từng công ty.

Gọi a_i là vốn nhập, w_i=a_i/Σa. Gọi H là tập mã có tiêu đề qua lọc:

\[C=\sum_{i\in H}w_i,\quad r_i=\frac{w_i}{C},\quad c_i=r_i s_i,\quad S=\sum_{i\in H}c_i\]

C là phần vốn có ít nhất một tin phù hợp trong các truy vấn đã gọi. C không đo độ đầy đủ của mọi tin thị trường. S chỉ mô tả phần vốn có tin. c_i cho biết mã nào kéo điểm tổng lên hoặc xuống.

Ví dụ A chiếm 50%, điểm +0,6; B chiếm 30%, điểm −0,2; C chiếm 20% chưa tìm được tin:

\[C=0,8,\quad S=\frac{0,5(0,6)+0,3(-0,2)}{0,8}=0,30\]

A đóng góp 0,375; B đóng góp −0,075; tổng 0,30. Nếu phần vốn chưa biết có sắc thái bất kỳ từ −1 đến +1:

\[L=CS-(1-C)=0,04,\quad U=CS+(1-C)=0,44\]

Đây là hệ quả đại số của miền điểm, không phải khoảng tin cậy thống kê. Nếu C=1, khoảng co về một điểm nhưng mô hình vẫn có thể chấm sai. Nếu C=0, không tính S. Muốn toàn khoảng dương cần CS>1−C; do |S|≤1, C>50% là điều kiện cần, không phải điều kiện đủ. Mốc 50% ở đây suy ra toán học, không phải con số tùy chọn.

Đóng góp cá nhân có thể chứng minh: biến bài toán từ trung bình các tiêu đề sang mô tả theo phần vốn; minh bạch thiếu thông tin; phân rã đóng góp; đối chiếu trước/sau bộ lọc. Không nên tuyên bố đã phát minh trung bình có trọng số hoặc khoảng chặn toán học.

## 5. Nâng cấp 2: Tin + Giá

Vấn đề: cùng tin tiêu cực, giá chưa giảm và giá đã giảm mạnh là hai tình huống khác nhau. Mục tiêu là bộ quy tắc có thể truy nguyên cho người đang nắm giữ, chưa phải dự báo tối ưu.

Luồng: chọn mã → lấy tin và lịch sử giá → xác định đúng đối tượng, bỏ thể thao/trang dữ liệu/trùng → chọn tin có trước ngày giá từ 1 đến 30 ngày → gom tiêu đề gần giống → tính sắc thái và độ mới → tính lợi suất 5 hàng phiên hoàn tất và phân vị lịch sử → áp bảng năm nhãn → hiện nhánh quyết định, trạng thái biến động, từng nhóm tin và lý do không dùng bài khác.

Giá Close được hiển thị để người dùng đọc mức giá. R5 và vùng lịch sử dùng Adj Close do Yahoo cung cấp để giảm méo bởi sự kiện doanh nghiệp. Điều chỉnh do nguồn cung cấp chưa đồng nghĩa đã đối soát độc lập với sàn. TradingView là khung quan sát riêng, không phải chuỗi giá backend đang dùng để gán nhãn.

### Gom tin và thời gian

Tiêu đề giống nhau theo Jaccard ≥0,8 và cách ngày ≤3 được gom tạm. Jaccard bằng số từ chung chia số từ thuộc hợp của hai tập. Điểm nhóm s_g là trung bình điểm bài. Ngày nhóm lấy ngày sớm để bản đăng lại không làm trẻ tin. Đây là chống lặp tiêu đề gần giống, chưa phải nhận diện sự kiện hoàn chỉnh; hai tiêu đề khác nhau nói cùng sự kiện vẫn có thể bị đếm hai nhóm.

Tin cùng ngày giá bị loại khỏi nhãn vì chưa xác minh thứ tự giờ đăng/giờ đóng cửa. Tin mới hơn giá vẫn cho đọc nhưng không được dùng để nói giá đã phản ứng. Tin vĩ mô để riêng vì chưa biết mức phơi nhiễm và yếu tố bất ngờ đối với từng doanh nghiệp.

### Công thức phiên bản 2

Với m nhóm, tuổi a_g tính bằng ngày lịch tới ngày giá và bán rã h=7:

\[w_g=2^{-a_g/h},\quad S=\frac{\sum_g w_gs_g}{\sum_g w_g},\quad F=\frac{\sum_g w_g}{m},\quad D=SF=\frac{\sum_g w_gs_g}{m}\]

S là sắc thái tương đối; F là độ mới trung bình; D là điểm dùng xét nhãn. F không phải xác suất mô hình đúng. Thiếu tin vẫn không gán nhãn; D gần 0 do tin cũ cần được đọc cùng F, không diễn giải thành tin trung tính.

Ví dụ hai nhóm: s1=0,8 tuổi 7 ngày → w1=0,5; s2=−0,2 tuổi 14 ngày → w2=0,25. S=(0,4−0,05)/0,75=0,4667; F=0,375; D=0,175. Bảng quy tắc dùng D nên chưa vượt +0,20. Nếu dùng S trực tiếp như phiên bản trước thì sẽ vào nhánh tích cực. Đây là khác biệt thiết kế có thể kiểm tra được.

Một tin s=0,85 tuổi 1 ngày có D≈0,770; tuổi 29 ngày D≈0,048. Phiên bản cũ cho S=0,85 ở cả hai tuổi vì trọng số triệt tiêu. Kiểm thử hồi quy bảo vệ sửa đổi này.

\[N_{eff}=\frac{(\sum_g w_g)^2}{\sum_g w_g^2}\]

Số nhóm hiệu dụng phản ánh mức tập trung trọng số, không chứng minh các sự kiện độc lập. Ba nhóm có trọng số bằng nhau cho 3; một nhóm lấn át thì tiến gần 1. Nhãn mạnh yêu cầu từ 3, nhưng lựa chọn mốc 3 vẫn là quy ước.

\[R_5=\frac{A_t}{A_{t-5}}-1,\quad B=Q_{0,75}(|R_{5,hist}|),\quad E=Q_{0,90}(|R_{5,hist}|)\]

A là giá điều chỉnh. Hiển thị % bằng nhân 100. Dùng khoảng một năm lịch sử, ít nhất 60 quan sát R5 quá khứ; loại R5 mới nhất khỏi tập tự so sánh. Các cửa sổ lịch sử chồng lấn, không phải 60 quan sát độc lập. Hiện “phiên” là hàng giá đã có; lịch nghỉ/phiên thiếu chưa được đối soát với lịch sàn đầy đủ.

### Bảng năm nhãn và trạng thái rủi ro

| Điều kiện | Nhãn |
|---|---|
| Thiếu giá/lịch sử/nhóm tin hợp lệ | Chưa gán nhãn, không phải Giữ |
| −0,20 < D < +0,20 | Giữ |
| D≥0,20 nhưng R5>B hoặc R5<−B | Giữ: tránh mua đuổi hoặc bằng chứng trái chiều |
| D≥0,60, 0<R5≤B, N_eff≥3 | Mua mạnh |
| D≥0,20, −B≤R5≤B, chưa đủ điều kiện mạnh | Mua |
| D≤−0,60, R5<−B, N_eff≥3 | Bán mạnh |
| D≤−0,20, R5<−B, chưa đủ điều kiện mạnh | Bán |
| D≤−0,20, R5≥−B | Giữ: chưa xác nhận giảm theo ngưỡng |

E chỉ báo mức cực đoan. Phiên bản 2 không tự đảo Bán mạnh thành Giữ khi giá giảm sâu hơn E. Mức biến động bình thường/tăng cao/cực đoan hiện riêng; Giữ không khẳng định rủi ro thấp. Mua/Bán nghĩa là cân nhắc tăng/giảm vị thế theo quy tắc, chưa quyết định số cổ phiếu hay thực thi lệnh.

### Các con số từ đâu?

| Số | Xuất xứ và mức bằng chứng |
|---|---|
| 3 lớp, softmax, top_k=3 | Model/bài gốc, trang 1 và 4 |
| 10–15 tiêu đề, 1–2 tin mỗi mã, tối đa 5 mã, minh họa 4 vĩ mô | Bài gốc trang 4–5; giới hạn vận hành, không phải tối ưu thống kê |
| [−1,+1], giới hạn phần vốn thiếu tin, điều kiện cần C>50% | Hệ quả đại số |
| 90 ngày truy vấn | Quy ước bản triển khai, không gán cho bài gốc |
| 30 ngày, h=7, R5, tối thiểu 60, lịch sử 1 năm | Quy ước phạm vi/độ mới/đủ mẫu của bản thử |
| ±0,20, ±0,60, N_eff≥3, Jaccard 0,8, 3 ngày | Quy ước thiết kế, chưa tối ưu trên dữ liệu EGX |
| Chọn phân vị 75%/90% | Quy ước thiết kế; giá trị B/E cụ thể được tính từ lịch sử mã |
| 9 cấu hình độ nhạy | 3 mức bán rã × 3 cặp ngưỡng; không phải backtest lợi nhuận |

## 6. Chứng minh đóng góp bằng gì?

Tách ba mức bằng chứng. (1) Phần mềm: kiểm thử bảo toàn công thức, lọc đúng ca lỗi, xử lý thiếu dữ liệu; API/UI thực sự chạy. (2) Chất lượng thông tin: bộ tiêu đề có người gán nhãn để đo precision/recall của lọc và gom; hiện chưa đủ để khẳng định đã tối ưu. (3) Giá trị đầu tư: dữ liệu lưu theo thời điểm, chia tập theo thời gian, so giá-only với giá+tin, benchmark nắm giữ, trừ chi phí; hiện chưa hoàn thành mức này.

Ca thật ETEL trước sửa có bài OneFootball lọt vào nhóm quyết định. Bỏ nó trên cùng lô làm N_eff giảm 3,142558→2,270790, S 0,070730→0,071128; nhãn vẫn Giữ. Đây chứng minh lỗi đầu vào và ảnh hưởng lên phép tính, không chứng minh lợi nhuận cải thiện. Test sau sửa bảo đảm bài vẫn có trong nhật ký nhưng không được gửi vào chấm tin công ty.

155 kiểm thử đạt trong lượt 06/11/2026 là bằng chứng phần mềm trong môi trường kiểm tra. Không gọi đó là 155 bài kiểm chứng lợi nhuận. Có kiểm thử dùng dữ liệu giả/mô hình giả; phải nói rõ khi trình bày.

Đóng góp cá nhân có thể trình bày trung thực: xác định người dùng; nêu vấn đề thiếu tỷ trọng và thiếu độ phủ; yêu cầu tách Tin + Giá; thiết kế yêu cầu truy nguyên, điều chỉnh phương pháp qua phản ví dụ, xây dựng và kiểm tra nguyên mẫu. Phần code/tài liệu có AI hỗ trợ. Chỉ nhận phần việc bạn thật sự hiểu, lựa chọn, kiểm tra và có thể giải thích. Không nhận là tự huấn luyện FinBERT, phát minh các công thức cơ bản hoặc chứng minh chiến lược thắng thị trường.

## 7. Kịch bản trình bày 8–10 phút

1. Một phút: người dùng EGX đang nắm cổ phiếu cần biết gì; phạm vi tiêu đề tiếng Anh/giá ngày.
2. Hai phút: bài gốc, sơ đồ ba tầng, ví dụ p+−p−; giới hạn trung bình chung.
3. Hai phút: danh mục 50/30/20, tự tính C=0,8, S=0,30 và [0,04;0,44]; chỉ rõ đóng góp và thiếu tin.
4. Hai phút: chọn một mã, chỉ ngày giá, S/F/D, R5/B/E, dòng quy tắc tạo nhãn; mở một nhóm tin và lý do loại một bài.
5. Một phút: ca bóng đá và tin cũ, cách sửa có kiểm thử.
6. Một phút: mức bằng chứng, giới hạn và kế hoạch đánh giá ngoài mẫu.

## 8. Câu hỏi vấn đáp cần trả lời được

**Thầy: Có gì là của em?** Em mở rộng câu hỏi từ sắc thái tin chung sang phần vốn có thông tin và quy tắc Tin + Giá có truy nguyên. Em dùng mô hình có sẵn, không nhận mô hình là của mình. Minh chứng là công thức theo vốn, log lọc, phản ví dụ và kiểm thử sửa lỗi.

**Vì sao 0,2 và 0,6?** Là mức khởi đầu để phân biệt nghiêng hướng và mạnh trong bộ quy tắc; em chưa có chứng cứ tối ưu. Em công khai tham số, thử độ nhạy và cần hiệu chỉnh trên tập huấn luyện theo thời gian, giữ tập cuối để đánh giá.

**Vì sao không dùng vĩ mô vào điểm?** Cùng một tin lãi suất có thể khác tác động theo doanh nghiệp. Chưa có mô hình phơi nhiễm/kỳ vọng nên em để bối cảnh riêng, tránh tự cộng một hệ số không có căn cứ.

**Tại sao tin tốt mà không Mua?** Vì điểm D chưa đủ sau xét tuổi, hoặc giá tăng vượt B, hoặc tin và giá trái chiều. Mở trace để chỉ chính xác điều kiện, không trả lời theo cảm tính.

**Giảm giá là do tin này à?** Chưa kết luận được. Biến động sau tin chỉ là quan sát, có thị trường chung và nhiều tin khác; đo tác động cần thiết kế event study/đối chứng phù hợp.

**Có phải real time?** Bản này tính từ giá đóng cửa ngày; khung TradingView là nguồn quan sát khác. Thời điểm bấm lấy không đồng nghĩa thời điểm giá được tạo.

**Chứng minh tốt hơn chưa?** Đã chứng minh một số đặc tính phần mềm và khắc phục ca lỗi cụ thể. Chưa chứng minh tăng lợi nhuận ngoài mẫu. Hai tuyên bố này cần bằng chứng khác nhau.

**Sao một khoảng co về một điểm vẫn chưa chắc?** Khoảng chỉ xét phần vốn thiếu tin; khi đủ phủ thì nguồn bất định đó bằng 0, còn sai số FinBERT, lọc và thiếu bao phủ nội dung vẫn tồn tại.

**Có thể gọi đây là đóng góp nghiên cứu mới không?** Có thể gọi là đóng góp thiết kế/tích hợp và đánh giá của đồ án nếu chứng minh được phần việc. Chưa có rà soát đủ để khẳng định tính mới trên toàn bộ học thuật.

## 9. Nguồn để tự kiểm tra

- Bài gốc và số trang đã đối chiếu ở mục 2: https://mohamed-hendawy.medium.com/building-ai-powered-financial-sentiment-analysis-with-hugging-face-and-finbert-92134b97295a
- Model chính thức: https://huggingface.co/ProsusAI/finbert
- Mã nguồn/tài liệu tác giả FinBERT: https://github.com/ProsusAI/finBERT
- Lịch sử giá: https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html
- News API: https://eodhd.com/financial-apis/stock-market-financial-news-api

Các nguồn này giải thích mô hình/công cụ và kiến trúc; không chứng minh ngưỡng D hoặc chiến lược năm nhãn của dự án. Cơ sở của từng quy ước được phân biệt trong bảng ở mục 5.
