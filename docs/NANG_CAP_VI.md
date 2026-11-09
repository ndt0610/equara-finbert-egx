# Nâng cấp cho bản tái dựng Equara AI / FinBERT

**Phần C (mới, 03/11/2026): tab "Danh mục theo vốn" nay tính độ phủ tin theo vốn.** Cách tính, luật lọc tin, cấu hình, API, kiểm thử và công cụ đo nằm trong [PHAN_C_DO_PHU_TIN_VI.md](PHAN_C_DO_PHU_TIN_VI.md). Tab 3 và notebook không còn dùng β, chu kỳ bán rã hay κ theo mặc định.

Các Module 1–2 bên dưới (trọng số tuổi và độ rõ, điểm theo vốn cộng β vĩ mô) là **phương án cũ ngày 01/11**. Code và endpoint `/api/v2/sentiment/portfolio/weighted` vẫn giữ nguyên để tái lập các bảng và biểu đồ của hồ sơ 01/11 (`scripts/run_upgrade_demo.py --from-run`), nhưng giao diện không còn gọi chúng. Module 3 (bộ nhớ đệm) vẫn dùng cho cả phần C.

Cách tính điểm của phần lõi **không đổi**: hai endpoint cũ `/api/sentiment/stock` và `/api/sentiment/portfolio` vẫn trả JSON giống hệt bản gốc với cùng đầu vào (so tự động 4 request ở chế độ fixture). Ở chế độ live công thức giữ nguyên. Khi dùng adapter HTTP, số request và request_mode có thể thay đổi do batching. JSON có thêm khối `data_freshness` và các trường ghi từng lượt gọi nguồn tin (giờ gọi, địa chỉ truy vấn, mã HTTP, thời gian chờ) để giao diện chứng minh tin được lấy trực tiếp. Mọi thứ mới nằm trong `backend/upgrades/`, `scripts/`, `tests/`, các endpoint `/api/v2/...` ở cuối `backend/app.py`, tab thứ 3 trên giao diện web và các ô [NÂNG CẤP C] / [KIỂM TRA] của notebook.

## Giai đoạn 1: hoàn thiện phần lõi (sửa lỗi, không đổi công thức)

| Chỗ còn thiếu | Bằng chứng trước khi sửa | Sửa ở đâu | Sau khi sửa |
|---|---|---|---|
| Nhập mã sai sàn (`COMI.NYSE`) hoặc mã trùng làm server lỗi | HTTP 500 Internal Server Error | `backend/app.py`, hàm `validation_error_handler`: dùng `jsonable_encoder` | HTTP 422, thông báo "Chỉ nhập mã cổ phiếu EGX, ví dụ COMI hoặc COMI.EGX." |
| HF API trả 429 (giới hạn tốc độ) hoặc 503 (model đang nạp) là cả lượt phân tích thất bại | Adapter báo lỗi ngay ở lần gọi đầu | `backend/providers/hf_inference.py`: thử lại tối đa 2 lần, chờ theo `Retry-After` / `estimated_time`, trần 10 giây | Kiểm thử: 503 rồi 200 → thành công sau 1 lần thử lại; 429 liên tục → dừng sau 3 lần; 401 không thử lại |
| Tin các mã trong danh mục được lấy lần lượt | 5 mã = 5 lượt chờ nối tiếp + 1 lượt vĩ mô | `backend/services/sentiment.py`: `asyncio.gather` | Cùng danh sách tin, cùng thứ tự trạng thái (có kiểm thử), thời gian chờ ≈ lượt chậm nhất |
| Dự án không có kiểm thử | Không có thư mục `tests/` | `tests/test_core.py` | 16 kiểm thử phần lõi |
| Bài báo mục 8 gửi ~15 tiêu đề / request HF; code gửi từng tiêu đề | 14 tiêu đề danh mục = 14 request HTTP | `backend/providers/hf_inference.py` (`classify_many`), `backend/services/sentiment.py` | 1 request cho tối đa 15 tiêu đề; HF từ chối mảng thì tự quay về từng tiêu đề (kiểm thử với HF giả lập) |
| Đường gọi Hugging Face API của bài báo chưa chạy thật lần nào | Tài khoản miễn phí bị HTTP 402: lượt thử của nhóm được báo trả HTTP 402 | `backend/config.py` (`HF_INFERENCE_URL`), `backend/providers/hf_inference.py` (`endpoint`), `scripts/serve_hf_api.py` | Cùng adapter gọi máy chủ FinBERT tự dựng theo định dạng Hugging Face qua HTTP thật, không cần token; token chỉ gửi tới huggingface.co |
| Giao diện không cho thấy tin được lấy trực tiếp hay lấy lúc nào | Bảng nguồn chỉ ghi `used:3`; notebook giữ tin đã lấy suốt phiên Colab mà không báo | `backend/providers/news.py` (`_get`, `public_url`), `backend/services/sentiment.py` (`data_freshness`), `backend/upgrades/service.py`, `frontend/app.js`, notebook | Khung xanh "Tin lấy trực tiếp từ internet lúc …" hoặc vàng "Dùng lại tin đã lấy lúc …"; bảng từng lượt gọi có giờ gọi, mã HTTP, thời gian chờ, link mở lại truy vấn (khóa EODHD bị xóa khỏi link); notebook chỉ dùng lại tin 10 phút, có ô "Lấy tin mới" |
| Sơ đồ mục 2–3: app gọi `GET sentiment`; code chỉ có POST | Không gọi được bằng GET | `backend/app.py` | `GET /api/sentiment/stock?symbol=COMI`, `GET /api/sentiment/portfolio?symbols=COMI,ETEL,FWRY`, cùng JSON với POST |

## Bản đồ file mới

| File | Module | Vai trò |
|---|---|---|
| `backend/upgrades/relevance.py` | C | Luật lọc tin riêng relevance-v2: trùng, cũ hơn 90 ngày, tên không có trong tiêu đề, tên ADIB không kèm chữ Ai Cập, tin thể thao, trang dữ liệu; mỗi tin bị loại có đúng một lý do tiếng Việt. `judge_macro`: tin vĩ mô phải nói về kinh tế hay thị trường |
| `backend/upgrades/coverage.py` | C | Điểm mã s_i, độ phủ C, tỷ trọng tính lại, đóng góp, điểm S, khoảng giới hạn, hướng, vốn theo nhãn; `CoverageConfig` (mọi tùy chọn thử nghiệm mặc định tắt) |
| `backend/upgrades/coverage_service.py` | C | Lấy ứng viên (EODHD trước, Google hẹp khi EODHD không có hoặc dưới 10 tin phù hợp, Google rộng khi vẫn dưới 10), lọc, lọc tin kinh tế, chấm FinBERT qua cache, dựng ô "cách bài báo" từ cùng lượt tin, trả JSON tab 3 |
| `fixtures/coverage_candidates.json` | C | 4 ứng viên [FIXTURE] mà bộ lọc cũ giữ còn luật mới loại, để fixture thấy được bảng "tin bị loại" |
| `scripts/capture_candidates.py`, `summarize_captures.py`, `make_label_sheet.py`, `score_relevance.py`, `replay_saved_runs.py` | C | Công cụ đo: thu mọi ứng viên, tóm tắt độ phủ theo ngày, phiếu gán nhãn mù, κ và precision/recall, chạy lại từ lượt đã lưu |
| `tests/test_coverage.py`, `test_measurement_tools.py`, `test_notebook.py` | C | 40 kiểm thử: ví dụ tính tay, các ca biên, luật lọc, API, ô cách bài báo = tab 2, thứ tự nguồn, cache, công cụ đo, ô notebook phần C |
| `docs/du_lieu_03-11/`, `docs/BANG_TAB1_03-11.md` | C | Phản hồi tab 1 thật của lượt Windows 03/11 22:29 (5 mã) và bảng đọc nhanh |
| `backend/upgrades/time_confidence.py` | 1 (cũ) | Trọng số thời gian `0.5^(giờ/H)`, độ rõ ràng `|P+ − P−|`, gộp có co về trung tính `Σws/(Σw+κ)`; quy tắc "đủ tin" `Σw ≥ κ` |
| `backend/upgrades/portfolio_weighting.py` | 2 (cũ) | Tỷ trọng vốn, beta vĩ mô, `S_k = clip(micro_k + β_k·M)`, `S = Σ vốn_k·S_k`, quy đổi đóng góp từng tin; hàm `article_baseline` gọi đúng hàm lõi để in điểm theo bài báo |
| `backend/upgrades/ttl_cache.py` | 3 | `TTLCache` (hết hạn + LRU), `CachedInference` bọc provider lõi (local hoặc HF API) |
| `backend/upgrades/charts.py` | 3 | Vẽ 3 biểu đồ PNG bằng matplotlib |
| `backend/upgrades/service.py` | ghép | `UpgradedPortfolioService`: dùng lại `NewsAggregator` và provider của lõi, thêm cache, trả song song điểm gốc và điểm mới |
| `backend/upgrades/schemas.py` | ghép | Kiểm tra input: tỷ trọng ≥ 0, β trong [0, 3], không trùng mã |
| `scripts/run_upgrade_demo.py` | 1+2+3 | Chạy FinBERT thật, đối chiếu với kết quả cũ, đo latency, xuất 3 PNG + `BANG_SO_LIEU.md`; `--from-run` tính lại từ xác suất đã lưu, không cần model |
| `tests/test_upgrades.py` | 1+2+3 | 22 kiểm thử: công thức, cộng đóng góp = tổng, cache hết hạn, cache giảm request HF, endpoint v2, trạng thái "Không đủ tin", tính lại từ lần chạy trước |
| `tests/test_core.py` | lõi | 16 kiểm thử: chuẩn hóa mã, loại trùng, ngày giờ, công thức gốc, lỗi 422, thử lại HF, gửi theo lô + quay về, GET = POST, luồng danh mục song song |
| `frontend/index.html`, `app.js`, `style.css` | ghép | Tab "Danh mục theo vốn" (phần C): nhập mã và phần vốn, thang −1 đến +1 với điểm S và khoảng giới hạn, thanh vốn theo nhãn, thẻ từng mã với tin đã chấm, tin bị loại kèm lý do, tin chưa chấm, ô điểm vĩ mô, ô cách bài báo, phép tính tay. Cả 3 tab: khung "Tin lấy trực tiếp lúc …" / "Dùng lại tin đã lấy lúc …", bảng từng lượt gọi nguồn tin (giờ gọi, kết quả, mã HTTP, thời gian chờ, link truy vấn), giờ đăng và tuổi của từng tiêu đề kèm link bài gốc |
| `scripts/evaluate_finbert.py` | đánh giá | Đo độ chính xác FinBERT so với model review phim (SST-2) trên tin tài chính có nhãn; kiểm chứng trọng số độ rõ; xuất biểu đồ 4 và 5, `BANG_DANH_GIA.md`, `predictions.csv`; `--from-run` tính lại không cần model |
| `scripts/serve_hf_api.py` | lõi | Máy chủ FinBERT tự dựng (bài báo mục 8: self-hosted), nhận và trả JSON giống hệt Hugging Face text-classification tại `/models/ProsusAI/finbert`; `/stats` đếm request đã nhận; miễn phí, không cần token |
| `scripts/check_hf_api.py` | lõi | Gửi 7 tiêu đề tham chiếu qua đúng adapter của backend tới Hugging Face thật (cần credit) hoặc máy chủ tự dựng (`--endpoint`), so xác suất với FinBERT local, đo gửi theo lô so với từng tiêu đề (1 request khởi động, trung vị 3 vòng); ghi `hf_api_check.json` hoặc `self_hosted_api_check.json` kể cả khi lỗi |
| `tests/test_hf_api_check.py` | lõi | 3 kiểm thử với Hugging Face giả lập: 7 tiêu đề = 1 request theo lô và khớp xác suất, gửi từng tiêu đề = 7 request, phát hiện phiên bản model khác, báo 402 và thiếu token mà không lộ token |
| `tests/test_self_hosted_hf_api.py` | lõi | 5 kiểm thử: định dạng Hugging Face của máy chủ tự dựng (1 tiêu đề, nhiều tiêu đề, lỗi 400/404/413/422), adapter chạy qua HTTP thật trên cổng 127.0.0.1, token không bao giờ gửi tới máy chủ tự dựng, luồng danh mục 5 mã của web app = 1 request |
| `tests/test_live_data_display.py` | lõi | 4 kiểm thử: link truy vấn không chứa khóa EODHD, mỗi lượt gọi nguồn tin ghi giờ gọi + địa chỉ + mã HTTP + thời gian chờ + mã cổ phiếu, response live có khối `data_freshness`, lần bấm thứ hai ở tab nâng cấp đánh dấu tin dùng lại và giữ giờ lấy thật ban đầu |
| `tests/test_evaluation.py` | đánh giá | 11 kiểm thử: đọc nhãn, khoảng tin cậy Wilson, McNemar, chỉ số từng nhãn, chọn ví dụ, phân tích độ rõ, đọc lại `predictions.csv`, `--from-run`, đếm request HF theo lô |
| `notebooks/Equara_AI_FinBERT_Colab.ipynb` (các ô [NÂNG CẤP C], [Đo, tùy chọn], [GIAO DIỆN], [KIỂM TRA] và ô xuất [Phương án cũ 01/11]) | ghép | Ô [NÂNG CẤP C] nạp dự án từ zip và dùng đúng code phần C của web app với FinBERT đã nạp trong notebook; widget nhập `MÃ:VỐN`, nút "Xem độ phủ tin"; ô [Đo, tùy chọn] thu mọi ứng viên tin và tải kết quả về. Tin chỉ dùng lại 10 phút, ô "Lấy tin mới", khung xanh/vàng ghi giờ lấy tin (giờ Việt Nam); ô [GIAO DIỆN] chạy chính web app trong Colab; ô xuất 3 PNG của phương án cũ 01/11, ô đo độ chính xác (biểu đồ 4 và 5), ô chạy đường gọi API của bài báo qua máy chủ tự dựng (miễn phí), ô tùy chọn gọi Hugging Face thật (đọc `HF_TOKEN` từ Colab Secrets, cần credit) |

## Chạy

```powershell
# trong venv của dự án (đã cài requirements.lock.txt)
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # matplotlib + pytest
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe -m scripts.run_upgrade_demo        # tải ProsusAI/finbert như phần lõi
# kết quả: artifacts\upgrade\chart1_*.png, chart2_*.png, chart3_*.png, BANG_SO_LIEU.md, upgrade_results.json
.\.venv\Scripts\python.exe -m scripts.run_upgrade_demo --from-run artifacts\upgrade --out artifacts\upgrade_v2
# tính lại điểm, bảng, biểu đồ từ xác suất FinBERT đã lưu (khi đổi công thức), không nạp model
```

Trên Colab: chạy các ô cũ của notebook (để nạp FinBERT), rồi ô **[NÂNG CẤP C]** và ô widget ngay sau nó. Muốn xem đúng giao diện web: chạy thêm ô **[GIAO DIỆN]** (ở đầu notebook, tự hỏi zip), giao diện hiện ngay dưới ô. Ô đầu sẽ hỏi tải lên file zip dự án này; ô cuối chạy script và tải về `upgrade_results.zip`.

**Chốt chặn phiên bản model.** Bước [2/6] của script chấm lại 7 tiêu đề trong `artifacts/local_inference_api_results.json` (kết quả FinBERT revision `0bc2ac10…` đã kiểm chứng trên máy Windows). Nếu xác suất lệch quá `0.001`, script **dừng** và không vẽ biểu đồ, để số trên slide luôn khớp với model của demo. Chỉ thêm `--allow-model-mismatch` khi cố ý chạy model khác (ví dụ để thử nghiệm), và khi đó không dùng số liệu cho slide.

## Đo độ chính xác FinBERT (biểu đồ 4 và 5)

Bài báo mục 1 nói model sentiment thông thường đọc sai tin tài chính nhưng không đưa con số; README của ProsusAI/finBERT có phần dữ liệu có nhãn và `predict.py`. Script này đo con số đó:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_finbert      # cần mạng tới Hugging Face; khoảng 10 phút trên CPU (lần chạy Colab thật: 626 giây)
# kết quả: artifacts\evaluation\chart4_finbert_vs_general.png, chart5_confidence_check.png, BANG_DANH_GIA.md, evaluation_results.json, predictions.csv
.\.venv\Scripts\python.exe -m scripts.evaluate_finbert --from-run artifacts\evaluation --out artifacts\evaluation_v2
# tính lại bảng và biểu đồ từ predictions.csv của lần chạy trước, không cần model, không cần mạng
```

- Dữ liệu mặc định: tập validation của `zeroshot/twitter-financial-news-sentiment` (nhãn Bearish / Bullish / Neutral), bộ FinBERT chưa từng học. Không chấm trên Financial PhraseBank vì FinBERT đã học trên chính bộ đó. Dùng CSV khác: `--data-csv file.csv` (cột `text`, `label`).
- So sánh công bằng: model review phim chỉ có 2 nhãn, nên hai model được so trên các tin có chiều rõ (Bullish / Bearish), kèm khoảng tin cậy 95% (Wilson) và kiểm định McNemar trên cùng bộ tin. FinBERT được chấm thêm trên đủ 3 nhãn.
- Biểu đồ 5 kiểm chứng trọng số độ rõ `w_conf = |P+ − P−|` của Module 1 trên chính các tin này: chia tin theo độ rõ, xem tỷ lệ đoán đúng chiều và tỷ lệ tin thực chất trung tính ở mỗi khoảng, rồi so phần "phiếu" mà tin đúng chiều, sai chiều, trung tính nhận được khi chia đều (bài báo) và khi chia theo độ rõ (Module 1).
- `predictions.csv` có đúng các cột `predict.py` của README: câu, 3 xác suất softmax, nhãn dự đoán, điểm = P(positive) − P(negative), cộng nhãn đúng và dự đoán của model so sánh.

## Hugging Face Inference API: vì sao 402 và cách chạy thật miễn phí

Bài báo gọi FinBERT qua Hugging Face Inference API (mục 5 và 8). Hồ sơ của nhóm ghi nhận HTTP 402. Xem [trang giá hiện hành](https://huggingface.co/docs/inference-providers/pricing).

Code chạy FinBERT theo 3 cách, cùng model `ProsusAI/finbert`, revision `0bc2ac10…` được ghim cho local và máy chủ tự dựng. Router công cộng chưa xác nhận revision:

| Cách | Biến môi trường | Tốn tiền | Dùng cho |
|---|---|---|---|
| Local Transformers (mặc định) | `INFERENCE_PROVIDER=transformers-local` | Không | Mọi biểu đồ và con số |
| Adapter Hugging Face API của bài báo, gọi máy chủ tự dựng | `INFERENCE_PROVIDER=hf-inference`, `HF_INFERENCE_URL=http://127.0.0.1:8001/models/ProsusAI/finbert` | Không | Chứng minh đường gọi API chạy thật qua HTTP: gửi theo lô, đọc JSON, thử lại |
| Adapter Hugging Face API của bài báo, gọi Hugging Face thật | `INFERENCE_PROVIDER=hf-inference`, `HF_TOKEN` | Cần PRO hoặc credit | Khi nhóm có tài khoản trả phí |

Model của cả 3 cách đều tải miễn phí từ Hugging Face Hub. `HF_TOKEN` chỉ được gửi tới địa chỉ `https://…huggingface.co`, không bao giờ tới máy chủ tự dựng hay nơi khác (có kiểm thử).

Chạy đường API miễn phí trên máy (2 cửa sổ PowerShell). Trên Colab đã có ô [KIỂM TRA] làm sẵn các bước này.

```powershell
# Cửa sổ 1: máy chủ tự dựng (lần đầu tải model khoảng 438 MB)
.\.venv\Scripts\python.exe -m scripts.serve_hf_api --port 8001

# Cửa sổ 2: kiểm tra 7 tiêu đề tham chiếu qua HTTP thật
.\.venv\Scripts\python.exe -m scripts.check_hf_api --endpoint http://127.0.0.1:8001/models/ProsusAI/finbert
# kết quả: artifacts\hf_api_check\self_hosted_api_check.json

# Hoặc chạy cả web app qua đường API của bài báo
$env:INFERENCE_PROVIDER = 'hf-inference'
$env:HF_INFERENCE_URL = 'http://127.0.0.1:8001/models/ProsusAI/finbert'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
Invoke-RestMethod 'http://127.0.0.1:8001/stats'   # số request HTTP máy chủ đã nhận
```

Khi có token còn credit, gọi Hugging Face thật:

```powershell
$env:HF_TOKEN = '<token, không lưu vào file>'
.\.venv\Scripts\python.exe -m scripts.check_hf_api
# kết quả: artifacts\hf_api_check\hf_api_check.json; in ra số request HTTP, gửi theo lô có được chấp nhận không, sai khác so với FinBERT local
```

## Gọi API mới

```powershell
# Như sơ đồ mục 3 của bài báo (GET), cùng JSON với POST
Invoke-RestMethod 'http://127.0.0.1:8000/api/sentiment/stock?symbol=COMI'
Invoke-RestMethod 'http://127.0.0.1:8000/api/sentiment/portfolio?symbols=COMI,ETEL,FWRY'

# Phần C: độ phủ tin theo vốn (POST hoặc GET, cùng JSON); chi tiết trong PHAN_C_DO_PHU_TIN_VI.md
Invoke-RestMethod 'http://127.0.0.1:8000/api/v2/sentiment/portfolio/coverage?positions=COMI:50,ETEL:30,FWRY:20'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v2/coverage/config'

# Phương án cũ 01/11 (giữ để tái lập, giao diện không còn gọi)
$body = '{"positions":[{"symbol":"COMI","weight":70,"macro_beta":1.2},{"symbol":"ETEL","weight":20,"macro_beta":0.6},{"symbol":"FWRY","weight":10,"macro_beta":1.0}],"half_life_micro_hours":12,"half_life_macro_hours":24,"prior_strength":0.5}'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v2/sentiment/portfolio/weighted' -Method Post -ContentType 'application/json' -Body $body
Invoke-RestMethod 'http://127.0.0.1:8000/api/v2/cache/stats'
```

Response phân tích live thành công có `data_freshness`: `requested_at_utc`, `completed_at_utc`, `news_collection_ms`, `total_ms`; mỗi lượt thực sự nhận phản hồi HTTP có `fetched_at`, `query_url` (đã xóa khóa API), `http_status`, `elapsed_ms`. Endpoint weighted thêm `news_groups_from_cache` / `news_groups_total`, và dòng tin dùng lại có `cached: true`, giữ `fetched_at` của lần lấy thật.

Response của endpoint weighted (phương án cũ) có `article_method` (công thức của bản tái dựng), `upgraded_method` (điểm mới, điểm từng mã, đóng góp từng tin, `evidence_status` và Σw từng nhóm tin trong `evidence_by_group`), `difference`, `timing_ms` và `cache` (số tin lấy từ cache, số tin phải chấm model).

## Tham số mặc định và lý do (phương án cũ 01/11)

| Tham số | Mặc định | Vì sao |
|---|---|---|
| Chu kỳ bán rã tin riêng mã | 12 giờ | Tin doanh nghiệp được giá phản ánh trong phiên; sau 1 ngày còn 25% trọng số |
| Chu kỳ bán rã tin vĩ mô | 24 giờ | Lãi suất, lạm phát, tỷ giá tác động nhiều phiên; sau 2 ngày còn 25% |
| κ (độ hoài nghi) | 0.5 | 1 tin rõ nét tuyệt đối vừa ra chỉ được giữ 2/3 điểm; cần nhiều tin cùng chiều mới tiến gần ±1 |
| Ngưỡng "đủ tin" | Σw ≥ κ | Không thêm tham số mới: một nhóm tin (tin riêng 1 mã, hoặc tin vĩ mô khi β danh mục > 0) đủ tin khi bằng chứng nặng hơn độ hoài nghi. Không nhóm nào đủ thì nhãn là `Insufficient` (giao diện ghi "Không đủ tin"), điểm số vẫn được trả kèm `score_label` để đối chiếu |
| Tuổi tin khi thiếu ngày đăng | 48 giờ | Không thưởng cho tin không rõ ngày như thể vừa ra |
| Vùng Neutral | ±0.15 | Chỉ để gắn nhãn đọc nhanh; điểm số luôn được in kèm |
| TTL cache kết quả FinBERT | 24 giờ | Cùng model + revision + tiêu đề cho cùng xác suất; khóa chứa revision nên đổi model thì cache tự mất hiệu lực |
| TTL cache danh sách tin | 10 phút | Tin mới vẫn được lấy sau tối đa 10 phút |
