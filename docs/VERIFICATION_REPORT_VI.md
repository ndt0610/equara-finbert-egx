# Báo cáo kiểm chứng triển khai Equara AI / FinBERT

**Thời điểm ghi nhận:** 01-11-2026 (UTC trong log).  
**Mục tiêu:** tái dựng demo ứng dụng phân tích sentiment tài chính EGX theo bài viết được cung cấp, giữ nguyên repository ProsusAI/finBERT.

Bản PDF gốc không nằm tại thư mục làm việc hiện tại; phần đối chiếu được thực hiện trên các trang PNG đã render và lưu từ giai đoạn trước trong `D:\BT Thầy Hiếu\demo_artifacts\paper\page-1.png` đến `page-6.png`.

## Kết luận tóm tắt

Ứng dụng đã chạy trên localhost ở **live mode**. Kiểm thử trình duyệt thực tế xác nhận Single Stock và Portfolio hoàn tất bằng local `ProsusAI/finbert`, hiển thị headline, nguồn, trạng thái provider, ba xác suất và sentiment tổng hợp. Trong lượt web này `eodhd_token_configured=false`; EODHD bị bỏ qua và không có request EODHD. COMI có 12 headline từ RSS; portfolio năm mã có 6 headline từ RSS. RSS và số liệu có thể thay đổi theo thời điểm.

Colab Secret `EODHD_API_TOKEN` trước đó được đọc mà không in giá trị. Preflight COMI do người dùng cung cấp và bốn request portfolio mới trả HTTP 200/0; không có headline EODHD thực tế. Không gửi request EODHD macro, không retry, không nâng cấp gói và không thanh toán. Chi tiết lần kiểm tra Colab được tách riêng bên dưới để không nhầm với web demo RSS-only.

## Môi trường và tính toàn vẹn upstream

| Mục | Bằng chứng |
|---|---|
| Repository upstream | `D:\BT Thầy Hiếu\finBERT` |
| Commit | `3b4bfed383a8bb6b013db2f1ce9c766ff5100d24` |
| Source diff | `git diff --quiet HEAD --` exit 0 |
| Index diff | `git diff --cached --quiet` exit 0 |
| Status | Chỉ có các thư mục output untracked đã tồn tại: `output/`, `output_three_label/`, `output_utf8/` |
| App | `D:\BT Thầy Hiếu\equara_ai_reproduction` — thư mục riêng, nằm ngoài repo upstream |
| Python | 3.12.14; virtual environment riêng tại `D:\envs\equara_demo` |
| Dependencies | `uv pip check` — all installed packages compatible |
| Keys | Backend workspace không có `HF_TOKEN`, `HUGGINGFACEHUB_API_TOKEN`, `EODHD_API_TOKEN` hoặc `EODHD_TOKEN` trong Process/User/Machine scope. Colab đọc được Secret `EODHD_API_TOKEN`; giá trị không được đưa vào báo cáo hoặc notebook output. |

**Lưu ý bảo mật phiên này:** Trong lúc kiểm tra giao diện Colab, giá trị Secret thoáng xuất hiện trong một bản chụp accessibility của giao diện và sau đó đã được ẩn. Giá trị không được ghi vào repository hay output của notebook; hãy thu hồi và tạo lại EODHD key trước khi tiếp tục sử dụng.

## Bằng chứng thực thi

Lệnh chạy fixture server:

```powershell
$env:DEMO_MODE='fixture'
& 'D:\envs\equara_demo\Scripts\python.exe' -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Kết quả từ HTTP calls thật tới localhost:

| Kiểm tra | Kết quả |
|---|---|
| `GET /` | HTTP 200 |
| `GET /static/app.js` | HTTP 200 |
| `GET /api/health` | `status=ok`, `data_mode=fixture`, model `ProsusAI/finbert`, không có credentials |
| `GET /api/stocks` | Trả 3 mã trong bài báo: COMI, ETEL, FWRY |
| `POST /api/sentiment/stock` body `{"symbol":"COMI"}` | HTTP 200; 12 fixture headline; fixture score tổng hợp Bullish; xác suất cộng `1.0`; 0 inference HTTP calls |
| `POST /api/sentiment/portfolio` body `{"symbols":["COMI","ETEL","FWRY"]}` | HTTP 200; 10 fixture headline; 0 inference HTTP calls |
| `POST /api/sentiment/portfolio` body `{"symbols":["COMI","ETEL","FWRY","ADIB","EFIH"]}` | HTTP 200; 14 fixture headline (10 micro + 4 macro); 0 inference HTTP calls |
| Portfolio gồm hơn 5 mã | HTTP 422 |
| BBC Middle East RSS | HTTP 200; XML parse được; 23 feed entries trong lần kiểm tra |
| Google News RSS query `Egypt economy` | HTTP 200; RSS/Atom parse được; 100 entries trong lần kiểm tra |
| Live `POST /api/sentiment/stock` với COMI, không có credentials | HTTP 424 `missing_hf_token`; Google News trả 14 micro, BBC RSS trả 2 macro; sau gộp/giới hạn có 15 headline (13 micro, 2 macro); phản hồi không có trường probabilities |
| Colab EODHD News API | Secret đọc được, giá trị không xuất hiện trong log/output. COMI preflight do người dùng cung cấp: HTTP 200/0; không gửi lặp. Portfolio gửi đúng 4 request mới (`ETEL.EGX`, `FWRY.EGX`, `ADIB.EGX`, `EFIH.EGX`), mỗi mã một request; cả bốn HTTP 200/0. Tổng dữ liệu EODHD thu được: 0 headline. Không gửi general/macro request, retry hay request bổ sung. |

Số lượng feed là thời điểm kiểm tra, không phải giá trị cố định. Fixture responses đã lưu dưới `artifacts/fixture_*_result.json`; live response không có score nằm ở `artifacts/live_missing_hf_final.json`; summary cuối nằm ở `artifacts/fixture_smoke_results.json` và `artifacts/live_smoke_results_final.json`. Kết quả live của lần thử trước cũng được giữ tại `artifacts/live_missing_hf.json` và `artifacts/live_smoke_results.json`; log backend nằm ở `artifacts/backend.log`.

## Kết quả về khả năng tái hiện

| Mức | Nội dung |
|---|---|
| Đã chạy thực tế | Server FastAPI live; health/catalog; fixture flows; browser UI Single Stock và Portfolio với RSS thật + FinBERT local; UI hiển thị headline, provider status, nguồn, ba xác suất và sentiment tổng hợp |
| Đã kiểm tra dịch vụ công khai | BBC public Middle East RSS và Google News RSS trả HTTP 200; backend live parse và lọc tin từ hai RSS fallback |
| Tích hợp backend / dữ liệu provider | Backend có EODHD-first cho micro và macro cùng RSS fallback; Colab ưu tiên EODHD theo ticker. Các ticker EODHD kiểm tra trước đó trả HTTP 200/0, nên chưa có headline EODHD thực tế. Lượt browser này chủ động để trống token và chỉ dùng RSS. HTTP 200/0 không xác nhận entitlement hay có tin. HF Inference API chưa có kết quả thành công. |
| Chưa tái hiện được đúng như bài báo | Một batch HTTP request chứa tới ~15 headlines: tài liệu HF hiện hành mô tả `inputs` là string đơn. Backend gọi đúng model/provider/params nhưng một request cho mỗi headline |
| Tái dựng theo lựa chọn triển khai | Query macro EODHD/filter Egypt; fallback criteria; dedup; sorting; công thức average/label/score; giao diện browser thay cho mobile app gốc |

## Những giới hạn cần nói khi demo

1. Bài được cung cấp là bài viết mô tả kiến trúc, không cung cấp source ứng dụng Equara AI hoặc công thức sentiment aggregation.
2. Fixture headlines/probabilities được viết tĩnh chỉ để xác nhận luồng API/UI có thể phục vụ qua localhost. Chúng không đến từ feeds hoặc model và phải để nguyên badge cảnh báo.
3. Backend workspace không có API key; Colab Secret được đọc an toàn. Năm ticker được kiểm tra đều có response HTTP 200 nhưng 0 headline. Kết quả rỗng không phân biệt được feed không có tin với hạn chế quyền dữ liệu; không nâng cấp gói hoặc thanh toán.
4. HF API schema hiện tại chỉ công bố một chuỗi `inputs`; batch request chính xác như bài báo chưa được xác nhận theo schema đang công bố.
5. Browser UI đã được kiểm thử trực tiếp tại `http://127.0.0.1:8000/`; HTML, JS và CSS phục vụ thành công. Snapshot số liệu hiển thị lưu tại `artifacts/web_demo_browser_verification.json`. RSS thay đổi theo thời gian.
6. Dữ liệu news chỉ dùng tiêu đề. Kết quả sentiment không phải khuyến nghị đầu tư.

## Web demo local — kiểm chứng trình duyệt cuối

Kiểm thử ngày 01-11-2026 dùng giao diện tại `http://127.0.0.1:8000/`, Backend `live`, `transformers-local`, model `ProsusAI/finbert`, CPU. Health trả `status=ok`, `eodhd_token_configured=false`; UI cũng hiển thị rõ EODHD chưa cấu hình. Vì vậy bộ thu thập bỏ qua EODHD và chỉ lấy BBC/Google RSS. Lượt này không dùng fixture và không gọi Hugging Face Inference API.

| Luồng | Headline / inference local | Provider và số headline đưa vào model | Sentiment | Positive | Negative | Neutral | Score hiển thị |
|---|---:|---|---|---:|---:|---:|---:|
| Single Stock — COMI.EGX | 12 / 12 | Google News RSS 10; BBC RSS 2 | Neutral | 25.3% | 16.7% | 58.0% | 0.086 |
| Portfolio — COMI, ETEL, FWRY, ADIB, EFIH | 6 / 6 | Google News RSS 4; BBC RSS 2 | Neutral | 9.3% | 31.9% | 58.9% | -0.226 |

UI hiển thị cả title, source/publisher, loại micro/macro, mã chứng khoán, xác suất ba nhãn cho từng headline, xác suất tổng hợp và sentiment tổng hợp. Khối provider status báo EODHD micro/macro `skipped_missing_api_key`, Google News RSS micro có kết quả, BBC RSS macro có 2 mục và Google News macro được bỏ qua vì BBC đã có tin. Portfolio không có tin micro cho ETEL/FWRY và chỉ có 2 headline macro; kết quả có cảnh báo ngay trên trang. Số mục provider trả về trước giới hạn/dedup được ghi riêng với số headline thực sự phân tích.

Đây là snapshot của RSS tại lần chạy, không phải bộ kết quả cố định. Bằng chứng có cấu trúc: `artifacts/web_demo_browser_verification.json`. Hướng dẫn chạy lại trực tiếp: `docs/DEMO_GUIDE_VI.md`.

### Đối chiếu chức năng với bài báo

Đối chiếu theo bài viết [Building AI-Powered Financial Sentiment Analysis with Hugging Face and FinBERT](https://mohamed-hendawy.medium.com/building-ai-powered-financial-sentiment-analysis-with-hugging-face-and-finbert-92134b97295a), được tác giả trình bày như một deep dive kiến trúc.

| Mô tả trong bài báo | Bản tái dựng và kiểm chứng | Trạng thái |
|---|---|---|
| Ba tầng News Aggregation → NLP Inference → Aggregation & API; app tiêu thụ REST API | FastAPI REST, News Aggregator, local inference và aggregation; browser UI gọi REST | Đã tái dựng; UI không phải app mobile gốc |
| FinBERT `ProsusAI/finbert`, ba nhãn và softmax | Cùng model ID, inference Transformers local, ba xác suất trên từng headline và kết quả tổng hợp | Đã chạy trên local CPU; không thay model |
| News micro + macro và nhiều nguồn có fallback | EODHD ưu tiên trong notebook/backend, Google News/BBC RSS fallback theo luồng; lượt web cuối chỉ dùng RSS | Mã đã tích hợp; lần web này không gọi EODHD và các kiểm tra EODHD trước đó có 0 tin |
| Portfolio kết hợp macro news với 1–2 headline mỗi holding, tối đa 5 mã | Input năm mã, giới hạn hai micro headline mỗi mã và tối đa bốn macro; UI cho biết khi nguồn trả thiếu | Luồng đã chạy; snapshot có 6/14 headline mục tiêu do thiếu ETEL/FWRY micro và chỉ có 2 macro |
| HF Inference Provider, `top_k=3`, `function_to_apply=softmax` | Adapter HF vẫn có; web demo cuối dùng local Transformers để inference không phụ thuộc API token/credits | Khác phương thức triển khai; lần HF trước được báo HTTP 402, chưa có kết quả thành công |
| Batch HTTP request khoảng 15 headlines | Local provider nhận danh sách headlines để batch inference; adapter HF đang dùng một HTTP request cho mỗi headline theo schema API hiện hành | Chưa xác nhận được đúng batch HTTP của bài báo |
| Bài báo không nêu công thức gộp sentiment | UI dùng trung bình số học đều ba xác suất; chọn nhãn có trung bình lớn nhất và score `mean(positive)-mean(negative)` | Lựa chọn tái dựng, được gắn nhãn trên giao diện |

## Chạy lại notebook trên Colab — EODHD ưu tiên, RSS fallback

Ngày 01-11-2026, notebook `notebooks/Equara_AI_FinBERT_Colab.ipynb` được chạy trong runtime Google Colab CPU thật. Model là `ProsusAI/finbert`, revision `0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031`; inference dùng Transformers/PyTorch local và giữ nguyên tokenization, truncation, batching và softmax đã kiểm thử. Không chỉnh sửa repository FinBERT gốc, không dùng fixture và không gọi Hugging Face Inference API.

**Tích hợp đã chạy:** Colab đọc Secret an toàn; EODHD được thử trước cho ticker; response rỗng/lỗi rơi về Google News RSS; BBC RSS cung cấp macro news, với Google News RSS fallback khi BBC rỗng. Cache runtime ngăn request lặp. COMI HTTP 200/0 là kết quả preflight do người dùng cung cấp và được tái sử dụng. Lượt Portfolio mới gửi đúng bốn request, mỗi mã ETEL/FWRY/ADIB/EFIH một lần; tất cả trả HTTP 200/0. Không gọi EODHD general/macro.


| Ticker | EODHD News status | Headline EODHD | Request trong lượt này |
|---|---|---:|---:|
| COMI.EGX | HTTP 200, danh sách rỗng (preflight người dùng cung cấp) | 0 | 0 |
| ETEL.EGX | HTTP 200, danh sách rỗng | 0 | 1 |
| FWRY.EGX | HTTP 200, danh sách rỗng | 0 | 1 |
| ADIB.EGX | HTTP 200, danh sách rỗng | 0 | 1 |
| EFIH.EGX | HTTP 200, danh sách rỗng | 0 | 1 |

| Phạm vi | Trạng thái provider | Headline thực sự phân tích | Nhãn | Positive | Negative | Neutral | Score |
|---|---|---|---|---:|---:|---:|---:|
| COMI | EODHD 0 (preflight 200/0, cache); Google News RSS 9; BBC RSS 2 | 11 | Neutral | 0.273267 | 0.179503 | 0.547230 | 0.093763 |
| COMI, ETEL, FWRY, ADIB, EFIH | EODHD: COMI dùng cache, bốn mã mới đều 200/0; Google News RSS 6; BBC RSS 2; macro Google News bỏ qua vì BBC có tin | 8 | Neutral | 0.181245 | 0.243448 | 0.575306 | -0.062203 |

Trong Portfolio, headline micro được đưa vào model theo mã: COMI 2, ETEL 2, FWRY 0, ADIB 1, EFIH 1; BBC macro 2. Google News RSS không trả headline cho FWRY. Hai bảng sentiment dùng headline thật từ RSS; EODHD đóng góp **0 headline**. `HTTP 200/0` cho biết request được phản hồi thành công nhưng không chứng minh có dữ liệu cho ticker. Không có bằng chứng để xác định response rỗng do feed hay entitlement tài khoản.

Provider status, nguồn/publisher, số headline và ba xác suất từng headline được hiển thị inline trong Colab. COMI chưa đạt mục tiêu 10–15 headline; Portfolio có 8/14 tối đa và thiếu tin gần đây cho FWRY, BBC có 2/4 macro mục tiêu. Nguồn thưa ảnh hưởng độ đại diện sentiment.

Notebook đọc token bằng `google.colab.userdata`; giá trị không được in. Đã có cảnh báo ở trên về một lần lộ Secret trong accessibility snapshot; cần thu hồi/tạo lại key nếu chưa được xoay vòng. Không gửi thêm request để tránh hao hạn mức.

Hướng dẫn mở và chạy: `docs/COLAB_DEMO_GUIDE_VI.md`. Notebook: `notebooks/Equara_AI_FinBERT_Colab.ipynb`.

## Phán định

**FastAPI/backend:** live UI Single Stock và Portfolio đã chạy trên browser bằng RSS thật và local Transformers. UI thể hiện title, nguồn, count/status provider, ba xác suất từng headline và xác suất tổng hợp. EODHD token bị bỏ trống có chủ đích nên không phát sinh request trong lần demo này. EODHD-first/fallback đã được kiểm chứng riêng trên Colab, nhưng dữ liệu EODHD nhận được bằng 0. Một lượt thử Hugging Face Inference API trước đó được báo trả HTTP 402; chưa có kết quả thành công.

**Notebook Colab:** đúng model `ProsusAI/finbert` chạy local trên CPU cho COMI và danh mục năm mã. EODHD-priority/fallback đã chạy; cả COMI preflight và bốn mã portfolio đều HTTP 200/0, nên hai kết quả dùng Google News RSS/BBC RSS. Bốn request mới là giới hạn kiểm chứng; không gọi EODHD macro. Không chỉnh sửa repository FinBERT gốc. Xem `docs/COLAB_DEMO_GUIDE_VI.md`.

Tài liệu EODHD đối chiếu: [Financial News API](https://eodhd.com/financial-apis/stock-market-financial-news-api), [pricing](https://eodhd.com/pricing), [API limits](https://eodhd.com/financial-apis/api-limits), [EGX active tickers](https://eodhd.com/exchange/EGX) ([page 2](https://eodhd.com/exchange/EGX?page=2)).
