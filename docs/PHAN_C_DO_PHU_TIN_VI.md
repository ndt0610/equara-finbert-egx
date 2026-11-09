# Phần C: Danh mục theo vốn và độ phủ tin (bản 3.2, 04/11/2026)

Tab thứ 3 trên web ("Danh mục theo vốn") và ô **[NÂNG CẤP C]** trong notebook trả lời một câu hỏi:

> Với phần vốn mỗi mã mà tôi nhập, các tiêu đề **qua luật lọc hiện tại** của từng doanh nghiệp đang nghiêng về phía nào, và **bao nhiêu phần vốn có tiêu đề như vậy** để nói điều đó?

**Dành cho ai và phạm vi.** [Nhóm chọn] Người học, người hướng dẫn hoặc người phân tích đang xem một demo học thuật nhỏ về tin của tối đa 5 mã EGX. Họ cần thấy tiêu đề ứng viên nào đi vào phép tính S và C, và vì sao các bản ghi khác bị loại. [Sự thật] Đây chưa phải công cụ đã kiểm chứng để nhà đầu tư dùng ra quyết định: luật lọc tin và nhãn FinBERT chưa được so với nhãn của người. [Suy luận] Đây là định vị demo tạm thời. Nhóm chưa khảo sát người dùng hay xác nhận nhu cầu thị trường thật; một người phân tích thật sẽ cần nhiều ngày tin và nhiều mã hơn 5.

**Cách gọi số đếm.** Tài liệu và giao diện dùng "bản ghi ứng viên" hoặc "tiêu đề ứng viên", không gọi là "sự kiện". Ví dụ: 146 bản ghi của lượt live 16:59:38 ngày 04/11 gồm cả 9 bản lặp cùng URL. 146 bản ghi không đồng nghĩa 146 sự kiện.

Tab 1, tab 2 và các API gốc **không đổi**: cùng đầu vào thì JSON giống hệt gói V2 (có kiểm thử). Phần C chỉ thêm, không sửa công thức của bản tái dựng.

Đây không phải tư vấn đầu tư hay khuyến nghị giao dịch chứng khoán, và không dự báo giá.

Cách đọc nhãn trong tài liệu: **[Sự thật]** là điều đã đo hoặc có trong code, **[Suy luận]** là điều nhóm rút ra nhưng chưa đo, **[Nhóm chọn]** là lựa chọn thiết kế của nhóm.

## 0. Các bản và thay đổi

### Bản 3.2 (04/11/2026, tối): chữ Việt khi chạy lệnh trên Windows

Bản 3.2 chỉ đổi cách hai script in chữ ra màn hình. Không đổi thuật toán, backend, điểm, giao diện hay phép kiểm nào.

- [Sự thật, Codex chạy] Bản 3.1 trên Windows (Python 3.12.10):
  - 15/15 SHA-256 khớp;
  - pytest 146 đạt, 1 bỏ qua;
  - `tests/check_browser.py` đạt 12/12, màn 320 px và 390 px tràn 0 px, khi chạy bằng `python -X utf8 tests\check_browser.py ...`.
- [Sự thật, Codex chạy] Chạy nguyên văn `python tests\check_browser.py ...`, không có `-X utf8`, thì mọi phép kiểm đều đạt, nhưng script chết ở dòng in bảng kết quả với `UnicodeEncodeError` của bảng mã cp1252.
- [Sự thật] Nguyên nhân: khi đầu ra bị chuyển sang pipe, file hay công cụ chạy lệnh, Python trên Windows ghi bằng cp1252. Bảng mã này không có chữ Việt. Claude tái hiện được trên Linux bằng `PYTHONIOENCODING=cp1252`: cùng lỗi ở cùng dòng. Lệnh `--help` của script và lệnh `python -m scripts.replay_saved_runs docs/du_lieu_03-11` ở mục 9 cũng chết như vậy.
- [Sự thật] Sửa: `tests/check_browser.py` và `scripts/replay_saved_runs.py` tự đổi stdout và stderr sang UTF-8 ngay khi chạy. Lệnh nguyên văn giờ chạy được, không cần `-X utf8`. Thêm `-X utf8` cũng không sao.
- [Sự thật] Kết quả trong môi trường dựng gói (Linux, Python 3.13):
  - pytest 147/147;
  - với `PYTHONIOENCODING=cp1252`, `check_browser.py` đạt 12/12 và in ra đúng từng byte như khi chạy UTF-8;
  - bảng 12 dòng này giống hệt bảng Codex lưu trên Windows ở bản 3.1 (`-X utf8`), chỉ khác ký tự xuống dòng;
  - `replay_saved_runs` ra cùng kết quả ở cp1252 và UTF-8, và cùng kết quả với bản 3.
- [Sự thật] Các công cụ đo khác ở mục 10 chưa sửa. Ví dụ `capture_candidates` và `score_relevance`: lệnh `--help` của hai công cụ này chết ở cp1252. Trên Windows, khi đầu ra bị chuyển hướng, chạy chúng bằng `python -X utf8 -m scripts.<tên>`.

### Bản 3.1 (04/11/2026, tối): kiểm trình duyệt và màn 320 px

Điểm số, luật lọc (vẫn relevance-v3, cùng SHA-256 ở cuối mục bản 3), backend, `frontend/app.js` và tab 1–2 **không đổi**. Bản 3.1 chỉ sửa hai chỗ Codex gặp khi chạy bản 3 trên Windows.

- [Sự thật, Codex đo] Ở khung trình duyệt thật rộng 319 px (`innerWidth=319`), trang rộng 380 px (`scrollWidth=380`). Phần tràn duy nhất là bước thứ ba của dải "Luồng xử lý" ở chân trang (`right=380`). Kiểm 390 px của bản 3 vẫn đạt, vì ba bước nằm ngang cần khoảng 380 px.
- [Sự thật] Sửa: từ 430 px trở xuống, dải "Luồng xử lý" xếp dọc, mũi tên quay xuống. Phần CSS này nằm ở cuối `frontend/style.css`; các dòng CSS của bản tái dựng C2 không đổi. Dải này dùng chung cho mọi tab, nên trên màn hẹp tab 1–2 cũng xếp dọc dải này; số và JSON của tab 1–2 không đổi.
- [Sự thật] `tests/check_browser.py` thêm màn 320 px: ở tab 3 kiểm khi đóng và khi mở mọi mục chi tiết, ở tab 1 và tab 2 kiểm sau khi có kết quả. Phép đo dùng `document.documentElement.clientWidth` (không tính thanh cuộn dọc), vì trên Windows thanh cuộn dọc chiếm chỗ. Khi không đạt, script in tên phần tử bị tràn.
- [Sự thật] `requirements-dev.txt` thêm `playwright==1.64.1`, đúng bản Codex chạy đạt trên Windows. Gói này không kèm trình duyệt. Cách cài và lệnh chạy nằm ở đầu tệp `tests/check_browser.py`: dùng Chrome hoặc Chromium có sẵn qua `--chromium ĐƯỜNG_DẪN`, hoặc chạy `python -m playwright install chromium`.
- [Sự thật] Kết quả trong môi trường dựng gói (Linux, Python 3.13, Chromium cài sẵn, truyền qua `--chromium`): pytest 147/147; `tests/check_browser.py` đạt cả 12 dòng, gồm 390 px và 320 px. Chạy script mới này với CSS bản 3 thì script báo lỗi đúng chỗ: tràn 61 px ở 320 px, phần tử `div.flow-step right=381`.

### Bản 3 (04/11/2026, chiều): loại trùng ổn định và giao diện phễu đếm

S, C, khoảng giới hạn, công thức và tab 1–2 **không đổi**. Bản 3 sửa bước loại trùng của tab 3 và đổi cách tab 3 trình bày số đếm.

**Lỗi loại trùng của bản 2 (Codex phát hiện, Claude xác nhận bằng code và phép thử nhỏ).**
- [Sự thật] Bản 2 ghi khóa vào tập "đã thấy" trước khi xét tuổi tin. Một bản quá hạn đến trước che bản còn hạn cùng khóa, nên kết quả phụ thuộc thứ tự bản ghi đến.
- [Sự thật] Bản 2 ghi tiêu đề rỗng là "trùng".
- [Sự thật] Ảnh hưởng trên dữ liệu live đã có: 0. Cả 286 bản ghi của hai lượt live ngày 04/11 (146 + 140) đều có URL và ngày, không bản nào quá hạn.

**Chính sách loại trùng của bản 3** (chi tiết ở mục 3, bước 1–2):
- Khóa là URL đã chuẩn hóa; chỉ khi không có URL mới dùng tiêu đề đã chuẩn hóa. Hai URL khác nhau không bao giờ bị gộp.
- Bản quá hạn và bản thiếu tiêu đề không vào nhóm trùng.
- Mỗi nhóm giữ bản có ngày mới nhất; bản không ngày chỉ được chọn khi cả nhóm không có ngày. Kết quả không phụ thuộc thứ tự bản ghi.
- Không gộp theo sự kiện.
- [Nhóm chọn, pi đồng ý 04/11] Thiếu tiêu đề được xét trước trùng, để bản rỗng không che bản có tiêu đề cùng URL. Tuổi tin vẫn xét đầu tiên.

**Phạm vi.** [Sự thật] Chỉ tab 3 và API v2 (`screen`, `screen_macro` trong `backend/upgrades/relevance.py`, gọi từ `coverage_service.py` và hai script đo). Tab 1–2 và ô "cách bài báo" vẫn dùng `backend.providers.news.deduplicate` của bản tái dựng, không sửa; kiểm thử trong `tests/test_dedup_v3.py` khóa đúng hành vi cũ đó.

**Đã kiểm.**
- [Sự thật] 30 kiểm thử hồi quy mới. Chúng bao gồm: bản cũ đến trước bản mới; mọi hoán vị của {cũ, mới, không ngày}; tiêu đề rỗng; cùng tiêu đề khác URL; ngày bằng nhau thì giữ bậc truy vấn thấp hơn; 200 lô ngẫu nhiên xáo thứ tự; tin vĩ mô; khóa hành vi C2.
- [Sự thật] Khi cài lại logic loại trùng của bản 2 vào một bản sao, 19 trong 30 kiểm thử báo lỗi, nghĩa là kiểm thử bắt được đúng lỗi cũ.
- [Sự thật] Chạy lại toàn bộ bản ghi của hai JSON live Codex lưu ngày 04/11 qua luật bản 3: lượt A/B 16:59:38 (146 bản ghi, cộng lượt POST kiểm tra) và lượt một danh mục (tin lấy lúc 16:47:43, gửi lúc 16:49:39; 140 bản ghi). Kết quả: 0 bản ghi đổi quyết định hay lý do, và kết quả giữ nguyên khi xáo thứ tự. JSON không lưu phần mô tả, nên lý do "tên chỉ có trong mô tả" và cột bộ lọc cũ không kiểm lại được; lượt này có 0 bản ghi mang lý do đó.

**Giao diện tab 3 bản 3** (mục 8):
- phễu đếm từng mã, chỉ số đếm, không có tỷ lệ phần trăm;
- danh sách bản ghi bị loại nhóm theo lý do đầu tiên, kèm dấu hiệu phụ;
- danh sách "qua luật hiện tại nhưng ngoài giới hạn 15";
- khối "Khớp tên theo bộ lọc Tab 1–2" chuyển xuống phần tham khảo;
- câu "Dành cho ai" ở đầu tab;
- bỏ các chữ "tin riêng", "có giữ", "cũng loại".

**Mốc khóa luật lọc relevance-v3:** 2026-11-04 15:10 UTC (22:10 giờ Việt Nam). SHA-256 của `backend/upgrades/relevance.py`: `2aa110379b79e954d71cc7e79cec7fba1bb1c81e1c01310cd86c23196fff5d3b`. Bản 3 chỉ đổi bước loại trùng và thêm lý do "thiếu tiêu đề". Các luật tên, alias, thể thao, trang dữ liệu và tin vĩ mô giữ nguyên như relevance-v2.

### Bản 2 so với bản 1 (03/11)

Công thức không đổi. Bản 2 sửa 4 lỗi ở phần lõi, mỗi lỗi có bằng chứng trên dữ liệu thật:

| # | Lỗi của bản 1 | Bằng chứng | Bản 2 |
|---|---|---|---|
| 1 | Độ phủ đo "truy vấn hẹp có trúng không", chưa đo "mã có tin không" | [Sự thật] FWRY: truy vấn hẹp ra 1 ứng viên, giữ 0, cả 03/11 lẫn 04/11; truy vấn rộng thêm 11 ứng viên, luật bản 1 giữ 8 (Codex chạy trên Windows 04/11, 12:32). ETEL: hẹp giữ 2 tin ngày 03/11 rồi 0 tin ngày 04/11; rộng thêm 43, giữ 22. MarketScreener có tin kết quả nửa năm của Fawry ngày 11/08/2026, trong cửa sổ 90 ngày | Truy vấn rộng (bậc 2) bật mặc định khi mã có dưới 10 tin phù hợp (mục 4) |
| 2 | Tin của ngân hàng mẹ ADIB ở UAE được tính cho ADIB Egypt | [Sự thật] "ADIB", "Abu Dhabi Islamic Bank" cũng là tên ngân hàng mẹ niêm yết ở Abu Dhabi; tên dùng để truy vấn bắt đầu bằng đúng tên đó | Tên ADIB phải đi kèm chữ chỉ Ai Cập (mục 3, bước 3b) |
| 3 | Ô vĩ mô ghi "bối cảnh kinh tế" nhưng toàn tin chính trị | [Sự thật] Cả lượt 03/11 và 04/11, 2/2 tin vĩ mô là tin tự do báo chí, M = −0,901 | Chỉ giữ tin có từ về kinh tế hay thị trường; thiếu thì gọi truy vấn tin kinh tế của bản tái dựng (mục 5) |
| 4 | Mã mang nhãn Neutral mà điểm dương, không có giải thích | [Sự thật] 03/11: cả 4 mã có tin đều Neutral, điểm +0,383, +0,358, +0,018, +0,413; thanh "vốn theo nhãn" ghi 80% Neutral trong khi S = +0,293 | Hiện số tin theo nhãn của từng mã và một câu giải thích kèm điểm (mục 2) |

Thêm: trang dữ liệu dạng "… Estimates – EGX:FWRY - TradingView" bị loại (tiêu đề thật Codex gặp ngày 04/11), và chữ "Chưa có tin riêng" đổi thành "Không tìm thấy tin riêng", vì truy vấn không thấy tin chưa có nghĩa là công ty không có tin. Bản 3 đổi tiếp thành "Không có tiêu đề qua luật hiện tại".

**Mốc khóa luật lọc relevance-v2:** 2026-11-04 05:37 UTC (12:37 giờ Việt Nam). SHA-256 của `backend/upgrades/relevance.py`: `485637eb9917263ec7ce9ae1cce3ec020276707ceef8443b6898fbe5887651f9`. Muốn đo luật này bằng phiếu gán nhãn, dùng tin thu **sau** mốc này. Dữ liệu ngày 04/11 của Codex đã được dùng để viết luật trang TradingView, nên không còn là phép kiểm độc lập.

## 1. Các từ dùng trong tab, mỗi từ một ví dụ số

Ví dụ chung: danh mục A 50%, B 30%, C 20%. A có tiêu đề qua luật hiện tại, điểm mã +0,6. B cũng có, điểm mã −0,2. C không có tiêu đề nào qua luật hiện tại.

| Từ | Nghĩa | Ví dụ |
|---|---|---|
| Phần vốn w_i | Số bạn nhập, tự chia lại cho tổng bằng 100% | Nhập 5, 3, 2 cũng thành 50%, 30%, 20% |
| Tiêu đề qua luật hiện tại | Tiêu đề nhắc đúng tên công ty và qua luật lọc ở mục 3. Luật là tự động, chưa có người kiểm | "CIB posts record profit" qua luật của COMI |
| Bản ghi ứng viên | Một tiêu đề do nguồn tin trả về cho một mã, trước khi lọc. Một tin đăng ở hai báo, hay một URL ở hai truy vấn, là hai bản ghi | Lượt 16:59:38 ngày 04/11: 146 bản ghi ứng viên cho 5 mã, không phải 146 sự kiện |
| Điểm một tin | P(tích cực) − P(tiêu cực) của tiêu đề đó. Đây là `sentiment_score` của chính FinBERT: README của ProsusAI/finBERT ghi "probability of positive - probability of negative", và hàm `predict` trong `finbert/finbert.py` tính đúng như vậy (dòng 625 trên nhánh master ngày 04/11/2026) | P+ 0,8, P− 0,1 thì điểm +0,7 |
| Điểm mã s_i | Trung bình điểm các tiêu đề được chấm của mã. Bằng trung bình P+ trừ trung bình P−, đúng công thức điểm của bản tái dựng, chỉ khác là tính cho từng mã | 2 tin: điểm +0,7 và +0,5, thì s = +0,6 |
| Độ phủ tin C | Tổng phần vốn của các mã có ít nhất 1 tiêu đề qua luật hiện tại | A và B có tin, nên C = 50% + 30% = 80% |
| Tỷ trọng tính lại r_i | Phần vốn chia cho độ phủ | A: 50/80 = 62,5%; B: 30/80 = 37,5% |
| Đóng góp c_i | r_i × s_i, cộng các đóng góp ra đúng S | A: 0,625 × 0,6 = +0,375; B: 0,375 × (−0,2) = −0,075 |
| Điểm tin doanh nghiệp S | Tổng các đóng góp, chỉ trên phần vốn có tin | S = 0,375 − 0,075 = **+0,30** |
| Khoảng giới hạn | Điểm theo vốn của cả danh mục nằm ở đâu, nếu phần vốn không tìm thấy tin mang điểm bất kỳ từ −1 đến +1 | 0,8 × 0,30 ± 0,2 = **[+0,04; +0,44]** |
| Hướng | Chỉ nói "dương" hoặc "âm" khi cả khoảng nằm về một phía của 0 | [+0,04; +0,44] nằm trên 0, nên hướng là dương |
| Vốn theo nhãn | Bao nhiêu phần vốn thuộc mã có nhãn Bullish, Bearish, Neutral, hay không tìm thấy tin | Ví dụ: Bullish 50%, Bearish 30%, không tìm thấy tin 20% |
| Điểm vĩ mô M | Điểm của tối đa 4 tin kinh tế và thị trường Ai Cập, hiện riêng, **không cộng vào S** | M = −0,90 không làm S đổi |

[Nhóm chọn] Phần của nhóm là: lọc đúng công ty, độ phủ theo vốn, tỷ trọng tính lại, khoảng giới hạn và tách vĩ mô. Điểm từng tin là của FinBERT, không phải của nhóm.

**Vì sao khoảng giới hạn có công thức này.** [Sự thật] Điểm theo vốn của cả danh mục là C·S + (1 − C)·u, với u là điểm chưa biết của phần vốn không tìm thấy tin. Nếu u nằm trong [−1, +1] thì điểm cả danh mục nằm trong [C·S − (1 − C), C·S + (1 − C)]. Đây là phép tính, không phải ước lượng.

**Vì sao cần độ phủ trên 50% mới có hướng.** [Sự thật] Cả khoảng nằm trên 0 khi C·S > 1 − C. Vì S không vượt quá 1, điều này đòi hỏi C > 1 − C, tức C > 50%. Ví dụ thật ngày 04/11 (Codex, Windows, bản 1): danh mục 50/30/20 chỉ COMI có tin, C = 50%, S = +0,636, khoảng 0,5 × 0,636 ± 0,5 = [−0,18; +0,82], không có hướng.

Ví dụ thứ hai, độ phủ thấp: chỉ A (40%) có tin, điểm +0,6. Khoảng là 0,4 × 0,6 ± 0,6 = [−0,36; +0,84]. Khoảng chứa 0, nên tab ghi "chưa xác định hướng" dù S = +0,6. [Nhóm chọn] Tab vẫn hiện S và các đóng góp, chỉ không nói hướng.

**Khoảng giới hạn KHÔNG phải khoảng tin cậy thống kê.** [Sự thật] Nó coi điểm các mã đã có tin là đúng, và không giả định gì về mã không tìm thấy tin. Nó không nói FinBERT chấm đúng hay sai.

## 2. Nhãn Neutral có thể đi cùng điểm dương

[Sự thật] Nhãn của mỗi tin là lớp có xác suất lớn nhất (đúng `prediction` của FinBERT). Nhãn của mỗi mã dùng đúng quy tắc của bản tái dựng: Bullish khi trung bình P(tích cực) lớn nhất, Bearish khi trung bình P(tiêu cực) lớn nhất, còn lại Neutral. Điểm thì là trung bình P(tích cực) trừ trung bình P(tiêu cực).

Ví dụ thật ngày 03/11, COMI có 6 tiêu đề qua luật: trung bình P+ = 0,398, P− = 0,015, P(trung tính) = 0,587. Điểm = 0,398 − 0,015 = +0,383, nhưng P(trung tính) lớn nhất, nên nhãn là Neutral. Đếm theo từng tin: 2 tích cực, 4 trung tính, 0 tiêu cực.

Hai con số trả lời hai câu khác nhau: nhãn trả lời "trung bình thì lớp nào khả dĩ nhất", điểm trả lời "tin nghiêng về phía nào". S tính từ điểm, không tính từ nhãn.

Bản 2 hiện thêm:
- số tin theo nhãn của từng mã (`label_counts`);
- một câu giải thích dưới thanh "vốn theo nhãn" khi có mã mang nhãn Neutral mà điểm khác 0, nêu đúng điểm từng mã (`capital_by_label_note`). Ví dụ 03/11: "COMI +0.383, ETEL +0.358, ADIB +0.018, EFIH +0.413".

[Nhóm chọn] Giữ quy tắc nhãn để khớp bản tái dựng. Biến `COVERAGE_NEUTRAL_BAND` (mặc định tắt) đổi sang nhãn theo độ lớn của điểm, chỉ để thử, vì ngưỡng của nó chưa được đo trên tin EGX.

## 3. Luật lọc tiêu đề theo doanh nghiệp relevance-v3

Chỉ tab 3 dùng luật này. Tab 1 và tab 2 vẫn dùng bộ lọc cũ (tên hoặc mã xuất hiện ở bất kỳ đâu trong tiêu đề hay mô tả, so chuỗi con), để còn đối chứng.

Mỗi bản ghi ứng viên được xét theo thứ tự dưới đây, ở cả truy vấn hẹp lẫn truy vấn rộng. Bản ghi bị loại ở bước đầu tiên không đạt và chỉ ghi lý do đó; số đếm theo lý do cũng theo lý do đầu tiên. Đây là luật tự động, chưa có người kiểm, và có thể loại nhầm tin có nói về công ty nhưng tiêu đề không nêu tên công ty.

[Sự thật] Bản 3 thêm **dấu hiệu phụ** (`pattern_flags`): tiêu đề có khớp mẫu trang dữ liệu (bước 5) hay từ khóa thể thao (bước 4) không, tính độc lập với thứ tự luật. Dấu hiệu phụ chỉ để xem: nó không đổi quyết định lọc và không đổi số đếm. Ví dụ thật ngày 04/11: "CBKD Stock Price and Chart — LSIN:CBKD - TradingView" là trang giá GDR London của CIB. Bản ghi này ghi lý do "tiêu đề không nhắc tên công ty" vì luật tên (bước 3) xét trước luật trang dữ liệu (bước 5), và mang dấu hiệu phụ "cũng khớp mẫu trang dữ liệu".

| Bước | Loại khi | Ví dụ |
|---|---|---|
| 1 | Cũ hơn 90 ngày. Tin không có ngày, hoặc ngày không đọc được, vẫn được xét tiếp và ghi "không rõ ngày", giống bản tái dựng | Tin đăng 120 ngày trước |
| 1b | (Mới ở bản 3) Thiếu tiêu đề: tiêu đề rỗng sau khi bỏ dấu câu, nên FinBERT không có chữ để chấm | Bản ghi có URL nhưng tiêu đề trống |
| 2 | (Bản 3 viết lại) Bản lặp trong cùng lượt. Khóa = URL đã chuẩn hóa (chữ thường ở scheme và host, bỏ `?…`, `#…` và dấu "/" cuối); chỉ khi không có URL mới dùng tiêu đề đã chuẩn hóa (chữ thường, bỏ dấu câu). Hai URL khác nhau không bao giờ bị gộp, kể cả khi cùng tiêu đề. Bản ghi ở bước 1 hoặc 1b không vào nhóm trùng. Mỗi nhóm giữ đúng một bản: bản có ngày mới nhất; bản không ngày chỉ được chọn khi cả nhóm không có ngày; hòa thì bậc truy vấn thấp hơn, rồi tiêu đề, rồi URL, rồi các trường còn lại. Kết quả không phụ thuộc thứ tự bản ghi | Thật, lượt 16:59:38 ngày 04/11: 9 bản lặp, cả 9 là bản bậc 2 của một URL đã có ở bậc 1, cùng ngày đăng (3 lặp tiêu đề đã chấm, 5 lặp bản ghi không nhắc tên, 1 lặp trang dữ liệu) |
| 3 | Tên công ty hoặc alias không có trong **tiêu đề** (so nguyên từ, không phân biệt hoa thường). Nếu tên chỉ có trong mô tả thì ghi lý do riêng | "Egypt prepares for coming debt repayments": bộ lọc cũ giữ vì "coming" chứa "comi"; luật mới loại |
| 3b | (Mới ở bản 2) Tên chỉ khớp "ADIB" hoặc "Abu Dhabi Islamic Bank" mà tiêu đề không có egypt, egyptian, misr, egx, cairo hay egp | "ADIB posts record nine-month profit" bị loại; "ADIB-Egypt posts EGP 1.2bn profit" và "Abu Dhabi Islamic Bank Egypt raises capital" được giữ |
| 4 | Tiêu đề có từ khóa thể thao (football, league, cup, club, FC, SC, stadium, coach, round of 32, relegation, quarter-final, …). Cố ý không có "match" và "goal" | "Telecom Egypt SC held to a draw …": Telecom Egypt còn là tên câu lạc bộ bóng đá |
| 5 | Tiêu đề là trang dữ liệu chứ không phải tin (quote, chart, historical data, seasonal returns, …). Bản 2 thêm dạng TradingView: tên trang (Estimates, Forecast, Financials, Statistics, Profile, Overview, Technicals, Dividends, Key stats) đứng **ngay trước** "– SÀN:MÃ" | Thật ngày 03/11: "… (CBKD) Equity Price and Quote - London Stock Exchange". Thật ngày 04/11: "Fawry For Banking Technology And Electronic Payment Estimates – EGX:FWRY - TradingView". Vẫn giữ: "Fawry beats profit estimates - Reuters", "Fawry (EGX:FWRY) earnings beat estimates" |

[Nhóm chọn] Lý do của bước 3: FinBERT chỉ chấm tiêu đề, nên tiêu đề phải nói về công ty. Tên và alias của 5 mã:

| Mã | Tên dùng để tìm | Alias dùng để lọc |
|---|---|---|
| COMI | Commercial International Bank | COMI, CIB, Commercial International Bank |
| ETEL | Telecom Egypt | ETEL, Telecom Egypt |
| FWRY | Fawry | FWRY, Fawry |
| ADIB | Abu Dhabi Islamic Bank Egypt | ADIB, Abu Dhabi Islamic Bank (cần chữ chỉ Ai Cập), Abu Dhabi Islamic Bank Egypt |
| EFIH | E-finance for Digital and Financial Investments | EFIH, E-finance, E-finance for Digital and Financial Investments |

**Vì sao bước 3b chỉ áp cho ADIB.** [Sự thật] Tên dùng để truy vấn ADIB ("Abu Dhabi Islamic Bank Egypt") bắt đầu bằng đúng tên đầy đủ của ngân hàng mẹ, một tổ chức có nhiều tin của chính nó, nên truy vấn có thể kéo tin của ngân hàng mẹ về. Tên truy vấn của COMI ("Commercial International Bank") thì không như vậy. Nếu bắt "CIB" phải đi kèm chữ Ai Cập, ta sẽ mất tin thật ngày 03/11 "CIB Commits Up to USD 38.2M to MNT-Halan’s Proposed Offering", là tin đúng của COMI mà không có chữ nào chỉ Ai Cập.

**Phản ví dụ còn sót của bản 2.** Cần đo bằng phiếu gán nhãn trước khi sửa; không chỉnh theo cảm giác. Tiêu đề có dấu * là nhóm tự dựng theo sự kiện thật để thử luật, không phải tin thu được.

- [Sự thật] Giữ nhầm khi tiêu đề có chữ Ai Cập nhưng nói về ngân hàng mẹ: "ADIB, Egypt's sovereign fund sign MoU"*.
- [Sự thật] "E-finance" cũng là một danh từ chung: "Nigeria's e-finance push"* vẫn được tính cho EFIH. Chưa gặp ca thật; truy vấn dùng tên pháp lý đầy đủ. Tin thật ngày 03/11 của EFIH ("E-finance approves EGP 410.6 million dividend …") có chữ EGP nên vẫn qua nếu sau này siết.
- [Sự thật] Trang dữ liệu dạng khác chưa gặp vẫn lọt, ví dụ "… Stock Price & News - Google Finance"*.
- [Sự thật] Nhiều tiêu đề cùng một sự kiện vẫn được tính nhiều lần. Ngày 03/11, 4 trong 6 tin COMI là cùng đợt MNT-Halan. Cùng một tin đăng ở hai báo có hai URL nên cũng tính hai lần. Tab liệt kê mọi tiêu đề để người xem tự thấy.
- [Sự thật] Bản ghi ghi ngày "trong tương lai" (nguồn ghi sai ngày) được ưu tiên trong nhóm trùng vì là bản mới nhất. Hai bản cùng URL mà khác tiêu đề: chỉ tiêu đề của bản được chọn đi qua các luật sau.
- [Sự thật] Ví dụ lọt luật thấy khi dựng lại lượt 16:59:38: "Pre-match Haras El-Hodood vs Telecom Egypt, Egypt Second Division Round 3 - BeSoccer Livescore" là tin bóng đá nhưng qua luật của ETEL vì không có từ nào trong danh sách thể thao. Bản ghi này nằm ngoài giới hạn 15 nên không được chấm. Chưa sửa: cần đo bằng phiếu gán nhãn trước.
- [Suy luận] Danh sách từ khóa thể thao và trang dữ liệu chỉ gồm những mẫu đã gặp. Chưa có số đo precision hay recall.

## 4. Lấy tin cho mỗi mã

1. [Sự thật] Có khóa EODHD thì gọi EODHD trước (tối đa 20 ứng viên), rồi áp luật lọc.
2. [Sự thật] Gọi Google News RSS với truy vấn hẹp của bản tái dựng, `"<tên công ty>" Egypt EGX stock when:90d`, khi EODHD không có tin phù hợp nào (đúng như bản tái dựng) **hoặc** khi tin phù hợp còn dưới 10.
3. [Sự thật] Nếu vẫn dưới 10 tin phù hợp thì gọi truy vấn rộng (bậc 2) `"<tên công ty>" when:90d`. Tin từ truy vấn rộng qua đúng luật lọc ở mục 3 và ghi "bậc 2" trong bảng.
4. [Nhóm chọn] Chấm tối đa 15 tiêu đề qua luật mới nhất theo ngày đăng mỗi mã (ngày không rõ xếp sau), như yêu cầu một mã của bài báo. Bản ghi qua luật còn lại ghi "qua luật hiện tại nhưng ngoài giới hạn 15": không chấm, không vào S. 15 là cấu hình demo, chưa được chứng minh là tối ưu.
5. [Sự thật] Danh sách tin được giữ 10 phút; xác suất FinBERT của một tiêu đề được giữ 24 giờ (cùng bộ nhớ đệm của phần nâng cấp cũ). Mỗi tiêu đề khác nhau chỉ chấm một lần.

**Căn cứ của truy vấn rộng và ngưỡng 10.**

- [Sự thật] Bằng chứng ở mục 0, dòng 1: truy vấn hẹp bỏ sót tin có thật của FWRY và ETEL, và kết quả của nó đổi theo ngày (ETEL 2 tin rồi 0 tin).
- [Nhóm chọn] 10 là đầu dưới của "top 10–15" trong bài báo.
- [Sự thật] Trên hai ngày đã thấy, số tin hẹp giữ được của 5 mã COMI/ETEL/FWRY/ADIB/EFIH là 6/2/0/1/1 (03/11) và 3/0/0/1/1 (04/11). Vì vậy mọi ngưỡng từ 7 đến 15 đều cho kết quả y hệt: cả 5 mã đều gọi truy vấn rộng. Con số 10 không quyết định kết quả trên dữ liệu đã thấy; điều quyết định là có gọi truy vấn rộng hay không.
- [Sự thật] Phạm vi: chỉ tab 3 và API v2. Mỗi mã thêm tối đa 1 lượt gọi Google. `COVERAGE_TIER2_BELOW=0` tắt truy vấn rộng để chạy lại cách lấy tin của bản 1.
- [Suy luận] Chưa đo: bao nhiêu phần trăm tin bậc 2 đúng là tin của công ty; độ phủ dao động theo ngày bao nhiêu; nguồn tự động (ad-hoc-news.de, Wansom AI) chiếm bao nhiêu.

**Ô "cách bài báo" trong tab 3.** [Sự thật] Ô này dựng lại điểm của tab 2 từ chính lượt lấy tin đó: 2 tin mới nhất mỗi mã theo bộ lọc cũ, cộng 4 tin vĩ mô (đúng tin của tab 2, không qua luật tin kinh tế ở mục 5), gộp tối đa 14 tiêu đề. Kiểm thử xác nhận ô này cho đúng số của tab 2 với cùng đầu vào. Ô này dùng để so: cùng một lượt tin, cách gộp chung và cách tách theo vốn nói gì.

## 5. Ô tin kinh tế và thị trường Ai Cập (điểm M)

1. [Sự thật] Lấy tin vĩ mô như bản tái dựng (EODHD, rồi BBC Middle East lọc theo chữ Ai Cập, rồi Google), 4 tin mới nhất.
2. [Nhóm chọn] Chỉ giữ tin có ít nhất một từ về kinh tế hay thị trường trong tiêu đề: economy, inflation, interest rate, central bank, pound, currency, IMF, World Bank, GDP, growth, budget, deficit, debt, bonds, investment, exports, trade, tourism, Suez Canal, oil, natural gas, LNG, fuel, subsidies, prices, stocks, shares, EGX, markets, banks, loans, credit rating, Moody's, Fitch, S&P, PMI, reserves, taxes, revenue, …. Cố ý không tính "aid", "deal" và "gas" đứng một mình.
3. [Sự thật] Nếu giữ được ít hơn 4 tin và lượt lấy tin vĩ mô chưa gọi Google, gọi thêm truy vấn Google tin kinh tế có sẵn của bản tái dựng (`Egypt economy OR Egyptian economy OR EGX when:90d`), rồi lọc lại.
4. [Sự thật] Không còn tin nào thì ô ghi "Không tìm thấy tin kinh tế hay thị trường Ai Cập" và không có M. Tin bị loại được liệt kê kèm lý do.

[Sự thật] Chạy lại lượt 03/11: cả hai tin ("Democratic senator blames Egypt press crackdown on US military aid decision", "Egypt court fines journalist Lina Attalah and orders news site's closure") bị loại với lý do "tiêu đề không nói về kinh tế hay thị trường". File đã lưu không có kết quả truy vấn tin kinh tế, nên M của lượt này là "—".

**Phản ví dụ còn sót.** (* = tiêu đề nhóm tự dựng theo sự kiện thật)
- Giữ nhầm tin chính trị có một từ kinh tế: "Egypt jails journalist over report on inflation"*, "Egypt's Sisi meets IMF chief to discuss Gaza aid"*.
- Loại nhầm tin kinh tế không có từ trong danh sách: "Egypt, UAE sign $35 billion Ras El-Hekma deal"*, "EU announces 7.4 billion euro package for Egypt"*.

## 6. Cấu hình

Đặt bằng biến môi trường trước khi chạy uvicorn. Mọi tùy chọn thử nghiệm mặc định **tắt**; khi bật, tab ghi rõ tùy chọn nào đang bật.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `COVERAGE_LOOKBACK_DAYS` | 90 | Cửa sổ tin (1–90 ngày), giữ theo bản tái dựng |
| `COVERAGE_MAX_PER_HOLDING` | 15 | Số tin tối đa được chấm mỗi mã |
| `COVERAGE_MACRO_LIMIT` | 4 | Số tin kinh tế cho điểm M |
| `COVERAGE_TIER2_BELOW` | 10 | Gọi truy vấn rộng khi một mã có dưới số tin phù hợp này. `0`, `off`, `false`, `no` hoặc `none` để tắt (như bản 1) |
| `COVERAGE_MIN_FOR_SCORE` | tắt | Ví dụ `0.65` (mốc mượn của MSCI): dưới mốc thì không hiện S và khoảng giới hạn, vẫn hiện đóng góp |
| `COVERAGE_HALF_LIFE_MICRO_HOURS`, `COVERAGE_HALF_LIFE_MACRO_HOURS` | tắt | Tin càng cũ càng nhẹ |
| `COVERAGE_PRIOR_STRENGTH` | 0 | κ: co điểm về 0 khi ít tin |
| `COVERAGE_NEUTRAL_BAND` | tắt | Nhãn theo độ lớn của điểm thay vì xác suất lớn nhất |
| `COVERAGE_CONFIDENCE_WEIGHTING` | tắt | Trọng số theo độ rõ \|P+ − P−\| |

[Nhóm chọn] Các mốc 90 ngày, 15 tiêu đề và 10 tiêu đề, cùng danh sách từ khóa thể thao và mẫu trang dữ liệu, là cấu hình demo, chưa được chứng minh là tối ưu. [Sự thật] Khi mọi tùy chọn thử nghiệm tắt, điểm mã đúng bằng trung bình phẳng của bản tái dựng (có kiểm thử).

## 7. API

```powershell
# POST
$body = '{"positions":[{"symbol":"COMI","weight":50},{"symbol":"ETEL","weight":30},{"symbol":"FWRY","weight":20}]}'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v2/sentiment/portfolio/coverage' -Method Post -ContentType 'application/json' -Body $body
# GET, cùng JSON với POST
Invoke-RestMethod 'http://127.0.0.1:8000/api/v2/sentiment/portfolio/coverage?positions=COMI:50,ETEL:30,FWRY:20'
# Cấu hình đang dùng
Invoke-RestMethod 'http://127.0.0.1:8000/api/v2/coverage/config'
```

- Đầu vào: 1–5 mã EGX khác nhau, phần vốn ≥ 0, tổng > 0. Sai thì HTTP 422 kèm thông báo tiếng Việt.
- Khối `portfolio`: `coverage`, `uncovered_weight`, `score`, `sum_contributions`, `bound` {low, high}, `direction`, `direction_text`, `capital_by_label`, `capital_by_label_note`.
- Mỗi mã trong `holdings`: phần vốn, có tin hay không, số tin, điểm, nhãn, `label_counts`, ba xác suất trung bình, đóng góp, các tiêu đề đã chấm (điểm, phần của điểm mã, đóng góp, bậc truy vấn, alias khớp), bản ghi bị loại kèm `reason_code`, `reason` và (bản 3) `pattern_flags`, bản ghi qua luật nhưng ngoài giới hạn (`not_scored`), số ứng viên, số tin bộ lọc cũ sẽ giữ, ngày tin cũ nhất và mới nhất, `tier2_called` và `providers` (từng truy vấn đã gọi cho mã đó).
- Khối `macro`: `n`, `score`, `label`, `label_counts`, `headlines`, `rejected` (kèm lý do), `keep_rule`. Là `null` khi không có tin vĩ mô nào, kể cả tin bị loại.
- Các khối khác: `article_method` (ô cách bài báo), `providers` (từng lượt gọi nguồn tin), `notes` (giới hạn), `disclaimer`, `data_freshness`, `cache`, `relevance_rules` ("relevance-v3"), `method_version` ("coverage-v2").

## 8. Giao diện và notebook

- **Web, tab 3 (giao diện C3 bản 3, 04/11/2026; công thức, S, C và khoảng giữ nguyên).** Đầu tab có câu "Dành cho ai" (người học, người hướng dẫn, người phân tích xem demo nhỏ tối đa 5 mã EGX; chưa phải công cụ đã kiểm chứng cho nhà đầu tư). Nhập mã và phần vốn (mặc định COMI 50, ETEL 30, FWRY 20), bấm "Xem độ phủ tin". Từ trên xuống:
  - **Tóm tắt "Tin về các mã trong danh mục":**
    - một dòng phạm vi "Demo học thuật cho tối đa 5 mã EGX";
    - S (2 chữ số, dấu phẩy thập phân): điểm sắc thái tiêu đề trên phần vốn có tin, không phải dự báo giá;
    - câu "nghiêng tích cực/tiêu cực theo điểm tiêu đề" theo dấu của S, không có ngưỡng;
    - ba ô lấy từ JSON: phần vốn có tin (k/n mã); số tiêu đề được chấm kèm câu đếm "Từ N bản ghi ứng viên: X bị luật tự động loại, Y qua luật hiện tại, trong đó Z ngoài giới hạn 15 tiêu đề mỗi mã nên không chấm"; LIVE/FIXTURE kèm giờ lấy tin hoặc giờ của tin dùng lại.
    - Ngay dưới S là lưu ý: điểm tính theo từng tiêu đề, chỉ bỏ bản lặp cùng URL, nhiều tiêu đề cùng một sự kiện vẫn được tính nhiều lần. Kèm câu: "qua luật" không có nghĩa là tiêu đề chắc chắn nói về công ty, "bị loại" không có nghĩa là chắc chắn không liên quan.
  - **Biểu đồ chính "Mã nào kéo điểm lên, mã nào kéo xuống":**
    - Mỗi mã một thanh lệch hai phía từ vạch 0. Độ dài là đóng góp c_i = r_i × s_i (r_i = w_i / C), lấy nguyên từ JSON. Dòng chữ ghi mã, vốn ban đầu, số tiêu đề, điểm mã và đóng góp; dòng cuối "Cộng các thanh = S".
    - Mã không có tiêu đề qua luật là dòng xám "chưa có điểm · không tính vào S": không có thanh, và không phải điểm 0.
    - Bấm vào một dòng để mở chi tiết. Đầu tiên là **phễu đếm**, chỉ có số đếm, không có tỷ lệ phần trăm, mọi số lấy từ JSON: "N bản ghi ứng viên = X bị luật tự động loại + Y qua luật hiện tại" và "Y qua luật hiện tại = K được chấm bằng FinBERT + Z qua luật nhưng ngoài giới hạn 15". Phễu không cộng khớp thì trang báo lỗi thay vì che đi.
    - Tiếp theo: truy vấn đã gọi, bảng tiêu đề được chấm (nguồn và bậc truy vấn, cột đóng góp của từng tiêu đề), và hai mục thu gọn.
    - Mục "Qua luật hiện tại nhưng ngoài giới hạn 15": ghi "chỉ chấm 15 tiêu đề mới nhất theo ngày đăng; ngày không rõ xếp sau".
    - Mục "Bị luật tự động loại (n)": nhóm theo lý do đầu tiên, theo thứ tự luật, mỗi nhóm có số đếm; mỗi bản ghi có ngày, nguồn, bậc truy vấn, từ đã khớp (thể thao, trang dữ liệu) và dấu hiệu phụ nếu có. Mục này ghi rõ: loại tự động, chưa có người kiểm; có thể loại nhầm tin có nói về công ty nhưng tiêu đề không nêu tên công ty; mỗi bản ghi chỉ ghi lý do đầu tiên khớp; dấu hiệu phụ không đổi quyết định hay số đếm.
  - **"Cả danh mục có thể nằm ở đâu":**
    - Dải khoảng giới hạn trên thang riêng −1 đến +1, chỉ hiện khi còn mã chưa có tin. Trang ghi rõ đây là biên do vốn thiếu tin, không phải khoảng tin cậy; S không vẽ trên thang này.
    - Khi mọi mã đều có tin, dải được thay bằng một câu: khoảng co về S, nhưng điều đó không chứng minh tin đã lọc đúng, không loại tin trùng sự kiện, không hiệu chỉnh mô hình.
  - **Tham khảo và chi tiết (thu gọn):**
    - tin kinh tế Ai Cập (ghi "không cộng vào S") kèm tin bị loại;
    - cách bài báo;
    - nhãn FinBERT của từng mã và thanh vốn theo nhãn (đã rời phần đầu vì nhãn có thể khác dấu của S);
    - **"Khớp tên theo bộ lọc Tab 1–2"** (mới ở bản 3): bộ lọc này chỉ kiểm tên hoặc alias có nằm trong tiêu đề + mô tả hay không (so chuỗi con), không phải quyết định cuối của luồng Tab 1–2. Khối có bảng theo mã (qua luật · khớp tên, bị loại · khớp tên), danh sách bản ghi bị luật hiện tại loại nhưng khớp tên, và câu "N là số bản ghi trong lượt này, không phải số sự kiện". Lượt 16:59:38 ngày 04/11: 11 bản ghi (COMI 4, ETEL 2, FWRY 1, ADIB 3, EFIH 1), trong đó 4 là bản lặp cùng URL (3 bản lặp của tiêu đề đã chấm, 1 bản lặp của trang dữ liệu ADIB). Mọi bản ghi qua luật hiện tại của lượt đó cũng khớp tên theo bộ lọc Tab 1–2;
    - phép tính tay 6 chữ số;
    - nguồn tin, truy vấn, bộ nhớ đệm, phiên bản luật, và câu "90 ngày, 15 tiêu đề, mức 10 tiêu đề cho truy vấn rộng, danh sách thể thao và mẫu trang dữ liệu là cấu hình demo, chưa được chứng minh là tối ưu".
  - **So hai danh mục A/B:** bật "So với danh mục B trên cùng lô tin", nhập cột vốn B (hoặc bấm nút điền ví dụ A 5 mã × 20%, B 50/30/20). Trang gửi **một** yêu cầu cho mọi mã của A và B (phần vốn của A, mã chỉ có ở B mang vốn 0), nên A và B dùng cùng một lần lấy tin và chấm FinBERT. Điểm mã không phụ thuộc phần vốn, nên trình duyệt tính S của B bằng đúng công thức mục 1 từ cùng phản hồi, và đối chiếu S, C, khoảng của A với số backend (lệch quá 10⁻⁹ thì không hiện so sánh). Biểu đồ "Vì sao B khác A": mỗi mã = (r_B − r_A) × s_i, cộng ra đúng S_B − S_A; khi cả hai đủ 100% vốn có tin, đây là (w_B − w_A) × s_i. Khi thiếu tin, mỗi S tính trên C của chính nó và trang hiện dải khoảng của cả A và B. Giới hạn: A và B cộng lại tối đa 5 mã (backend nhận tối đa 5 mã mỗi yêu cầu); ô cách bài báo tính trên mọi mã của A và B gộp lại.
  - Tab 1 và tab 2 không đổi (vẫn dấu chấm thập phân, giống bản tái dựng).
  - **Đã kiểm giao diện C3 bản 3 (Claude, môi trường dựng gói; Linux, Python 3.13, Chromium không giao diện):**
    - *Fixture:* `tests/check_browser.py` đạt. Script này kiểm mọi điều ở dòng bản 1 bên dưới, và thêm: phễu từng mã bằng số trong JSON; nhóm lý do đúng số; không còn các chữ "tin riêng", "có giữ", "cũng loại", "tin liên quan", "được giữ"; khối "Khớp tên theo bộ lọc Tab 1–2" đúng số bản ghi. Màn hình 390 px không tràn ngang, kể cả khi mở mọi mục chi tiết.
    - *Dựng lại JSON live:* hai JSON Codex lưu trên Windows ngày 04/11 được đưa thẳng vào trang, bằng cách chặn đúng lời gọi API coverage; trang không lấy tin mới. Chỉ thêm dấu hiệu phụ tính bằng relevance-v3, vì JSON lưu trước bản 3, và thay ghi chú cố định của backend bằng ghi chú bản 3.
      - Lượt A/B 16:59:38, phễu ứng viên / loại / qua luật / chấm / ngoài 15: COMI 66/53/13/13/0, ETEL 43/20/23/15/8, FWRY 12/5/7/7/0, ADIB 14/10/4/4/0, EFIH 11/8/3/3/0.
      - Lượt một danh mục: COMI 66/51/15/15/0, ETEL 63/41/22/15/7, FWRY 11/4/7/7/0.
      - Khối Tab 1–2: 11 bản ghi ở lượt A/B và 9 bản ghi ở lượt một danh mục. Dòng CBKD hiện "cũng khớp mẫu trang dữ liệu". S trên trang bằng S trong JSON. 390 px không tràn ngang; không lỗi JS.
      - Đây là phép dựng lại trên dữ liệu đã lưu, không phải lượt live mới. Lượt live bản 3 trên Windows: xem đoạn kế tiếp.
  - **Bản 3 trên Windows (Codex, 04/11/2026; bản sao riêng gồm gói C2 cộng 14 tệp của bản 3; thư mục làm việc không đổi):**
    - *Fixture:* Python 3.12.10, pytest 146 đạt, 1 bỏ qua (test notebook, thiếu pandas), 0 lỗi. `tests/check_browser.py` đạt với Chrome cài sẵn và Playwright 1.64.1 cài tay, gồm tab 1–2, tab 3, A/B và 390 px (0 px tràn, không bảng nào cuộn ngang). Bản 3.1 thêm Playwright vào `requirements-dev.txt` để khỏi cài tay.
    - *Tin live:* 22:29:29 giờ máy (giờ Việt Nam) ngày 04/11/2026, chế độ LIVE, tin từ RSS (Google News và BBC), chấm bằng ProsusAI/finbert chạy local trên CPU. EODHD không được gọi vì không cấu hình khóa. Google News RSS trả HTTP 200 cho mọi truy vấn: COMI 9 + 15, ETEL 7 + 36, FWRY 1 + 10 bản ghi (bậc 1 + bậc 2). Tin vĩ mô: BBC RSS 2, Google tin kinh tế 55.
    - *Danh mục 50/30/20:* 78 bản ghi ứng viên, 37 tự động loại, 41 qua luật hiện tại, 9 ngoài giới hạn 15, 32 tiêu đề doanh nghiệp được chấm. Độ phủ 100%. Điểm mã: COMI +0,427230, ETEL +0,329953, FWRY +0,144875. S = +0,341576 (trên trang +0,34). Tính tay: 0,5 × 0,427230 + 0,3 × 0,329953 + 0,2 × 0,144875 = 0,341576. Điểm tin vĩ mô +0,6891 chỉ để tham khảo, không cộng vào S.
    - Số khác lượt 03/11 là bình thường, vì tập tin và thời điểm đã đổi. Lượt này xác minh luồng LIVE và phép tính. Nó không xác minh luật lọc hay FinBERT đúng về kinh tế, và không dự báo giá.
  - **Đã kiểm giao diện C3 bản 1 như sau:**
    - *Fixture, môi trường dựng gói (Claude; Linux, Python 3.13, Chromium không giao diện):* pytest 117/117. `tests/check_browser.py`: JSON tab 1–2 bằng bản gốc; ở tab 3, tổng các thanh bằng S, mã thiếu tin không có thanh, dải khoảng khớp JSON; ở A/B, trang gửi đúng một yêu cầu và S của B khớp một POST riêng với vốn của B. Màn hình 390 px không tràn ngang; không lỗi JS.
    - *Fixture, Windows (Codex, bản sao sạch C3):* pytest 116 đạt, 1 bỏ qua. Test bỏ qua là `tests/test_notebook.py:55`, vì môi trường chưa có pandas; C3 không đổi notebook. `tests/check_browser.py` đạt, gồm tab 1–2, tab 3, A/B và màn hình 390 px.
    - *Tin live, Windows (Codex, 04/11/2026, giờ Việt Nam):* trình duyệt Chromium/Edge tải frontend C3, backend C3 chạy live. FinBERT chạy local trên CPU; tin lấy từ Google News RSS và BBC RSS; không dùng HF token hay khóa EODHD. Kết quả ở bảng mục 9.
    - **Giới hạn:** đây là xác nhận chạy thử. Nó chứng minh luồng giao diện và phép tính trong các lượt thử: giao diện hiện đúng số backend, A/B dùng một lô tin, và phép tính khớp. Nó **không** chứng minh độ chính xác gán nhãn (luật lọc tin và nhãn FinBERT chưa được so với nhãn của người), chưa gộp tin trùng sự kiện, và không nói gì về hiệu quả đầu tư hay dự báo giá.
- **Notebook.** Ô **[NÂNG CẤP C]** dùng đúng code của web app, chấm bằng FinBERT đã nạp ở các ô trên (không nạp model lần hai), đọc khóa EODHD từ Colab Secrets nếu có. Ô widget kế tiếp có nút "Xem độ phủ tin". Ô **[Đo, tùy chọn]** chạy công cụ thu tin ở mục 10.

## 9. Đã kiểm tra gì

| Kiểm tra | Kết quả |
|---|---|
| Toàn bộ kiểm thử | [Sự thật] Bản 3: 147/147 đạt (bản 2: 117 = 71 kiểm thử cũ giữ nguyên + 46 kiểm thử phần C; bản 3 thêm 30 kiểm thử loại trùng trong `tests/test_dedup_v3.py`) |
| Loại trùng bản 3 | [Sự thật] Bản cũ không che bản mới; mọi hoán vị cho cùng kết quả; tiêu đề rỗng ghi "thiếu tiêu đề"; cùng tiêu đề khác URL giữ cả hai; 19/30 kiểm thử báo lỗi khi cài lại logic bản 2 |
| Bản 3 không đổi số của fixture | [Sự thật] 9 danh mục ở tab 3 và 6 request tab 1–2 trước và sau bản 3: số đếm, điểm mã, S, C, khoảng và JSON tab 1–2 giống hệt. Chỉ khác chữ ghi chú, tên phiên bản luật và trường mới `pattern_flags` |
| Bản 3 trên dữ liệu live đã lưu | [Sự thật] 146 + 140 bản ghi của hai lượt Codex ngày 04/11 (cộng lượt POST kiểm tra) qua luật bản 3: 0 bản ghi đổi quyết định hay lý do; kết quả giữ nguyên khi xáo thứ tự |
| Tab 1, tab 2 và API gốc không đổi | [Sự thật] Fixture: 12 request (một mã, danh mục, gửi cả POST và GET; endpoint weighted cũ) cộng health và stocks giống hệt gói V2, chỉ khác giờ chạy `now_utc`. Live giả lập: phân tích một mã, danh mục, lấy tin đều giống hệt. Chromium: 4/4 đầu vào, JSON GET = POST = bản gốc, góc kim khớp JSON |
| Ví dụ tính tay | [Sự thật] 50/30/20 cho S = +0,30 và khoảng [+0,04; +0,44]; độ phủ 40% cho "chưa xác định hướng"; tổng đóng góp = S; vốn theo nhãn cộng ra 100% |
| Ô cách bài báo = tab 2 | [Sự thật] Đúng cho 3 bộ mã ở fixture và ở live giả lập, cả khi ô tin kinh tế gọi thêm truy vấn |
| Tin vĩ mô không làm đổi S | [Sự thật] Có kiểm thử |
| Thứ tự nguồn | [Sự thật] EODHD trước; Google hẹp khi EODHD không có tin phù hợp hoặc dưới 10; Google rộng khi vẫn dưới 10; tắt được; thiếu token khi cần thì HTTP 424 |
| Luật ADIB, bóng đá, trang TradingView, tin kinh tế | [Sự thật] Kiểm thử bằng tiêu đề thật (ADIB mẹ, ETEL bóng đá, trang Estimates của FWRY, 2 tin BBC) |
| Công cụ thu tin = web | [Sự thật] Cùng nguồn tin giả lập: tin công cụ đánh dấu "web chấm" trùng đúng tin tab 3 chấm, cả tin của mã lẫn tin kinh tế |
| Web tab 3 | [Sự thật] Chromium: JSON trên trang = JSON của POST; bản 3: phễu, nhóm lý do, khối Tab 1–2 khớp JSON, 390 px không tràn; bản 3.1: 320 px không tràn ở tab 1, 2 và 3 |
| Giao diện C3, Windows (Codex) | [Sự thật, số Codex gửi] Bản 1: pytest 116 đạt và 1 bỏ qua (test notebook, thiếu pandas); `tests/check_browser.py` ở chế độ fixture đạt. Bản 3: pytest 146 đạt, 1 bỏ qua, 0 lỗi (Python 3.12.10); `tests/check_browser.py` đạt; lượt live 22:29:29 ngày 04/11 cho S = +0,341576 (mục 8). Bản 3.1: 15/15 SHA-256 khớp; pytest 146 đạt, 1 bỏ qua; `tests/check_browser.py` 12/12 và 0 px tràn ở 320 px và 390 px khi chạy với `-X utf8`. Không có `-X utf8` thì script chết ở dòng in bảng (cp1252); bản 3.2 sửa chỗ này. Bản 3.2 chưa chạy trên Windows. Chạy live trên trình duyệt các bản trước: xem đoạn dưới |

**Chạy lại dữ liệu thật ngày 03/11** (lượt Windows 22:29 giờ Việt Nam, file trong `docs/du_lieu_03-11/`). Script: `python -m scripts.replay_saved_runs docs/du_lieu_03-11`. Kết quả với 5 mã mỗi mã 20%:

| Mã | Tab 1 (gộp tin của mã và vĩ mô) | Bộ lọc cũ giữ | Luật mới giữ | Điểm mã | Nhãn | Tin theo nhãn (+ · 0 · −) |
|---|---|---|---|---|---|---|
| COMI | Neutral +0,056 | 7 | 6 | +0,383 | Neutral | 2 · 4 · 0 |
| ETEL | Bearish −0,272 | 2 | 2 | +0,358 | Neutral | 1 · 1 · 0 |
| FWRY | Bearish −0,901 | 0 | 0 | — | không có tiêu đề qua luật | — |
| ADIB | Neutral −0,453 | 2 | 1 | +0,018 | Neutral | 0 · 1 · 0 |
| EFIH | Bearish −0,463 | 1 | 1 | +0,413 | Neutral | 0 · 1 · 0 |

- [Sự thật] Độ phủ 80%, S = +0,293, khoảng [+0,034; +0,434], hướng dương. Ô cách bài báo: −0,058 Neutral (9 tiêu đề).
- [Sự thật] Ô tin kinh tế: 0 tin, 2 tin vĩ mô bị loại vì là tin chính trị (bản 1 ghi M = −0,901 từ chính 2 tin này).
- [Sự thật] Với danh mục 50/30/20 trên cùng dữ liệu: độ phủ 80% (FWRY không có tiêu đề qua luật), S = +0,373, khoảng [+0,099; +0,499].
- [Sự thật] Luật mới loại 2 tin bộ lọc cũ giữ: trang báo giá LSE của COMI và trang "Seasonal Returns Chart" của ADIB.
- [Suy luận] Ở 3/5 mã, nhãn tab 1 khác nhãn của mã ở tab 3. Tab 1 trộn 2 tin chính trị rất tiêu cực với tin của mã, nên FWRY (không có tiêu đề nào qua luật) vẫn nhận Bearish −0,901 chỉ từ 2 tin đó.
- [Sự thật] File tab 1 chỉ chứa tin bộ lọc cũ đã giữ, và lượt này chưa gọi truy vấn rộng. Phép chạy lại chỉ thấy luật mới loại bớt, không thấy tin truy vấn rộng sẽ thêm.

**Lượt thật ngày 04/11 do Codex chạy trên Windows (gói bản 1, chỉ Google, không EODHD).** [Sự thật, số Codex gửi] 5 mã mỗi mã 20%: Google hẹp trả 9/6/1/5/3 ứng viên cho COMI/ETEL/FWRY/ADIB/EFIH, giữ 3/0/0/1/1. Điểm COMI +0,636, ADIB +0,018, EFIH +0,413. C = 60%, S = +0,356, khoảng [−0,187; +0,613], chưa xác định hướng. Ô vĩ mô: 2 tin tự do báo chí, M = −0,901. Phép thử truy vấn rộng cùng ngày: FWRY thêm 11 ứng viên, giữ 8; ETEL thêm 43, giữ 22.

**Lượt live giao diện C3 ngày 04/11 do Codex chạy trên Windows** (trình duyệt tải frontend C3, backend live, FinBERT local CPU, Google News RSS và BBC RSS, không HF token hay khóa EODHD). [Sự thật, số Codex gửi]

| Lượt (giờ Việt Nam) | Danh mục | C | Tiêu đề được chấm | S |
|---|---|---|---|---|
| 16:47:43, một danh mục | COMI 50 / ETEL 30 / FWRY 20 | 100% (3/3 mã) | 37 | +0,357610 (giao diện +0,36); dải co về S |
| 16:59:38, so A/B, A | 5 mã × 20% (COMI, ETEL, FWRY, ADIB, EFIH) | 100% | 42 | +0,264391 |
| 16:59:38, so A/B, B | COMI 50 / ETEL 30 / FWRY 20 | 100% | 35 | +0,325797 |

- [Sự thật, số Codex gửi] B − A = +0,061405. Phép trừ hai số S đã làm tròn 6 chữ số ra +0,061406; chênh ở chữ số thứ 6 là do làm tròn. Số đầy đủ Codex gửi: S_A = +0,26439144936475506; S_B = +0,32579671889246736; B − A = +0,0614052695277123. Tổng các thanh "Vì sao B khác A" là +0,0614.
- [Sự thật, số Codex gửi] Lượt A/B chỉ gửi một POST, nên A và B dùng cùng một lô tin. Một POST riêng với vốn của B cho S khớp. Mục "Tính tay" báo "Khớp" (chênh dưới 10⁻⁹). Không có lỗi JavaScript.
- [Sự thật] Bộ nhớ đệm tin giữ 10 phút cho từng nhóm tin. Ở lượt A/B, một phần nhóm tin dùng lại bộ nhớ đệm (tin lấy chưa quá 10 phút), và giao diện ghi rõ giờ lấy tin.
- [Sự thật] Lượt một danh mục và lượt A/B cách nhau khoảng 12 phút và dùng tin của hai thời điểm (37 và 35 tiêu đề cho cùng 3 mã). Vì vậy S +0,357610 và S_B +0,325797 không phải hai phép đo trên cùng một tập tin, không so với nhau. Hai số này cũng khác +0,312427 và +0,416665 buổi trưa vì tin khác giờ.
- [Sự thật] Đây là xác nhận chạy thử: nó chứng minh luồng giao diện và phép tính trong các lượt thử, không chứng minh độ chính xác gán nhãn (luật lọc tin, nhãn FinBERT) hay hiệu quả đầu tư (xem mục 11).

**Kiểm với tin thật lấy trực tiếp.** [Sự thật] Môi trường dựng gói này không vào được Google News và BBC; các kiểm thử live của Claude đều dùng nguồn tin giả lập. Chỉ Codex chạy với tin thật lấy trực tiếp, trên Windows: bản 1 ngày 04/11 (đoạn trên), bản 2 qua API ngày 04/11 (theo phụ lục bàn giao C2), và giao diện C3 qua trình duyệt (bảng trên). Số liệu FinBERT trong tài liệu này lấy từ lượt chạy Windows, không lấy từ model trong môi trường dựng gói.

## 10. Công cụ đo (chỉ báo số đo, không có ngưỡng đạt hay không đạt)

| Script | Làm gì |
|---|---|
| `scripts/capture_candidates.py` | Thu một lượt **mọi** ứng viên tin trước khi lọc: EODHD (nếu có khóa), Google hẹp, Google rộng (tắt bằng `--no-tier2`), tin vĩ mô, truy vấn tin kinh tế. Ghi luật mới, bộ lọc cũ, web có gọi hay chấm tin đó không, và tùy chọn xác suất FinBERT (`--score`). Quyết định "web gọi truy vấn nào" lấy từ chính hàm `fetch_candidates` của web. Mỗi lượt một thư mục `captures/<giờ UTC>/`. Không ghi khóa API |
| `scripts/summarize_captures.py` | Gộp nhiều lượt: số tin mỗi mã theo ngày, độ phủ của một danh mục ở từng lượt, số lượt có độ phủ trên 50% |
| `scripts/make_label_sheet.py` | Tạo phiếu gán nhãn **mù** cho 2 người (không có kết quả của máy, thứ tự xáo trộn) và file khóa riêng. Hai loại: tin có đúng doanh nghiệp không; tin tích cực, tiêu cực hay trung tính (câu hỏi theo Financial PhraseBank) |
| `scripts/score_relevance.py` | Từ hai phiếu: tỷ lệ đồng ý, Cohen κ, precision và recall của bộ lọc cũ và luật mới kèm khoảng Wilson 95%, số tin bị loại sai theo từng lý do. (Chưa dùng cho kế hoạch gán nhãn bên dưới: script in khoảng Wilson và dùng nhãn hai lớp, cần sửa trước.) Loại sentiment ghi thêm file `text,label` để đo FinBERT bằng `scripts.evaluate_finbert --data-csv` |
| `scripts/replay_saved_runs.py` | Tính lại tab 3 từ phản hồi tab 1 đã lưu, không cần mạng hay model |

Trên Windows, khi đầu ra bị chuyển hướng (pipe, file, công cụ chạy lệnh), chạy 4 công cụ đầu bằng `python -X utf8 -m scripts.<tên>`. Nếu không, chúng có thể chết ở chữ Việt đầu tiên (bảng mã cp1252). `replay_saved_runs` và `tests/check_browser.py` tự xử lý việc này từ bản 3.2.

**Kế hoạch đo luật lọc trên lượt 16:59:38 (chưa chạy; [Nhóm chọn], pi và Codex chốt 04/11).**

1. Hai người gán nhãn **mù** cho **toàn bộ** 146 bản ghi ứng viên của lượt A/B 16:59:38. Người gán không thấy quyết định của máy, và gán từng bản ghi độc lập. 146 bản ghi gồm cả bản lặp cùng URL. Đây không phải 146 sự kiện, và không đại diện cho tin EGX nói chung.
2. Báo cáo:
   - bảng chéo "quyết định của máy (qua luật, hoặc bị loại theo từng lý do) × nhãn của người";
   - danh sách bản ghi có nói về công ty mà bị luật loại nhầm;
   - tỷ lệ đồng ý và Cohen κ của hai người cho từng nhãn.
3. Kết luận chỉ đúng cho lượt này. Không tính khoảng Wilson 95% như thể 146 bản ghi là một mẫu ngẫu nhiên.
4. Muốn nói rộng hơn thì cần nhiều ngày thu tin độc lập và phải nêu rõ tổng thể muốn nói tới (mã nào, nguồn nào, khoảng thời gian nào).
5. Đo luật lọc tách khỏi đo sắc thái FinBERT. Sắc thái FinBERT trên tin EGX cũng chưa được kiểm chứng.
6. Các lượt thu sau lưu thêm: trạng thái bộ nhớ đệm, giờ lấy tin, truy vấn đã gọi và JSON đầy đủ.

Ví dụ đọc Cohen κ: hai người cùng gán 100 tin và đồng ý 90 tin. Nếu cả hai đều nói "có" 80% số tin, tỷ lệ đồng ý do may mắn là 0,8 × 0,8 + 0,2 × 0,2 = 0,68, nên κ = (0,90 − 0,68) / (1 − 0,68) ≈ 0,69.

## 11. Điều tài liệu này không khẳng định

- [Sự thật] Không có backtest giá EGX. Tab không nói giá sẽ lên hay xuống.
- [Sự thật] FinBERT được huấn luyện trên tin tài chính tiếng Anh chung, chưa được đo riêng trên tin EGX.
- [Sự thật] Luật relevance-v3 (luật nội dung giống relevance-v2) chưa được đo bằng nhãn của người; tỷ lệ tin đúng công ty của truy vấn rộng chưa được đo.
- [Suy luận] Người dùng ở đầu tài liệu là định vị demo tạm thời, chưa được xác nhận bằng khảo sát người dùng hay thị trường thật.
- [Sự thật] Số bản ghi ứng viên không phải số sự kiện: bản này không gộp tin theo sự kiện.
- [Suy luận] Độ phủ thực tế thay đổi theo ngày, vì số tiêu đề về mã nhỏ thường rất ít. Muốn biết độ phủ thường là bao nhiêu phải thu nhiều lượt bằng công cụ ở mục 10.
