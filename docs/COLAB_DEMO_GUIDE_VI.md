# Hướng dẫn demo FinBERT local trên Google Colab

## Notebook và inference

Notebook `notebooks/Equara_AI_FinBERT_Colab.ipynb` là demo độc lập cho Equara AI. Nó tải đúng model `ProsusAI/finbert` qua Transformers, khóa tại revision `0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031`, rồi chạy inference bằng PyTorch trong runtime Colab. Không gọi Hugging Face Inference API, không dùng fixture, không sửa repository gốc ProsusAI/finBERT, và giữ nguyên phương pháp inference đã kiểm thử.

Notebook đọc `EODHD_API_TOKEN` từ Colab Secrets bằng `google.colab.userdata`. Chỉ cờ có/không được in; token không được in ra cell output. Backend FastAPI là luồng riêng và đọc token từ process environment.

## Mở và chạy

1. Mở notebook bằng Google Colab, chọn **File → Upload notebook**.
2. Chọn **Runtime → Change runtime type → CPU**; GPU là tùy chọn.
3. Trong **Secrets**, lưu key với tên `EODHD_API_TOKEN` và bật notebook access.
4. Chạy cell cài đặt, cấu hình và tải model. Lần đầu tải khoảng 438 MB weights công khai từ Hugging Face Hub.
5. Dùng **Analyze stock** cho một mã như `COMI`; dùng **Analyze portfolio** cho tối đa năm mã, ví dụ `COMI, ETEL, FWRY, ADIB, EFIH`.
6. Đầu mỗi kết quả có khung xanh **"Tin lấy trực tiếp từ internet lúc … (giờ Việt Nam)"** khi vừa gọi nguồn tin, hoặc khung vàng **"Dùng lại tin đã lấy lúc … (X phút trước)"** khi dùng lại tin trong 10 phút. Tick ô **"Lấy tin mới"** để bỏ qua tin đã lấy. Muốn xem đúng giao diện web, chạy ô **[GIAO DIỆN]** ở đầu notebook, tự hỏi ZIP.
7. Notebook hiển thị số headline thực sự được phân tích theo provider, trạng thái mỗi provider, publisher/source, headline, nhãn và xác suất Positive/Negative/Neutral từng headline cùng xác suất tổng hợp.
8. Phần C (độ phủ tin theo vốn): chạy ô **[NÂNG CẤP C]** (tự hỏi ZIP dự án nếu chưa nạp), rồi ô widget ngay sau, nhập danh mục dạng `COMI:50, ETEL:30, FWRY:20` và bấm **Xem độ phủ tin**. Ô này dùng đúng code của web app và FinBERT đã nạp ở các ô trên. Cách đọc kết quả trong `docs/PHAN_C_DO_PHU_TIN_VI.md`.

## EODHD và fallback

EODHD được ưu tiên cho tin micro theo ticker. HTTP 200 nhưng danh sách rỗng được báo là `empty:0`, không được tính thành tin EODHD. Khi EODHD rỗng/lỗi, Google News RSS là fallback cho tin theo mã. Macro news trong Colab dùng BBC RSS, rồi Google News RSS nếu BBC không có tin phù hợp. Tin đã lấy cho cùng ticker/feed được dùng lại tối đa 10 phút giữa Single Stock và Portfolio (trước bản cập nhật 02-11-2026 là suốt runtime); quá 10 phút hoặc tick "Lấy tin mới" thì gọi lại nguồn.

Người dùng đã kiểm tra `COMI.EGX` trước lượt chạy hiện tại: HTTP 200, `NEWS_API_SUCCESS=True`, `NEWS_COUNT=0`. Kết quả này được tái sử dụng, không gửi lại request COMI. Trong lượt Portfolio, notebook gửi đúng một request cho từng mã còn lại `ETEL.EGX`, `FWRY.EGX`, `ADIB.EGX`, `EFIH.EGX`; cả bốn trả HTTP 200 và 0 headline. Không gửi request EODHD general/macro. Như vậy, bốn request EODHD mới đã được thực hiện trong lượt Portfolio; Single Stock không tạo thêm request EODHD.

HTTP 200 xác nhận endpoint đã trả lời request, nhưng số headline EODHD thực tế cho cả năm mã trong lượt kiểm chứng là **0**. Không thể kết luận nguyên nhân là thiếu tin trong feed hay entitlement của tài khoản. Tin sentiment dưới đây đến từ RSS thật, không có dữ liệu EODHD giả lập. Không nâng cấp gói hoặc thực hiện thanh toán.

## Kết quả chạy Colab thật — 01-11-2026

| Phạm vi | EODHD | Google News RSS | BBC RSS | Tổng headline | Sentiment | Positive | Negative | Neutral | Score |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| COMI.EGX | 0 (preflight HTTP 200/0 được tái sử dụng) | 9 | 2 | 11 | Neutral | 0.273267 | 0.179503 | 0.547230 | 0.093763 |
| COMI, ETEL, FWRY, ADIB, EFIH | 0; bốn request mới HTTP 200/0 | 6 | 2 | 8 | Neutral | 0.181245 | 0.243448 | 0.575306 | -0.062203 |

Trong Portfolio, micro headlines thực sự đưa vào model: COMI 2, ETEL 2, FWRY 0, ADIB 1, EFIH 1; BBC macro 2. EODHD không đóng góp headline. Provider status vẫn ghi riêng response/status từng mã; do giới hạn 2 micro headline mỗi mã, số COMI được đưa vào Portfolio là 2 dù cache Single Stock có 9 Google News headline.

Hai lần phân tích dùng model `ProsusAI/finbert` local trên CPU, không gọi HF Inference API, không dùng fixture. Sentiment là phân loại headline, không phải khuyến nghị đầu tư. BBC có thể chứa tin xã hội/chính trị không phản ánh riêng biến động cổ phiếu.

## Giới hạn

- RSS có thể ít, cũ, trùng hoặc không chuyên về thị trường; bài quá 90 ngày bị loại.
- Mỗi ticker được request EODHD tối đa một lần mỗi 10 phút (hoặc khi tick "Lấy tin mới"); reset runtime xóa cache.
- Tài khoản/API response rỗng không phải bằng chứng EODHD có tin.
- Colab reset runtime có thể yêu cầu tải model weights lại.

Tham khảo: [EODHD Financial News API](https://eodhd.com/financial-apis/stock-market-financial-news-api), [EODHD pricing](https://eodhd.com/pricing), [API limits](https://eodhd.com/financial-apis/api-limits), [EGX active tickers](https://eodhd.com/exchange/EGX) ([page 2](https://eodhd.com/exchange/EGX?page=2)).
