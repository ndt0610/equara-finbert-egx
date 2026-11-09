# Hướng dẫn demo trực tiếp

## Trạng thái hiện tại

Backend đang chạy tại **http://127.0.0.1:8000/** trong chế độ live, với `ProsusAI/finbert` chạy local trên CPU. Lần kiểm tra trình duyệt gần nhất dùng BBC RSS và Google News RSS; `eodhd_token_configured=false`, nên Backend bỏ qua EODHD và không gửi request tới dịch vụ này.

Trang hiển thị tiêu đề, nguồn tin, xác suất Positive/Negative/Neutral cho từng headline, xác suất tổng hợp và sentiment tổng hợp. Khối **Nguồn tin & trạng thái provider** cho biết số headline đã phân tích theo nguồn và trạng thái lần truy vấn. Trạng thái `trả về N mục nguồn` là số mục provider trả trước khi giới hạn/deduplicate; số headline thực sự phân tích được hiển thị riêng ngay phía trên.

## Khởi chạy an toàn cho buổi demo

Mở PowerShell trên máy demo. Nếu tiến trình hiện tại không còn chạy, dùng lệnh sau. Đặt `EODHD_API_TOKEN` rỗng trong đúng cửa sổ PowerShell này để đảm bảo lượt demo chỉ dùng RSS và không tiêu hao hạn mức EODHD.

```powershell
Set-Location '<thư mục dự án đã giải nén>'
$env:DEMO_MODE = 'live'
$env:INFERENCE_PROVIDER = 'transformers-local'
$env:LOCAL_INFERENCE_DEVICE = 'cpu'
$env:EODHD_API_TOKEN = ''
& '.\.venv\Scripts\python.exe' -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Giữ cửa sổ server mở và truy cập **http://127.0.0.1:8000/** trên cùng máy. Nếu cổng 8000 đang được tiến trình cũ sử dụng, dừng tiến trình Uvicorn đó bằng `Ctrl+C` trong cửa sổ server, rồi chạy lệnh trên.

Trước khi demo, xác nhận trạng thái cấu hình bằng:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/health' |
  Select-Object status,data_mode,inference_provider,inference_device,eodhd_token_configured
```

Giá trị cần thấy: `status=ok`, `data_mode=live`, `inference_provider=transformers-local`, `inference_device=cpu`, `eodhd_token_configured=False`. Không cần cấu hình hoặc hiển thị token cho lượt RSS-only này. Lần đầu có thể mất thêm thời gian tải model weights công khai nếu chưa có trong cache; đây không phải request Inference API.

## Kịch bản 1 — Single Stock

1. Chọn tab **Một cổ phiếu**, giữ mã `COMI`, rồi bấm **Phân tích**.
2. Chỉ ra nhãn tổng hợp, ba xác suất, tổng số headline và số inference local.
3. Chỉ ra khối **Nguồn tin & trạng thái provider** và thẻ tin có tiêu đề, nguồn/publisher, loại micro/macro, mã nếu có, ba xác suất riêng và liên kết nguồn.
4. Nêu rõ EODHD bị bỏ qua vì không cấu hình trong buổi demo; RSS cung cấp dữ liệu thực tế. Google News macro được bỏ qua vì BBC RSS đã trả headline.

Snapshot trình duyệt ngày 01-11-2026: COMI.EGX có 12 headline (Google News RSS 10, BBC RSS 2), 12 local FinBERT inferences, kết quả **Neutral**: Positive 25.3%, Negative 16.7%, Neutral 58.0%; score hiển thị 0.086. Headline RSS thay đổi theo thời gian, nên con số có thể khác ở lần chạy sau.

## Kịch bản 2 — Portfolio Sentiment

1. Chọn tab **Danh mục**, giữ `COMI, ETEL, FWRY, ADIB, EFIH`, rồi bấm **Phân tích danh mục**.
2. Chỉ ra danh sách năm mã, sentiment và ba xác suất tổng hợp.
3. Chỉ ra cảnh báo nếu thiếu tin micro hoặc macro và khối trạng thái provider.

Snapshot trình duyệt ngày 01-11-2026: 6 headline (Google News RSS 4, BBC RSS 2), 6 local FinBERT inferences, kết quả **Neutral**: Positive 9.3%, Negative 31.9%, Neutral 58.9%; score hiển thị -0.226. Lượt này không có tin micro cho ETEL.EGX và FWRY.EGX; chỉ có 2 headline macro. Nêu rõ nguồn tin mỏng hơn mục tiêu danh mục của bài báo.

## Kịch bản 3 — Danh mục theo vốn (phần C)

**Dành cho ai.** Người học, người hướng dẫn hoặc người phân tích đang xem một demo học thuật nhỏ về tin của tối đa 5 mã EGX: họ cần thấy tiêu đề ứng viên nào đi vào phép tính S và C, và vì sao các bản ghi khác bị loại. Đây là định vị demo tạm thời, chưa phải công cụ đã kiểm chứng để nhà đầu tư dùng ra quyết định. Khi nói số đếm, dùng "bản ghi ứng viên" hoặc "tiêu đề ứng viên", không gọi là "sự kiện": một tin đăng ở hai báo, hay một URL xuất hiện ở hai truy vấn, là hai bản ghi.

1. Chọn tab **Danh mục theo vốn (nâng cấp)**. Đọc câu "Dành cho ai" ở đầu tab. Giữ COMI 50, ETEL 30, FWRY 20 (phần trăm vốn), rồi bấm **Xem độ phủ tin**.
2. Chỉ ra **độ phủ tin**: bao nhiêu phần vốn có ít nhất một tiêu đề qua luật hiện tại (tiêu đề nhắc đúng tên công ty và qua các luật ở `docs/PHAN_C_DO_PHU_TIN_VI.md` mục 3). Mã không có tiêu đề nào qua luật hiện "Không có tiêu đề qua luật hiện tại" kèm các truy vấn đã gọi, không bị gán điểm. Mã có dưới 10 tiêu đề qua luật được tìm thêm bằng truy vấn rộng; bản ghi đó ghi "bậc 2".
3. Chỉ ra khối tóm tắt: điểm S trên phần vốn có tin (không phải dự báo giá), số tiêu đề được chấm kèm câu đếm "từ N bản ghi ứng viên: X bị luật tự động loại, Y qua luật hiện tại, trong đó Z ngoài giới hạn 15", LIVE/FIXTURE và giờ lấy tin. Lưu ý ngay dưới S: điểm tính theo từng tiêu đề; bản này chỉ bỏ bản lặp cùng URL, nhiều tiêu đề về cùng một sự kiện vẫn được tính nhiều lần. Chỉ ra biểu đồ "Mã nào kéo điểm lên, mã nào kéo xuống": mỗi thanh là đóng góp của một mã, cộng các thanh ra đúng S; mã không có tiêu đề qua luật là dòng xám, không có thanh. Dải khoảng giới hạn trên thang −1 đến +1 chỉ hiện khi còn vốn chưa có tin; tab chỉ nói hướng khi cả dải nằm về một phía của 0. Khi đủ 100% vốn có tin, dải được thay bằng câu giải thích khoảng co về S.
4. Bấm vào dòng của một mã. Ở đầu là **phễu đếm**, chỉ có số đếm, không có tỷ lệ phần trăm: ứng viên = tự động loại + qua luật hiện tại; qua luật hiện tại = được chấm + qua luật nhưng ngoài giới hạn 15. Bên dưới là bảng tiêu đề được chấm, rồi hai mục thu gọn:
   - "Qua luật hiện tại nhưng ngoài giới hạn 15": mỗi mã chỉ chấm 15 tiêu đề mới nhất theo ngày đăng, ngày không rõ xếp sau.
   - "Bị luật tự động loại": nhóm theo lý do đầu tiên khớp, mỗi bản ghi có ngày, nguồn và bậc truy vấn. Nói rõ ba điều ghi trong mục: quyết định loại là tự động, chưa có người kiểm; luật có thể loại nhầm tin có nói về công ty nhưng tiêu đề không nêu tên công ty; mỗi bản ghi chỉ ghi lý do đầu tiên khớp. "Dấu hiệu khác" cho biết tiêu đề còn khớp mẫu trang dữ liệu hay từ khóa thể thao. Ví dụ thật ngày 04/11: "CBKD Stock Price and Chart — LSIN:CBKD - TradingView" (trang giá GDR London của CIB) nằm ở nhóm "tiêu đề không nhắc tên hay alias của công ty", vì luật tên xét trước, và có dấu hiệu khác "cũng khớp mẫu trang dữ liệu".

   Nhãn FinBERT của từng mã (kể cả trường hợp nhãn Neutral mà điểm dương) và thanh vốn theo nhãn nằm trong mục thu gọn "Chi tiết · Nhãn FinBERT của từng mã".
5. Mở mục "Tham khảo":
   - ô tin kinh tế và thị trường Ai Cập hiện riêng, không cộng vào S (tin chính trị bị loại kèm lý do);
   - ô "cách bài báo" cho thấy cùng lượt tin nếu gộp chung như tab 2;
   - ô "Khớp tên theo bộ lọc Tab 1–2" chỉ để đối chiếu. Bộ lọc này chỉ kiểm tên hoặc alias có nằm trong tiêu đề + mô tả hay không (so chuỗi con). Nó không phải quyết định cuối của luồng Tab 1–2. Ví dụ lượt live 16:59:38 ngày 04/11: 11 bản ghi bị luật hiện tại loại nhưng khớp tên. Đó là 11 bản ghi trong lượt đó, không phải 11 sự kiện.
6. So hai danh mục: bật "So với danh mục B trên cùng lô tin", bấm nút điền ví dụ (A 5 mã × 20%, B 50/30/20) rồi bấm **So hai danh mục**. Trang gửi một yêu cầu cho mọi mã của A và B, nên hai danh mục dùng cùng một lô tiêu đề; biểu đồ "Vì sao B khác A" cho phần chênh của từng mã, cộng ra đúng S của B trừ S của A. A và B cộng lại tối đa 5 mã.

Giao diện bản 3 được kiểm bằng dữ liệu fixture trong môi trường dựng gói (Linux). Hai lượt JSON live Codex lưu trên Windows ngày 04/11 cũng được dựng lại trên giao diện bản 3: trang nhận nguyên JSON đã lưu, không lấy tin mới. Lượt A/B 16:59:38 cho phễu COMI 66 = 53 + 13, ETEL 43 = 20 + 23 (15 được chấm, 8 ngoài giới hạn), FWRY 12 = 5 + 7, ADIB 14 = 10 + 4, EFIH 11 = 8 + 3. Tổng: 146 bản ghi ứng viên, 96 bị loại, 50 qua luật, 42 được chấm.

Codex chạy giao diện C3 bản 1 với tin live trên Windows ngày 04/11: 50/30/20 cho độ phủ 100% và S +0,36; nút "Điền ví dụ" A/B cho A +0,264, B +0,326, B − A +0,061 trên cùng một lô tin. Bản 3 không đổi S, C hay khoảng giới hạn. Chi tiết và giới hạn ở `docs/PHAN_C_DO_PHU_TIN_VI.md` mục 0, 8 và 9.

Đây là xác nhận chạy thử: nó chứng minh luồng giao diện và phép tính trong các lượt thử, không chứng minh độ chính xác gán nhãn (luật lọc tin, nhãn FinBERT) hay hiệu quả đầu tư. Bộ nhớ đệm giữ tin 10 phút, nên hai lượt cách nhau dưới 10 phút có thể dùng lại một phần tin; giao diện ghi rõ giờ lấy tin.

Ví dụ thật ngày 03/11 (tính lại từ lượt Windows đã lưu, không phải lượt trình duyệt, chưa có truy vấn rộng): COMI 50, ETEL 30, FWRY 20 cho độ phủ 80% (FWRY không có tiêu đề qua luật), điểm +0,373, khoảng [+0,099; +0,499]. Tin thay đổi theo ngày, nên con số có thể khác. Chi tiết cách tính trong `docs/PHAN_C_DO_PHU_TIN_VI.md`. Đây không phải tư vấn đầu tư hay khuyến nghị giao dịch chứng khoán, và không dự báo giá.

## Kiểm tra REST nhanh

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/health'
Invoke-RestMethod 'http://127.0.0.1:8000/api/stocks'
```

Giao diện gọi `GET /api/sentiment/stock?symbol=…` và `GET /api/sentiment/portfolio?symbols=…` (cùng JSON với POST), và tab theo vốn gọi `POST /api/v2/sentiment/portfolio/coverage`. Lịch sử kiểm thử live trên trình duyệt được ghi trong `artifacts/web_demo_browser_verification.json` và `docs/VERIFICATION_REPORT_VI.md`.

## Đối chiếu với bài báo và giới hạn demo

- Bài báo mô tả pipeline News Aggregation → NLP Inference → Aggregation & API, tin micro và macro, ba nhãn FinBERT với softmax, và danh mục tối đa năm mã với 1–2 headline mỗi holding.
- Bản dựng giữ model `ProsusAI/finbert` và ba xác suất softmax. Ở web demo, inference chạy trong tiến trình Backend bằng Transformers local; bài báo dùng Hugging Face Inference API.
- Bài báo không công bố công thức sentiment tổng hợp hoặc giao diện gốc. Score và quy tắc aggregate trên trang là lựa chọn tái dựng được ghi rõ cạnh kết quả; UI web không phải app mobile Equara AI gốc.
- Hạn mức lấy tin trong mỗi lượt được giới hạn theo kiến trúc. Nguồn RSS có thể trả ít tin hơn; không tạo headline hoặc xác suất thay thế.
- Kết quả lần chạy chỉ thể hiện sentiment trên các headline đã thu được, không phải khuyến nghị đầu tư.

Nếu cần dùng EODHD trong một buổi demo khác, hãy chạy notebook Colab theo `docs/COLAB_DEMO_GUIDE_VI.md`; notebook đọc Secret `EODHD_API_TOKEN` mà không in giá trị. Các request EODHD đã kiểm tra trước đây đều HTTP 200 với 0 headline; response rỗng không chứng minh feed có tin. Không nâng cấp gói hoặc thực hiện thanh toán để làm demo.
