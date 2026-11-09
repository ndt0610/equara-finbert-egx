const $ = (selector) => document.querySelector(selector);
const stockTab = $("#stockTab");
const portfolioTab = $("#portfolioTab");
const stockPanel = $("#stockPanel");
const portfolioPanel = $("#portfolioPanel");
const resultPanel = $("#result");
const modeBadge = $("#modeBadge");
const modeNotice = $("#modeNotice");
const inferenceFlowDetail = $("#inferenceFlowDetail");
const newsFlowDetail = $("#newsFlowDetail");

function setModeBadge(health) {
  const provider = health.inference_provider || "hf-inference";
  modeBadge.className = `mode-badge ${health.data_mode === "fixture" ? "mode-fixture" : "mode-live"}`;
  modeBadge.textContent = health.data_mode === "fixture" ? "Dữ liệu minh họa" : "Dữ liệu thật";
  if (health.data_mode === "fixture") {
    modeNotice.textContent = "ĐANG DÙNG DỮ LIỆU FIXTURE: tiêu đề và xác suất chỉ để kiểm tra giao diện/luồng API; không có tin thật, không gọi EODHD hoặc FinBERT.";
    modeNotice.className = "notice";
    inferenceFlowDetail.textContent = "fixture · không gọi model";
    newsFlowDetail.textContent = "Fixture · không gọi nguồn tin";
  } else if (provider === "transformers-local") {
    const device = health.inference_device || "cpu";
    const newsProviderNote = health.eodhd_news_token_configured
      ? "EODHD News được thử trước; RSS bổ sung nếu không có tin phù hợp."
      : "Chưa cấu hình EODHD News; dùng RSS.";
    modeNotice.textContent = `Tin và FinBERT chạy trên máy này (${device}). ${newsProviderNote} FinBERT chấm tiêu đề; không lấy điểm sentiment dựng sẵn của EODHD.`;
    modeNotice.className = "notice live-note";
    inferenceFlowDetail.textContent = `Transformers local · ${device}`;
    newsFlowDetail.textContent = health.eodhd_news_token_configured
      ? "EODHD News · RSS bổ sung"
      : "BBC/Google RSS · EODHD News chưa cấu hình";
  } else if (!health.hf_token_configured) {
    modeNotice.textContent = "Live mode đang hoạt động nhưng chưa có HF_TOKEN. Tin có thể được lấy từ RSS; FinBERT inference sẽ dừng với thông báo cấu hình thay vì tạo kết quả thay thế.";
    modeNotice.className = "notice live-note";
    inferenceFlowDetail.textContent = "Hugging Face Inference API";
    newsFlowDetail.textContent = health.eodhd_news_token_configured
      ? "EODHD News · RSS bổ sung"
      : "BBC/Google RSS · EODHD News chưa cấu hình";
  } else {
    modeNotice.textContent = "Live mode: backend gọi nguồn tin và Hugging Face Inference API theo cấu hình hiện tại.";
    modeNotice.className = "notice live-note";
    inferenceFlowDetail.textContent = "Hugging Face Inference API";
    newsFlowDetail.textContent = health.eodhd_news_token_configured
      ? "EODHD News · RSS bổ sung"
      : "BBC/Google RSS · EODHD News chưa cấu hình";
  }
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    setModeBadge(health);
  } catch (_) {
    modeBadge.textContent = "Backend chưa sẵn sàng";
    modeBadge.className = "mode-badge mode-fixture";
    modeNotice.textContent = "Không kết nối được Backend API. Kiểm tra tiến trình Uvicorn.";
    modeNotice.className = "notice";
    newsFlowDetail.textContent = "Backend chưa có trạng thái provider";
  }
}

// Bốn khu vực phân tích độc lập; tab Tin + Giá không đổi logic ba tab C3.
const weightedTab = $("#weightedTab");
const weightedPanel = $("#weightedPanel");
const tinGiaTab = $("#tinGiaTab");
const tinGiaPanel = $("#tinGiaPanel");
const TABS = {
  stock: [stockTab, stockPanel],
  portfolio: [portfolioTab, portfolioPanel],
  weighted: [weightedTab, weightedPanel],
  tinGia: [tinGiaTab, tinGiaPanel],
};

function activateTab(tab) {
  for (const [name, [button, panel]] of Object.entries(TABS)) {
    const active = name === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    panel.classList.toggle("hidden", !active);
  }
  resultPanel.classList.add("hidden");
}

stockTab.addEventListener("click", () => activateTab("stock"));
portfolioTab.addEventListener("click", () => activateTab("portfolio"));
weightedTab.addEventListener("click", () => activateTab("weighted"));
tinGiaTab.addEventListener("click", () => { activateTab("tinGia"); renderTinGiaMarketView(); });

function renderTinGiaMarketView() {
  const host = $("#tinGiaMarketView");
  const symbol = $("#tinGiaSymbol").value.trim().toUpperCase().replace(/\.EGX$/, "");
  if (!/^[A-Z0-9]{2,8}$/.test(symbol)) {
    host.replaceChildren(node("p", "tg-card-note", "Nhập mã EGX hợp lệ để xem biểu đồ."));
    delete host.dataset.symbol;
    return;
  }
  if (host.dataset.symbol === symbol) return;
  host.dataset.symbol = symbol;
  host.replaceChildren(node("h3", "", `${symbol} · Giá và biểu đồ thị trường`));
  host.append(node("p", "tg-card-note", "Nguồn TradingView · dữ liệu EGX trễ. Giá, % thay đổi và thời điểm do nguồn hiển thị trong khung. Khung này phục vụ quan sát; backend chưa nhận chuỗi giá từ đây để tính nhãn hoặc mức thay đổi 5 phiên."));
  const wrap = node("div", "tradingview-widget-container tg-market-widget");
  wrap.append(node("div", "tradingview-widget-container__widget"));
  const credit = node("div", "tradingview-widget-copyright");
  credit.append(safeLink(`https://www.tradingview.com/symbols/EGX-${symbol}/`, `${symbol} chart by TradingView ↗`));
  wrap.append(credit);
  const script = document.createElement("script");
  script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
  script.async = true;
  script.textContent = JSON.stringify({autosize:true,symbol:`EGX:${symbol}`,interval:"D",timezone:"Africa/Cairo",theme:"light",style:"1",locale:"en",allow_symbol_change:false,hide_side_toolbar:true,hide_top_toolbar:false,hide_legend:false,hide_volume:false,withdateranges:true,save_image:false,calendar:false,details:false});
  script.onerror = () => host.append(node("p", "tg-card-note", "Không tải được khung TradingView. Mở liên kết nguồn để xem trạng thái; ứng dụng chưa nhận được giá qua API."));
  wrap.append(script);
  host.append(wrap);
}

$("#tinGiaSymbol").addEventListener("change", renderTinGiaMarketView);

function percent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showLoading(message) {
  resultPanel.classList.remove("hidden");
  resultPanel.replaceChildren(node("div", "loading-box", message));
}

function addHeadlines(items, analyzed, headingText = "Tiêu đề tin tức") {
  if (!items || items.length === 0) return;
  const titleRow = node("div", "section-title");
  titleRow.append(node("h3", "", headingText));
  titleRow.append(node("span", "", `${items.length} tiêu đề`));
  resultPanel.append(titleRow);

  const list = node("div", "headline-list");
  for (const item of items) {
    const card = node("article", "headline");
    const main = document.createElement("div");
    const title = node("div", "headline-title");
    title.append(safeLink(item.url, item.title) || item.title);
    main.append(title);
    const meta = node("div", "headline-meta");
    meta.append(node("span", "time-chip", item.published_at ? `Đăng ${formatClock(item.published_at)} · ${formatAge(item.published_at)}` : "Nguồn không ghi ngày đăng"));
    meta.append(node("span", "source-chip", item.source || "News source"));
    meta.append(node("span", "kind-chip", item.kind === "macro" ? "Vĩ mô" : "Doanh nghiệp"));
    if (item.symbol) meta.append(node("span", "kind-chip", item.symbol));
    if (analyzed && item.predicted_label) meta.append(node("span", "prediction-chip", sentimentLabelVi(item.predicted_label)));
    main.append(meta);
    if (analyzed && item.probabilities) {
      const scores = node("div", "headline-scores");
      scores.textContent = `Tích cực ${percent(item.probabilities.positive)} · Tiêu cực ${percent(item.probabilities.negative)} · Trung tính ${percent(item.probabilities.neutral)}`;
      main.append(scores);
    }
    card.append(main);

    if (item.url && /^https:\/\//i.test(item.url)) {
      const link = node("a", "", "Nguồn ↗");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
    }
    list.append(card);
  }
  resultPanel.append(list);
}

function addProbabilities(probabilities) {
  const grid = node("div", "probability-grid");
  for (const [key, label] of [["positive", "Tích cực"], ["negative", "Tiêu cực"], ["neutral", "Trung tính"]]) {
    const value = Math.max(0, Math.min(1, Number(probabilities[key] || 0)));
    const card = node("div", `probability-card ${key}`);
    const top = node("div", "probability-top");
    top.append(node("span", "", label));
    top.append(node("span", "probability-value", percent(value)));
    card.append(top);
    const track = node("div", "bar-track");
    const fill = node("div", "bar-fill");
    fill.style.width = percent(value);
    track.append(fill);
    card.append(track);
    grid.append(card);
  }
  resultPanel.append(node("h3", "article-probability-title", "Xác suất FinBERT trung bình"), grid);
}

function sentimentLabelVi(label) {
  return ({
    Bullish: "Nghiêng tích cực",
    Bearish: "Nghiêng tiêu cực",
    Neutral: "Trung tính",
    Positive: "Tích cực",
    Negative: "Tiêu cực",
  })[label] || label || "Chưa có nhãn";
}

// [HOÀN THIỆN] Hiện rõ dữ liệu lấy trực tiếp: giờ gọi nguồn tin, địa chỉ đã gọi, tuổi từng tin.
function formatClock(iso, withDate = true) {
  const moment = new Date(iso);
  if (!iso || Number.isNaN(moment.getTime())) return "—";
  const options = { hour: "2-digit", minute: "2-digit", second: "2-digit" };
  if (withDate) Object.assign(options, { day: "2-digit", month: "2-digit", year: "numeric" });
  return moment.toLocaleString("vi-VN", options);
}

function formatAge(iso) {
  const moment = new Date(iso);
  if (!iso || Number.isNaN(moment.getTime())) return "không rõ ngày đăng";
  const minutes = Math.max(0, Math.round((Date.now() - moment.getTime()) / 60000));
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} giờ trước`;
  return `${Math.round(hours / 24)} ngày trước`;
}

function seconds(ms) {
  return `${(Number(ms || 0) / 1000).toLocaleString("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} giây`;
}

function safeLink(url, text) {
  if (!url || !/^https?:\/\//i.test(url)) return null;
  const link = node("a", "", text);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function addFreshness(data, providers) {
  const freshness = data.data_freshness;
  const box = node("section", "freshness");
  if (!freshness) {
    box.classList.add("freshness-fixture");
    box.append(node("strong", "", "Dữ liệu minh họa (fixture), không phải tin thật"));
    box.append(node("span", "", "Không gọi nguồn tin nào. Chỉ dùng để kiểm tra giao diện."));
    resultPanel.append(box);
    return;
  }
  const calls = (providers || []).filter((row) => row.fetched_at);
  const fresh = calls.filter((row) => !row.cached);
  const reused = calls.filter((row) => row.cached);
  box.classList.add(fresh.length ? "freshness-live" : "freshness-cached");
  if (fresh.length) {
    box.append(node("strong", "", `Tin lấy trực tiếp từ internet lúc ${formatClock(freshness.requested_at_utc)}`));
    box.append(node("span", "", `${fresh.length} lượt gọi nguồn tin vừa chạy, chờ tổng cộng ${seconds(freshness.news_collection_ms)}. Bấm "Mở ↗" ở bảng dưới để tự kiểm tra từng truy vấn.`));
  } else {
    const oldest = reused.map((row) => row.fetched_at).sort()[0];
    box.append(node("strong", "", `Dùng lại tin đã lấy lúc ${formatClock(oldest)} (${formatAge(oldest)})`));
  }
  if (reused.length) {
    box.append(node("span", "", `${reused.length} lượt dùng lại tin đã lấy trước đó. ${freshness.news_cache || ""}`));
  } else if (freshness.news_cache) {
    box.append(node("span", "", freshness.news_cache));
  }
  box.append(node("span", "freshness-foot", `Hoàn tất lúc ${formatClock(freshness.completed_at_utc, false)} · tổng ${seconds(freshness.total_ms)} · giờ theo máy của bạn`));
  resultPanel.append(box);
}

function providerStatusLabel(status) {
  const reused = status.match(/^cache_hit\((.*)\)$/);
  if (reused) return reused[1].startsWith("skipped_") ? providerStatusLabel(reused[1]) : `dùng lại · ${providerStatusLabel(reused[1])}`;
  if (status === "skipped_missing_api_key") return "bỏ qua · chưa cấu hình API key";
  if (status === "failed") return "lỗi truy vấn";
  if (status.startsWith("stale:")) return `đã loại ${status.slice(6)} tin quá 90 ngày`;
  if (status === "empty:0") return "đã phản hồi · 0 tiêu đề";
  if (status === "skipped_eodhd_nonempty") return "bỏ qua · EODHD đã có tin";
  if (status === "skipped_bbc_rss_nonempty") return "bỏ qua · BBC RSS đã có tin";
  if (status === "skipped_eodhd_general_news_+_egypt_filter_nonempty") return "bỏ qua · EODHD đã có tin";
  const candidates = status.match(/^candidates:(\d+)$/);
  if (candidates) return `trả về ${candidates[1]} ứng viên (trước khi lọc)`;
  if (status === "skipped_eodhd_has_relevant") return "bỏ qua · EODHD đã có tin phù hợp";
  if (status === "skipped_enough_relevant") return "bỏ qua · đã đủ tin phù hợp";
  if (status === "skipped_enough_economic") return "bỏ qua · đã đủ tin kinh tế";
  if (status === "skipped_google_macro_already_called") return "bỏ qua · truy vấn Google vĩ mô đã gọi ở trên";
  const used = status.match(/^(?:used|ok):(\d+)$/);
  if (used) return `trả về ${used[1]} mục nguồn`;
  if (status.startsWith("skipped_")) return `bỏ qua · ${status.slice(8).replaceAll("_", " ")}`;
  return status;
}

function addProviderSummary(data) {
  const section = node("details", "provider-summary");
  const sourceCounts = new Map();
  for (const item of data.headlines || []) {
    const source = item.source || "News source";
    sourceCounts.set(source, (sourceCounts.get(source) || 0) + 1);
  }
  const summaryText = sourceCounts.size
    ? `Nguồn của tiêu đề · ${[...sourceCounts].map(([source, count]) => `${source} ${count}`).join(" · ")} · xem nhật ký`
    : "Nguồn tin và nhật ký truy vấn · không có tiêu đề";
  section.append(node("summary", "provider-summary-title", summaryText));
  const sources = node("div", "provider-summary-block");
  sources.append(node("strong", "", "Tin được phân tích"));
  if (sourceCounts.size) {
    for (const [source, count] of sourceCounts) {
      sources.append(node("span", "provider-chip", `${source}: ${count}`));
    }
  } else {
    sources.append(node("span", "provider-chip", "Không có tiêu đề được chấm"));
  }
  section.append(sources);

  const rows = (data.providers || []).map((row) => [
    row.provider,
    row.kind === "macro" ? "Vĩ mô Ai Cập" : `Tin riêng ${shortSymbol(row.symbol)}${row.tier === 2 ? " · truy vấn bậc 2" : ""}`,
    `${providerStatusLabel(row.status)}${row.http_status ? ` · HTTP ${row.http_status}` : ""}`,
    row.fetched_at ? formatClock(row.fetched_at, false) : "không gọi",
    row.elapsed_ms !== undefined ? `${row.elapsed_ms} ms` : "—",
    safeLink(row.query_url, "Mở ↗") || "—",
  ]);
  const statuses = node("div", "provider-summary-block");
  statuses.append(node("strong", "", "Từng lượt gọi nguồn tin"));
  section.append(statuses);
  if (rows.length) {
    section.append(table(["Nguồn", "Nhóm tin", "Kết quả", "Gọi lúc", "Chờ", "Truy vấn"], rows, "data-table provider-table"));
  } else {
    statuses.append(node("span", "provider-status-chip", "Backend không trả trạng thái provider."));
  }
  resultPanel.append(section);
}

function renderSuccessfulResult(data) {
  resultPanel.replaceChildren();
  const localInference = data.inference.provider === "transformers-local";
  const inferenceSummary = localInference
    ? `${data.inference_item_count ?? data.news_count} tiêu đề được FinBERT chấm trên máy này`
    : `${data.inference_http_requests} lượt gọi mô hình FinBERT`;
  const head = node("div", "result-head");
  const titleBlock = document.createElement("div");
  titleBlock.append(node("div", "result-kicker", data.scope === "portfolio" ? "Bản tái dựng bài báo · danh mục" : "Bản tái dựng bài báo · một mã"));
  titleBlock.append(node("h2", "", data.symbols.join(" · ")));
  titleBlock.append(node("p", "result-subtitle", `${data.news_count} tiêu đề · ${inferenceSummary}`));
  head.append(titleBlock);
  const pill = node("span", "sentiment-pill sentiment-neutral", sentimentLabelVi(data.sentiment));
  head.append(pill);
  resultPanel.append(head);
  if (data.scope !== "portfolio") addFreshness(data, data.providers);

  const score = Number(data.score);
  const scoreCard = node("section", "article-score-card");
  const scoreHeading = node("div", "article-score-heading");
  scoreHeading.append(
    node("div", "result-kicker", "Điểm sắc thái của tiêu đề"),
    node("strong", "article-score-value", signed(score, 3)),
  );
  scoreCard.append(scoreHeading);
  const rail = node("div", "article-score-rail");
  rail.setAttribute("role", "img");
  rail.setAttribute("aria-label", `Điểm sắc thái ${signed(score, 3)} trên thang từ -1 tiêu cực đến +1 tích cực; 0 là cân bằng`);
  const marker = node("span", "article-score-marker");
  marker.style.left = `${((Math.max(-1, Math.min(1, score)) + 1) / 2) * 100}%`;
  rail.append(node("span", "article-score-zero"), marker);
  const scale = node("div", "article-score-scale");
  scale.append(node("span", "", "−1 · nghiêng tiêu cực"), node("span", "", "0 · cân bằng"), node("span", "", "+1 · nghiêng tích cực"));
  scoreCard.append(rail, scale);
  scoreCard.append(node("p", "article-score-explain", "Công thức tái dựng: S = trung bình P(tích cực) − P(tiêu cực) trên các tiêu đề được chấm; mỗi tiêu đề có trọng số bằng nhau."));
  scoreCard.append(node("p", "article-score-limit", "Đây là sắc thái ngôn ngữ của các tiêu đề đã thu thập, không phải phần trăm thay đổi giá, lợi suất dự kiến hay khuyến nghị đầu tư."));
  resultPanel.append(scoreCard);
  addProbabilities(data.probabilities);
  const method = foldout("Cách gộp và giới hạn của bản tái dựng");
  method.append(node("p", "", "Bài báo không công bố đầy đủ công thức gộp xác suất thành một điểm danh mục. Bản tái dựng này dùng trung bình cộng xác suất của các tiêu đề; với danh mục, mỗi tiêu đề là một phiếu như mô tả trong phần lựa chọn tin."));
  method.append(node("p", "", `Nhãn “${sentimentLabelVi(data.sentiment)}” là lớp có xác suất trung bình cao nhất; nếu không có lớp duy nhất cao nhất thì nhãn là trung tính. Mô hình: ${data.inference.model}; cách chạy: ${data.inference.provider}${data.inference.device ? ` · ${data.inference.device}` : ""}.`));
  for (const warning of data.warnings || []) method.append(node("p", "", warning));
  resultPanel.append(method);
  addProviderSummary(data);
  addHeadlines(data.headlines, true, "Các tiêu đề đã được chấm");
  resultPanel.classList.remove("hidden");
}

function renderError(payload) {
  resultPanel.replaceChildren();
  const error = payload.error || {};
  const box = node("div", "error-box");
  box.append(node("strong", "", error.code || "request_failed"));
  box.append(node("span", "", error.message || "Yêu cầu không thành công."));
  resultPanel.append(box);
  const context = error.context || {};
  if (context.analysis_status === "blocked_before_inference") {
    resultPanel.append(node("p", "method-note", `Đã thu thập ${context.news_count} tiêu đề thật. Chưa có xác suất sentiment vì chưa chạy FinBERT.`));
    addHeadlines(context.headlines, false);
  }
  resultPanel.classList.remove("hidden");
}

async function submitAnalysis(url, body, button, render = renderSuccessfulResult) {
  button.disabled = true;
  showLoading("Đang gửi yêu cầu tới Backend API…");
  try {
    const response = await fetch(url, body === null ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) renderError(data);
    else render(data);
  } catch (_) {
    renderError({ error: { code: "network_error", message: "Không nhận được phản hồi từ Backend API." } });
  } finally {
    button.disabled = false;
  }
}

$("#stockForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const symbol = $("#stockSymbol").value.trim().toUpperCase();
  const query = new URLSearchParams({ symbol });
  submitAnalysis(`/api/sentiment/stock?${query}`, null, event.submitter);
});

$("#portfolioForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const symbols = $("#portfolioSymbols").value.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean);
  const query = new URLSearchParams({ symbols: symbols.join(",") });
  useOriginalPortfolio(symbols, event.submitter, renderOriginalPortfolio);
});

// ---------------------------------------------------------------------------
// Hàm dùng chung cho bảng và số có dấu.
// ---------------------------------------------------------------------------
function signed(value, digits = 3) {
  const number = Number(value);
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function shortSymbol(symbol) {
  return symbol ? symbol.replace(/\.EGX$/, "") : "Vĩ mô";
}

function table(headers, rows, className = "data-table") {
  const wrap = node("div", "table-wrap");
  const element = node("table", className);
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const header of headers) headRow.append(node("th", "", header));
  head.append(headRow);
  element.append(head);
  const body = document.createElement("tbody");
  for (const cells of rows) {
    const tr = document.createElement("tr");
    for (const cell of cells) {
      const td = node("td", "");
      if (cell instanceof Node) td.append(cell);
      else td.textContent = cell;
      tr.append(td);
    }
    body.append(tr);
  }
  element.append(body);
  wrap.append(element);
  return wrap;
}

// ---------------------------------------------------------------------------
// [NÂNG CẤP C] Tab "Danh mục theo vốn", giao diện C3. Chỉ đổi cách hiển thị: mọi số lấy từ JSON của backend.
//   1. Tóm tắt: điểm S, phần vốn có tin, số tiêu đề được chấm, LIVE/FIXTURE và giờ lấy tin.
//   2. Biểu đồ chính: đóng góp của từng mã vào S (r_i × s_i), mã không tìm thấy tin để xám, không vẽ thành 0.
//   3. Liệt kê mã được tính và mã chưa có dữ liệu, không suy diễn điểm ngoài tập tin đã chấm.
//   4. Tin vĩ mô, cách bài báo, nhãn FinBERT, phép tính tay, nguồn tin: vào mục tham khảo và chi tiết.
//   6. Bản 3: phễu đếm từng mã (ứng viên → tự động loại → qua luật → được chấm / ngoài giới hạn), danh sách bản ghi
//      bị loại theo lý do đầu tiên kèm dấu hiệu phụ, và khối "Khớp tên theo bộ lọc Tab 1–2" để đối chiếu.
//      Giao diện không đổi quyết định lọc: mọi số đếm lấy từ JSON.
//   5. So hai danh mục A/B: MỘT lần gọi API cho mọi mã của A và B, nên A và B dùng cùng một lô tiêu đề.
//      S của A và B tính lại ở trình duyệt theo đúng công thức của backend/upgrades/coverage.py,
//      rồi đối chiếu S và phạm vi vốn của A với số backend trả về. Lệch thì không hiện phần so sánh.
// ---------------------------------------------------------------------------
// "Không có tiêu đề qua luật hiện tại": truy vấn của phần C không thấy tiêu đề nào qua luật, không có nghĩa là công ty không có tin.
const NO_NEWS_LABEL = "Không có tiêu đề qua luật hiện tại";
const NO_SCORE_TEXT = "chưa có điểm · không tính vào S";
const MINUS = "−";
const MATCH_TOLERANCE = 1e-9;
const COVERAGE_URL = "/api/v2/sentiment/portfolio/coverage";

// ---------- Số kiểu Việt Nam: dấu phẩy thập phân, dấu trừ "−". Chỉ dùng ở tab này; tab 1–2 giữ nguyên. ----------
function viDigits(value, digits) {
  return Math.abs(Number(value)).toFixed(digits).replace(".", ",");
}

function vSigned(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  let shown = digits;
  // Số khác 0 mà làm tròn ra 0,00 thì hiện thêm chữ số (tối đa 4), để không mất dấu.
  while (shown < 4 && number !== 0 && Number(Math.abs(number).toFixed(shown)) === 0) shown += 1;
  const sign = Number(Math.abs(number).toFixed(shown)) === 0 ? "" : number > 0 ? "+" : MINUS;
  return `${sign}${viDigits(number, shown)}`;
}

function vPct(value, digits = null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value) * 100;
  const shown = digits ?? (Math.abs(number - Math.round(number)) < 1e-9 ? 0 : 1);
  return `${number.toFixed(shown).replace(".", ",")}%`;
}

function labelCountsText(counts) {
  if (!counts) return "";
  return `${counts.Bullish || 0} nghiêng tích cực · ${counts.Neutral || 0} trung tính · ${counts.Bearish || 0} nghiêng tiêu cực`;
}

function queriesTried(providers) {
  const parts = (providers || []).map((row) => {
    const name = row.provider === "Google News RSS" ? `Google bậc ${row.tier}` : row.provider;
    return `${name}: ${providerStatusLabel(String(row.status))}`;
  });
  return parts.join(" · ");
}

function formatDay(iso) {
  const moment = new Date(iso);
  if (!iso || Number.isNaN(moment.getTime())) return "không rõ ngày";
  return moment.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function dateRange(h) {
  const parts = [];
  if (h.oldest_published_at) {
    const oldest = formatDay(h.oldest_published_at);
    const newest = formatDay(h.newest_published_at);
    parts.push(oldest === newest ? `ngày ${newest}` : `${oldest} – ${newest}`);
  }
  if (h.undated_count) parts.push(`${h.undated_count} tin không rõ ngày`);
  return parts.join(" · ");
}

function onScale(value) {
  return `${((Math.max(-1, Math.min(1, Number(value))) + 1) / 2) * 100}%`;
}

function leanText(score) {
  if (score > 0) return "nghiêng tích cực theo điểm tiêu đề";
  if (score < 0) return "nghiêng tiêu cực theo điểm tiêu đề";
  return "không nghiêng về phía nào theo điểm tiêu đề";
}

function emptyScoreText(direction) {
  return "Chưa có dữ liệu để tính điểm";
}

function foldout(title, className = "") {
  const box = document.createElement("details");
  box.className = `advanced cov-fold${className ? ` ${className}` : ""}`;
  box.append(node("summary", "", title));
  return box;
}

// ---------- Dữ liệu của một lượt: LIVE hay FIXTURE, lấy tin lúc nào ----------
function snapshotInfo(data) {
  const mode = String(data.data_mode || "không rõ").toUpperCase();
  const freshness = data.data_freshness;
  if (!freshness) {
    return { mode, live: false, text: "Dữ liệu minh họa (fixture), không phải tin thật. Không gọi nguồn tin nào." };
  }
  const calls = (data.providers || []).filter((row) => row.fetched_at);
  const fresh = calls.filter((row) => !row.cached);
  const reused = calls.filter((row) => row.cached).map((row) => row.fetched_at).sort();
  const ttl = Math.round(Number(freshness.news_cache_ttl_seconds || 0) / 60);
  let text;
  if (fresh.length && !reused.length) {
    text = `Tin lấy trực tiếp lúc ${formatClock(freshness.requested_at_utc)} (giờ máy bạn).`;
  } else if (reused.length && !fresh.length) {
    text = `Dùng lại tin đã lấy lúc ${formatClock(reused[0])} (${formatAge(reused[0])}); bộ nhớ đệm giữ tin ${ttl} phút.`;
  } else if (reused.length) {
    text = `Một phần tin lấy lúc ${formatClock(freshness.requested_at_utc)}, phần còn lại dùng lại tin đã lấy lúc ${formatClock(reused[0])}; bộ nhớ đệm giữ tin ${ttl} phút.`;
  } else {
    text = `Gửi yêu cầu lúc ${formatClock(freshness.requested_at_utc)}; không lượt gọi nguồn tin nào ghi giờ.`;
  }
  return { mode, live: true, text };
}

function modeChip(info) {
  return node("span", `cov-mode ${info.live ? "cov-mode-live" : "cov-mode-fixture"}`, info.mode);
}

// ---------- Công thức (giống hệt backend/upgrades/coverage.py) ----------
// w_i = vốn_i / tổng vốn; C = Σ w_i của mã có tin; r_i = w_i / C; c_i = r_i × s_i; S = Σ c_i;
// Chỉ tính từ tin đã chấm. Mã chưa có dữ liệu: r và c là null, không gán điểm 0.
function portfolioView(holdings, rawWeights, config = {}) {
  const total = rawWeights.reduce((sum, value) => sum + Number(value || 0), 0);
  const rows = holdings.map((h, index) => ({ h, w: total > 0 ? Number(rawWeights[index] || 0) / total : 0 }));
  const coverage = rows.filter((row) => row.h.has_news).reduce((sum, row) => sum + row.w, 0);
  for (const row of rows) {
    row.r = row.h.has_news && coverage > 0 ? row.w / coverage : null;
    row.c = row.r === null ? null : row.r * row.h.score;
  }
  const covered = rows.filter((row) => row.h.has_news);
  const rawScore = coverage > 0 ? covered.reduce((sum, row) => sum + row.c, 0) : null;
  const score = rawScore;
  const direction = score === null ? "no_company_news" : score > 0 ? "positive" : score < 0 ? "negative" : "balanced";
  return finishView({ rows, coverage, score, rawScore, direction });
}

// Một danh mục, dùng nguyên số backend trả về (chế độ một danh mục).
// Same scored holdings on both sides: only weights change, never fetch or infer here.
function equalWeightView(holdings, rawWeights) {
  return portfolioView(holdings, rawWeights.map(w => Number(w) > 0 ? 1 : 0));
}

function sameBatchComparison(data, initialWeights, label = "") {
  const section = node("section", "cov-summary");
  section.append(node("h3", "table-title", `Cùng tin đã chấm: chia đều hay theo vốn${label ? " · " + label : ""}`));
  section.append(node("p", "cov-same-batch", "Giữ nguyên tiêu đề, điểm FinBERT và điểm từng mã. Bên trái chia đều theo mã; bên phải dùng vốn bạn nhập. Đổi vốn dưới đây chỉ cập nhật khung so sánh này trên cùng lô tin, không gọi nguồn hoặc chấm lại. Các phần khác giữ kết quả yêu cầu ban đầu."));
  const controls = node("div", "cov-facts");
  const inputs = data.holdings.map((h, i) => {
    const wrap = node("label", "");
    wrap.append(node("span", "", `${h.short || h.symbol} · phần vốn `));
    const input = node("input", ""); input.type = "number"; input.min = "0"; input.step = "any"; input.value = initialWeights[i];
    input.setAttribute("aria-label", `Vốn so sánh ${label} ${h.short || h.symbol}`);
    wrap.append(input); controls.append(wrap); return input;
  });
  const cards = node("div", "cov-ab-grid");
  const explanation = node("p", "method-note");
  const terms = node("div", "cov-facts");
  const render = () => {
    const weights = inputs.map(x => Number(x.value));
    cards.replaceChildren(); terms.replaceChildren();
    if (weights.some(w => !Number.isFinite(w) || w < 0) || !weights.some(w => w > 0)) {
      explanation.textContent = "Nhập vốn không âm và có ít nhất một mã lớn hơn 0."; return;
    }
    const equal = equalWeightView(data.holdings, weights);
    const weighted = portfolioView(data.holdings, weights);
    cards.append(abCard("chia đều theo mã", equal), abCard("theo vốn", weighted));
    weighted.rows.forEach((row, i) => {
      if (row.w <= 0) return;
      const e = equal.rows[i];
      const detail = row.h.has_news ? `Điểm mã ${vSigned(row.h.score, 6)} · ${row.h.n} tin. Đóng góp chia đều ${vSigned(e.c, 6)}; theo vốn ${vSigned(row.c, 6)}.` : "Chưa có điểm; không gán điểm thay thế.";
      terms.append(fact(row.h.short || row.h.symbol, vPct(row.w), detail));
    });
    const delta = equal.score == null || weighted.score == null ? null : weighted.score - equal.score;
    explanation.textContent = delta === null ? "Chưa có điểm tin để so sánh; không tự gán điểm 0." : `Theo vốn − chia đều = ${vSigned(delta, 6)}. ${Math.abs(delta) < 1e-9 ? "Hai kết quả bằng nhau." : "Chênh lệch chỉ đến từ tỷ trọng vốn."} Vốn bằng nhau phải cho điểm bằng nhau; đổi vốn có thể không đổi điểm nếu các mã có điểm bằng nhau hoặc đóng góp bù nhau.`;
  };
  inputs.forEach(input => input.addEventListener("input", render));
  section.append(controls, cards, explanation, terms);
  section.append(node("p", "method-note", "Mốc chia đều này không phải điểm tab bài gốc: tab đó gộp từng tiêu đề và cả vĩ mô, với tập tin khác. Ở đây hai bên cùng dùng tin doanh nghiệp; vĩ mô hiển thị riêng. Mã có vốn 0 không tham gia; mã chưa có điểm được thông báo ở phần phạm vi và không được gán điểm thay thế."));
  section.append(node("p", "method-note", "Đóng góp của mã = tỷ trọng vốn trong phần có điểm × điểm mã. Ở cấu hình mặc định, đóng góp của một tin = tỷ trọng đó × điểm tin / số tin của mã. Đây là đóng góp số học vào điểm danh mục, không phải mức tin làm giá tăng hoặc giảm."));
  render(); return section;
}

function backendView(data) {
  const p = data.portfolio;
  const rows = data.holdings.map((h) => ({ h, w: h.w, r: h.r, c: h.contribution }));
  return finishView({
    rows,
    coverage: p.coverage,
    score: p.score,
    rawScore: p.sum_contributions,
    direction: p.direction,
    directionText: p.direction_text,
  });
}

function finishView(view) {
  view.held = view.rows.filter((row) => row.w > 0);
  view.covered = view.held.filter((row) => row.h.has_news);
  // "Đủ vốn có tin" đếm theo mã, không so số thực với 1 (0,2 × 5 có thể ra 0,9999…).
  view.full = view.held.length > 0 && view.covered.length === view.held.length;
  view.headlines = view.held.reduce((sum, row) => sum + (row.h.n || 0), 0);
  return view;
}

function close(a, b) {
  if (a === null || a === undefined || b === null || b === undefined) return a == null && b == null;
  return Math.abs(Number(a) - Number(b)) < MATCH_TOLERANCE;
}

// Danh mục A tính lại ở trình duyệt phải khớp số backend (cùng phản hồi, cùng phần vốn).
function matchesBackend(view, portfolio) {
  return close(view.coverage, portfolio.coverage) && close(view.score, portfolio.score);
}

// ---------- Khối tóm tắt ----------
function fact(label, value, note) {
  const box = node("div", "cov-fact");
  box.append(node("small", "", label), node("strong", "", value));
  if (note) box.append(node("span", "", note));
  return box;
}

function coverageFact(view) {
  const note = `${view.covered.length}/${view.held.length} mã có tiêu đề qua bộ lọc hiện tại`;
  return fact("Vốn được đại diện", `${vPct(view.coverage)}`, note);
}

function duplicateCaveat() {
  return node(
    "p",
    "cov-caveat",
    "Điểm tính theo từng tiêu đề. Bản này chỉ bỏ bản lặp cùng URL (khi không có URL thì cùng tiêu đề); nhiều tiêu đề về cùng một sự kiện, kể cả cùng một tin đăng ở hai báo, vẫn được tính nhiều lần. Bấm vào từng mã bên dưới để xem phễu đếm và các tiêu đề.",
  );
}

function hasNewsNote() {
  const fold = foldout("Cách đọc điểm và giới hạn");
  fold.append(node("p", "", "S là sắc thái headline của phần vốn có tin sau khi chuẩn hóa lại về 100%; nó không phải lợi suất, dự báo giá hay xác suất cổ phiếu tăng."));
  fold.append(node("p", "", "“Có tin” nghĩa là ít nhất một tiêu đề qua bộ lọc tự động trong các nguồn đã gọi. “Không có tin” nghĩa là lượt truy vấn này không tìm thấy tiêu đề qua lọc, không chứng minh công ty không có tin. Bộ lọc chưa được người kiểm duyệt xác nhận từng bài."));
  fold.append(duplicateCaveat());
  return fold;
}

function scoreBlock(view, caption) {
  const big = node("div", "cov-big");
  if (view.score === null || view.score === undefined) {
    big.append(node("strong", "cov-big-empty", emptyScoreText(view.direction)));
  } else {
    big.append(node("strong", "", vSigned(view.score, 6)));
    big.append(node("span", "cov-big-caption", caption));
  }
  return big;
}

function singleSummary(data, view) {
  const info = snapshotInfo(data);
  const box = node("section", "cov-summary");
  const top = node("div", "cov-summary-top");
  top.append(node("div", "result-kicker", "Sắc thái tin theo tỷ trọng vốn"), modeChip(info));
  box.append(top, node("h2", "", view.held.map((row) => row.h.short).join(" · ")), scopeLine());
  box.append(scoreBlock(view, `S trên phần có tin · −1 tiêu cực đến +1 tích cực · ${vPct(view.coverage)} vốn được đại diện`));
  if (view.score !== null && view.score !== undefined) {
    box.append(node("p", "cov-lean", `Các tiêu đề được chấm đang ${leanText(view.score)}.`));
  }
  const facts = node("div", "cov-facts");
  facts.append(
    coverageFact(view),
    fact("Tiêu đề được chấm", `${view.headlines}`, "sau bộ lọc hiện tại"),
    fact("Lượt dữ liệu", info.mode, info.text),
  );
  box.append(facts, hasNewsNote());
  return box;
}

// ---------- Biểu đồ thanh lệch tâm (đóng góp, hoặc phần chênh B − A) ----------
function niceLimit(values) {
  const peak = Math.max(0, ...values.map((value) => Math.abs(value)));
  for (const step of [0.05, 0.1, 0.2, 0.25, 0.5, 1]) if (peak <= step) return step;
  return Math.ceil(peak);
}

function barPlot(value, limit, label) {
  const plot = node("div", "cov-row-plot");
  const track = node("span", "cov-row-track");
  const half = (Math.min(Math.abs(value), limit) / limit) * 50;
  const fill = node("span", `cov-row-fill ${value >= 0 ? "up" : "down"}`);
  fill.style.width = `${half}%`;
  fill.style.left = value >= 0 ? "50%" : `${50 - half}%`;
  fill.title = label;
  plot.append(track, fill, node("span", "cov-row-zero"));
  plot.setAttribute("role", "img");
  plot.setAttribute("aria-label", label);
  return plot;
}

function pullWord(value) {
  if (value > 0) return "đóng góp dương";
  if (value < 0) return "đóng góp âm";
  return "không đổi";
}

// rows: [{h, facts, value (null = chưa có điểm), body}]
function divergingChart(rows, { valueHead, emptyText, sumLabel, expected }) {
  const box = node("div", "cov-rows");
  const scored = rows.filter((row) => row.value !== null && row.value !== undefined).sort((a, b) => b.value - a.value);
  const empty = rows.filter((row) => row.value === null || row.value === undefined);
  const limit = niceLimit(scored.map((row) => row.value));

  const head = node("div", "cov-row-head");
  head.append(node("span", "", "Mã · vốn · tiêu đề · điểm mã"), node("span", "cov-row-head-plot", `đóng góp âm ← 0 → dương`), node("span", "cov-row-head-value", valueHead), node("span", "", ""));
  box.append(head);

  for (const row of [...scored, ...empty]) {
    const hasValue = row.value !== null && row.value !== undefined;
    const item = node("details", `cov-row${hasValue ? "" : " cov-row-empty"}`);
    const summary = node("summary", "cov-row-summary");
    const name = node("div", "cov-row-name");
    name.append(node("strong", "", row.h.short), node("small", "", row.facts));
    const value = node("div", "cov-row-value");
    if (hasValue) {
      value.append(node("strong", "", vSigned(row.value, 2)), node("small", "", pullWord(row.value)));
    } else {
      value.append(node("strong", "", "—"), node("small", "", "không có thanh"));
    }
    const plot = hasValue
      ? barPlot(row.value, limit, `${row.h.short}: ${valueHead.toLowerCase()} ${vSigned(row.value, 4)}`)
      : node("div", "cov-row-plot cov-row-nodata", emptyText);
    summary.append(name, plot, value, node("span", "cov-expand", "Xem tin"));
    item.append(summary, row.body);
    box.append(item);
  }

  const axis = node("div", "cov-axis");
  const ticks = node("span", "cov-axis-ticks");
  ticks.append(node("span", "", vSigned(-limit, 2)), node("span", "", "0"), node("span", "", vSigned(limit, 2)));
  axis.append(node("span", "", ""), ticks, node("span", "", ""), node("span", "", ""));
  box.append(axis);

  const total = scored.reduce((sum, row) => sum + row.value, 0);
  const sum = node("p", "cov-sum", `${sumLabel} = ${vSigned(total, 4)} (số trên mỗi thanh đã làm tròn 2 chữ số).`);
  if (expected !== null && expected !== undefined && !close(total, expected)) {
    sum.className = "cov-warning";
    sum.textContent = `Tổng các thanh ${vSigned(total, 6)} không khớp ${vSigned(expected, 6)}. Đây là lỗi hiển thị, hãy báo lại.`;
  }
  box.append(sum);
  return box;
}

function rowFacts(row, view) {
  const h = row.h;
  if (!h.has_news) {
    const why = h.candidates_total ? `${h.candidates_total} ứng viên, không còn tiêu đề qua lọc` : "nguồn đã gọi trả về 0 ứng viên";
    return `vốn ${vPct(row.w)} · lượt này chưa có tiêu đề qua lọc (${why})`;
  }
  const share = view.full ? "" : ` · ${vPct(row.r)} trong phần có tin`;
  return `vốn ${vPct(row.w)} · ${h.n} tiêu đề · sắc thái mã ${vSigned(h.score, 2)}${share}`;
}

function contributionChart(view, { withHeadlineShare = true } = {}) {
  const rows = view.held.map((row) => ({
    h: row.h,
    facts: rowFacts(row, view),
    value: row.h.has_news ? row.c : null,
    body: holdingDetails(row.h, withHeadlineShare ? row.r : undefined),
  }));
  return divergingChart(rows, {
    valueHead: "Đóng góp",
    emptyText: NO_SCORE_TEXT,
    sumLabel: "Cộng các thanh = S",
    expected: view.score ?? view.rawScore,
  });
}

function contributionIntro(view) {
  let text =
    "Mỗi thanh là đóng góp số học của một mã vào S = tỷ trọng vốn trong phần có tin × sắc thái tiêu đề của mã. Bên phải 0 là đóng góp dương, bên trái là âm. Mã chưa có tin qua lọc không có thanh; không được coi là điểm 0.";
  const example = view.covered[0];
  if (!view.full && example) {
    text += ` Vì chỉ ${vPct(view.coverage)} vốn có tin, phần vốn của mỗi mã được chia lại trên ${vPct(view.coverage)} đó (ví dụ ${example.h.short}: ${vPct(example.w)} / ${vPct(view.coverage)} = ${vPct(example.r)}).`;
  }
  return node("p", "cov-chart-intro", text);
}

function chartSection(title, ...parts) {
  const section = node("section", "cov-chart");
  section.append(node("h3", "", title), ...parts);
  return section;
}

// ---------- Phễu đếm: mọi số lấy từ JSON, giao diện không đổi quyết định lọc ----------
let headlineCap = null; // config.max_headlines_per_holding của lượt đang hiện

// Thứ tự luật của relevance-v3 (backend/upgrades/relevance.py). Mỗi bản ghi chỉ mang lý do đầu tiên khớp.
const REASON_ORDER = ["stale", "missing_title", "duplicate", "name_only_in_description", "name_not_in_title", "ambiguous_name", "sports", "not_news_page"];
const REASON_GROUP = {
  stale: "Cũ hơn cửa sổ tin",
  missing_title: "Thiếu tiêu đề",
  duplicate: "Bản lặp cùng URL (khi không có URL: cùng tiêu đề)",
  name_only_in_description: "Tên công ty chỉ có trong phần mô tả, không có trong tiêu đề",
  name_not_in_title: "Tiêu đề không nhắc tên hay alias của công ty",
  ambiguous_name: "Tên trùng với tổ chức khác, tiêu đề không nhắc Ai Cập",
  sports: "Tiêu đề có từ khóa thể thao",
  not_news_page: "Trang dữ liệu (báo giá, biểu đồ), không phải tin",
};
const FLAG_TEXT = {
  not_news_page: "cũng khớp mẫu trang dữ liệu (báo giá, biểu đồ)",
  sports: "cũng khớp từ khóa thể thao",
};
const RULE_ORDER_TEXT = "quá hạn → thiếu tiêu đề → bản lặp → tên công ty trong tiêu đề → tên trùng (ADIB) → thể thao → trang dữ liệu";

function capText() {
  return headlineCap === null || headlineCap === undefined ? "giới hạn" : `giới hạn ${headlineCap}`;
}

function funnelOf(h) {
  const rejected = (h.rejected || []).length;
  const scored = (h.headlines || []).length;
  const over = (h.not_scored || []).length;
  const candidates = Number(h.candidates_total || 0);
  return { candidates, rejected, pass: scored + over, scored, over, adds: candidates === rejected + scored + over };
}

function funnelTotals(holdings) {
  const total = { candidates: 0, rejected: 0, pass: 0, scored: 0, over: 0, adds: true };
  for (const h of holdings) {
    const f = funnelOf(h);
    for (const key of ["candidates", "rejected", "pass", "scored", "over"]) total[key] += f[key];
    total.adds = total.adds && f.adds;
  }
  return total;
}

function funnelSentence(t) {
  const over = t.over ? `, trong đó ${t.over} ngoài ${capText()} tiêu đề mỗi mã nên không chấm` : "";
  return `Từ ${t.candidates} bản ghi ứng viên: ${t.rejected} bị luật tự động loại, ${t.pass} qua luật hiện tại${over}. Chấm bằng FinBERT.`;
}

function scopeLine() {
  return node("p", "cov-scope", "Tổng hợp sắc thái các tin đã thu thập và chấm theo tỷ trọng vốn của từng mã. Xem đóng góp, nguồn tin và cách tính ở phần chi tiết.");
}

function funnelStep(count, label, className = "") {
  const step = node("div", `cov-step${className ? ` ${className}` : ""}`);
  step.append(node("strong", "", String(count)), node("span", "", label));
  return step;
}

function funnelBox(h) {
  const f = funnelOf(h);
  const box = node("div", "cov-funnel");
  box.setAttribute("aria-label", `Phễu đếm ${h.short}: ${f.candidates} ứng viên, ${f.rejected} tự động loại, ${f.pass} qua luật hiện tại, ${f.scored} được chấm, ${f.over} ngoài ${capText()}`);
  const first = node("div", "cov-funnel-line");
  first.append(funnelStep(f.candidates, "bản ghi ứng viên"), node("span", "cov-op", "="), funnelStep(f.rejected, "bị luật tự động loại", "cov-step-out"), node("span", "cov-op", "+"), funnelStep(f.pass, "qua luật hiện tại"));
  const second = node("div", "cov-funnel-line");
  second.append(funnelStep(f.pass, "qua luật hiện tại"), node("span", "cov-op", "="), funnelStep(f.scored, "được chấm bằng FinBERT"), node("span", "cov-op", "+"), funnelStep(f.over, `qua luật nhưng ngoài ${capText()}`, "cov-step-out"));
  box.append(first, second);
  if (!f.adds) {
    box.append(node("p", "cov-warning", `Phễu không cộng khớp: ${f.candidates} ứng viên ≠ ${f.rejected} + ${f.scored} + ${f.over}. Đây là lỗi hiển thị hoặc dữ liệu, hãy báo lại.`));
  }
  return box;
}

// Bảng của tab 3: trên màn hẹp mỗi dòng thành một thẻ (nhãn cột đứng trên giá trị), nên không cần cuộn ngang.
function stackTable(headers, rows, className) {
  return stackExisting(table(headers, rows, className));
}

function stackExisting(wrap) {
  const headers = [...wrap.querySelectorAll("thead th")].map((th) => th.textContent);
  wrap.classList.add("cov-stack");
  for (const tr of wrap.querySelectorAll("tbody tr")) {
    [...tr.children].forEach((td, index) => {
      td.dataset.label = headers[index] || "";
    });
  }
  return wrap;
}

function sourceTier(row) {
  return `${row.source || "—"} · bậc ${row.query_tier ?? "?"}`;
}

function recordList(rows, noteOf) {
  const list = node("ul", "cov-records");
  for (const row of rows) {
    const item = node("li", "cov-record");
    item.append(node("div", "cov-record-title"));
    item.firstChild.append(safeLink(row.url, row.title) || document.createTextNode(row.title || "(không có tiêu đề)"));
    item.append(node("div", "cov-record-meta", `${row.published_at ? formatDay(row.published_at) : "không rõ ngày"} · ${sourceTier(row)}`));
    const note = noteOf ? noteOf(row) : "";
    if (note) item.append(node("div", "cov-record-note", note));
    list.append(item);
  }
  return list;
}

function reasonLabel(code, rows) {
  if (code === "stale" && rows[0] && rows[0].reason) return rows[0].reason;
  return REASON_GROUP[code] || (rows[0] && rows[0].reason) || code;
}

// Chi tiết của lý do đầu tiên: từ đã khớp (thể thao, trang dữ liệu) hoặc câu đầy đủ (tên trùng).
function reasonTerm(row, code) {
  const term = /\(([^()]*)\)\s*$/.exec(row.reason || "");
  if ((code === "sports" || code === "not_news_page") && term) return `từ khớp: “${term[1]}”`;
  if (code === "ambiguous_name" && row.reason) return row.reason;
  return "";
}

function rejectedNote(row, code) {
  const parts = [];
  const term = reasonTerm(row, code);
  if (term) parts.push(term.charAt(0).toUpperCase() + term.slice(1));
  const extra = (row.pattern_flags || []).filter((flag) => flag !== code).map((flag) => FLAG_TEXT[flag] || flag);
  if (extra.length) parts.push(`Dấu hiệu khác: ${extra.join("; ")}`);
  return parts.join(" · ");
}

function rejectedFold(h) {
  const groups = new Map();
  for (const row of h.rejected) {
    const code = row.reason_code || "other";
    if (!groups.has(code)) groups.set(code, []);
    groups.get(code).push(row);
  }
  const rank = (code) => (REASON_ORDER.includes(code) ? REASON_ORDER.indexOf(code) : REASON_ORDER.length);
  const codes = [...groups.keys()].sort((a, b) => rank(a) - rank(b));
  const box = foldout(`Bị luật tự động loại (${h.rejected.length})`, "cov-fold-inner cov-rejected");
  box.append(
    node(
      "p",
      "method-note",
      `Loại tự động, chưa có người kiểm. Luật có thể loại nhầm tin có nói về công ty nhưng tiêu đề không nêu tên công ty. Luật xét lần lượt: ${RULE_ORDER_TEXT}. Mỗi bản ghi chỉ ghi lý do đầu tiên khớp, và số đếm theo lý do đó. "Dấu hiệu khác" cho biết tiêu đề còn khớp mẫu trang dữ liệu hay từ khóa thể thao; chỉ để xem, không đổi quyết định và không đổi số đếm.`,
    ),
  );
  box.append(node("p", "cov-reason-counts", codes.map((code) => `${reasonLabel(code, groups.get(code))}: ${groups.get(code).length}`).join(" · ")));
  for (const code of codes) {
    const rows = groups.get(code);
    box.append(node("h5", "cov-subtitle", `${reasonLabel(code, rows)} (${rows.length})`));
    box.append(recordList(rows, (row) => rejectedNote(row, code)));
  }
  return box;
}

function overCapFold(h) {
  const box = foldout(`Qua luật hiện tại nhưng ngoài ${capText()} (${h.not_scored.length})`, "cov-fold-inner cov-overcap");
  box.append(
    node(
      "p",
      "method-note",
      `Mỗi mã chỉ chấm ${headlineCap ?? "một số"} tiêu đề mới nhất theo ngày đăng; ngày không rõ xếp sau. Các bản ghi dưới đây qua luật hiện tại nhưng ngoài ${headlineCap ?? "số"} tiêu đề đó, nên không được chấm và không vào S.`,
    ),
  );
  box.append(recordList(h.not_scored, null));
  return box;
}

// ---------- Chi tiết của một mã (mở khi bấm vào dòng) ----------
function holdingDetails(h, r) {
  const body = node("div", "cov-row-body");
  body.append(funnelBox(h));
  body.append(node("p", "method-note", `${h.company}. Tên dùng để lọc: ${h.aliases.join(", ")}.${h.has_news ? ` Thời gian đăng của tiêu đề được chấm: ${dateRange(h)}.` : ""}`));
  if (h.providers && h.providers.length) body.append(node("p", "method-note", `Truy vấn đã gọi cho mã này: ${queriesTried(h.providers)}.`));
  if (h.has_news) {
    body.append(
      node(
        "p",
        "method-note",
        `Điểm mã ${vSigned(h.score, 4)} = trung bình P+ − trung bình P− của ${h.n} tiêu đề. Nhãn FinBERT của mã: ${h.label} (lớp có xác suất trung bình lớn nhất); tiêu đề theo nhãn: ${labelCountsText(h.label_counts)}.`,
      ),
    );
  } else {
    body.append(
      node(
        "p",
        "method-note",
        "Không có tiêu đề qua luật hiện tại nghĩa là các truy vấn trên không trả về tiêu đề nào qua luật trong cửa sổ tin (lý do từng bản ghi ở danh sách bên dưới). Công ty vẫn có thể có tin ở nguồn khác; mã này chưa có điểm, nên không tham gia S. Hệ thống không gán điểm thay thế.",
      ),
    );
  }
  if (h.headlines.length) {
    const withShare = r !== undefined && r !== null;
    body.append(node("h4", "cov-subtitle", withShare ? "Tiêu đề được chấm (cộng cột đóng góp ra đúng đóng góp của mã)" : "Tiêu đề được chấm"));
    const headers = ["Tiêu đề", "Đăng", "Nguồn", "P+", "P−", "P0", "s = P+ − P−"];
    if (withShare) headers.push("Đóng góp");
    body.append(
      stackTable(
        headers,
        h.headlines.map((row) => {
          const cells = [
            safeLink(row.url, row.title) || row.title,
            row.published_at ? formatDay(row.published_at) : "không rõ",
            sourceTier(row),
            vPct(row.probabilities.positive, 1),
            vPct(row.probabilities.negative, 1),
            vPct(row.probabilities.neutral, 1),
            vSigned(row.score, 3),
          ];
          if (withShare) cells.push(vSigned(r * row.share_of_holding_score, 4));
          return cells;
        }),
        "data-table cov-scored-table",
      ),
    );
  }
  if (h.not_scored.length) body.append(overCapFold(h));
  if (h.rejected.length) body.append(rejectedFold(h));
  return body;
}

// ---------- Khối tham khảo: khớp tên theo bộ lọc Tab 1–2 ----------
function oldFilterFold(holdings) {
  const rows = holdings.flatMap((h) => h.rejected.filter((row) => row.old_filter_keep).map((row) => ({ h, row })));
  const box = foldout(`Tham khảo · Khớp tên theo bộ lọc Tab 1–2: ${rows.length} bản ghi bị luật hiện tại loại nhưng khớp tên`);
  box.append(
    node(
      "p",
      "",
      "Bộ lọc Tab 1–2 (của bản tái dựng) chỉ kiểm một điều: tên hoặc alias của công ty có nằm trong tiêu đề + mô tả hay không, so theo chuỗi con (ví dụ \"COMI\" khớp cả \"coming\"). Đây không phải quyết định cuối của luồng Tab 1–2, vì luồng đó còn bỏ bản lặp, bỏ tin quá hạn và lấy tin theo cách riêng. Khối này chỉ để đối chiếu, không đổi S.",
    ),
  );
  box.append(node("p", "", `${rows.length} là số bản ghi trong lượt này, không phải số sự kiện: một bản lặp cùng URL cũng được đếm là một bản ghi.`));
  const perHolding = holdings.map((h) => {
    const f = funnelOf(h);
    const rejectedMatch = h.rejected.filter((row) => row.old_filter_keep).length;
    const passMatch = Number(h.old_filter_would_keep || 0) - rejectedMatch;
    return { h, f, rejectedMatch, passMatch };
  });
  box.append(
    stackTable(
      ["Mã", "Qua luật hiện tại · khớp tên", "Bị luật hiện tại loại · khớp tên"],
      perHolding.map(({ h, f, rejectedMatch, passMatch }) => [h.short, `${passMatch}/${f.pass}`, `${rejectedMatch}/${f.rejected}`]),
    ),
  );
  const allPassMatch = perHolding.every(({ f, passMatch }) => passMatch === f.pass);
  box.append(
    node(
      "p",
      "method-note",
      allPassMatch
        ? `Mọi bản ghi qua luật hiện tại trong lượt này cũng khớp tên theo bộ lọc Tab 1–2; hai bên chỉ khác ở ${rows.length} bản ghi bị luật hiện tại loại.`
        : `${perHolding.reduce((sum, { f, passMatch }) => sum + (f.pass - passMatch), 0)} bản ghi qua luật hiện tại nhưng không khớp tên theo bộ lọc Tab 1–2; thêm ${rows.length} bản ghi bị luật hiện tại loại nhưng khớp tên.`,
    ),
  );
  if (rows.length) {
    box.append(node("h4", "cov-subtitle", "Các bản ghi bị luật hiện tại loại nhưng khớp tên theo bộ lọc Tab 1–2"));
    box.append(
      recordList(
        rows.map(({ row }) => row),
        (row) => {
          const code = row.reason_code || "other";
          const term = reasonTerm(row, code);
          return `${shortSymbol(row.symbol)} · lý do loại hiện tại: ${reasonLabel(code, [row])}${term && code !== "ambiguous_name" ? ` (${term})` : ""}`;
        },
      ),
    );
  }
  return box;
}

// ---------- Phạm vi của điểm quan sát ----------
function observedScopeSection(items) {
  const section = node("section", "cov-chart");
  section.append(node("h3", "", "Các mã tham gia điểm tổng hợp"));
  for (const { label, view } of items) {
    const prefix = label ? `Danh mục ${label}: ` : "";
    const included = view.covered.map(row => row.h.short).join(", ");
    const missing = view.held.filter(row => !row.h.has_news).map(row => row.h.short).join(", ");
    section.append(node("p", "", included
      ? `${prefix}Điểm tính từ tin đã chấm của ${included}, đại diện ${vPct(view.coverage)} vốn đã nhập.`
      : `${prefix}Chưa có dữ liệu đã chấm để tính điểm cho phần vốn đã nhập.`));
    if (missing) section.append(node("p", "", `${missing}: chưa có tin được chấm trong lượt này; không gán điểm 0, không đưa vào phép tổng hợp. Tỷ trọng của các mã có điểm được chuẩn hóa lại.`));
  }
  section.append(node("p", "method-note", "Kết quả chỉ mô tả các tin đã thu thập và chấm. Có tin không có nghĩa đã thu đủ mọi tin của doanh nghiệp; hệ thống không dự đoán điểm cho tin chưa có."));
  return section;
}

// ---------- Mục tham khảo và chi tiết ----------
function headlineTable(rows, kindColumn) {
  const headers = ["Tiêu đề", "Đăng", "Nguồn"];
  if (kindColumn) headers.push("Loại", "Mã");
  headers.push("s = P+ − P−");
  return stackTable(
    headers,
    rows.map((row) => {
      const cells = [safeLink(row.url, row.title) || row.title, row.published_at ? formatDay(row.published_at) : "không rõ", row.source || "—"];
      if (kindColumn) cells.push(row.kind === "macro" ? "Vĩ mô" : "Riêng mã", shortSymbol(row.symbol));
      cells.push(vSigned(row.score, 3));
      return cells;
    }),
  );
}

function macroFold(macro) {
  const has = macro && macro.n;
  const box = foldout(`Tham khảo · Tin kinh tế Ai Cập: ${has ? `${vSigned(macro.score, 2)} từ ${macro.n} tiêu đề` : "không tìm thấy"} · không cộng vào S`);
  box.append(
    node(
      "p",
      "",
      has
        ? `Đây là tin chung về nền kinh tế, không riêng mã nào, nên được hiện riêng và không cộng vào S. M = trung bình P+ − trung bình P− = ${vSigned(macro.score, 4)} · tiêu đề theo nhãn: ${labelCountsText(macro.label_counts)}. ${macro.keep_rule}`
        : `Không tìm thấy tin kinh tế hay thị trường Ai Cập trong cửa sổ tin.${macro ? ` ${macro.keep_rule}` : ""}`,
    ),
  );
  if (has) box.append(headlineTable(macro.headlines, false));
  if (macro && macro.rejected && macro.rejected.length) {
    box.append(node("h4", "cov-subtitle", `${macro.rejected.length} tin vĩ mô bị loại và lý do`));
    box.append(stackTable(["Tiêu đề", "Lý do", "Nguồn"], macro.rejected.map((row) => [safeLink(row.url, row.title) || row.title, row.reason, row.source || "—"])));
  }
  return box;
}

function articleFold(article, compareMode) {
  const box = foldout(`Tham khảo · Mốc tái dựng theo bài báo: ${article ? vSigned(article.score, 2) : "không có tiêu đề"}`);
  if (!article) return box;
  box.append(
    node(
      "p",
      "",
      `${article.headline_count} tiêu đề; mỗi tiêu đề một phiếu, gộp tin doanh nghiệp và vĩ mô, không theo vốn. ${article.selection}. Đây là mốc của bản tái dựng: bài báo không công bố đầy đủ công thức gộp xác suất.${compareMode ? " Ở chế độ A/B, mốc này dùng chung toàn bộ mã và cùng lô tin của hai danh mục." : ""}`,
    ),
  );
  box.append(node("p", "", `Nhãn của mốc tái dựng: ${sentimentLabelVi(article.sentiment)}. Điểm s là trung bình P(tích cực) − P(tiêu cực); không phải hiệu suất đầu tư.`));
  box.append(headlineTable(article.headlines, true));
  return box;
}

function capitalBar(capital) {
  const parts = [
    ["Bullish", "Tích cực theo nhãn FinBERT", "seg-bullish"],
    ["Neutral", "Trung tính theo nhãn FinBERT", "seg-neutral"],
    ["Bearish", "Tiêu cực theo nhãn FinBERT", "seg-bearish"],
    ["no_news", "Chưa có tiêu đề qua lọc", "seg-nonews"],
  ];
  const box = node("div", "cov-capital");
  const bar = node("div", "cov-capital-bar");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", parts.map(([key, label]) => `${label} ${vPct(capital[key] || 0, 1)}`).join("; "));
  for (const [key, label, className] of parts) {
    const value = Number(capital[key] || 0);
    if (value <= 0) continue;
    const segment = node("span", `cov-seg ${className}`, value >= 0.12 ? vPct(value, 0) : "");
    segment.style.flexGrow = String(value);
    segment.title = `${label}: ${vPct(value, 1)} vốn`;
    bar.append(segment);
  }
  const legend = node("div", "cov-legend");
  for (const [key, label, className] of parts) {
    const item = node("span", "cov-legend-item");
    item.append(node("i", `cov-swatch ${className}`), node("span", "", `${label}: ${vPct(capital[key] || 0, 1)} vốn`));
    legend.append(item);
  }
  box.append(bar, legend);
  return box;
}

function labelFold(data, compareMode) {
  const box = foldout("Chi tiết · Nhãn FinBERT theo từng mã (không dùng để tính S)");
  box.append(
    node(
      "p",
      "",
      "Nhãn của mã là lớp có xác suất trung bình cao nhất. Một mã có thể được gắn nhãn trung tính trong khi điểm sắc thái dương hoặc âm. S được tính từ P(tích cực) − P(tiêu cực), không lấy từ nhãn phân loại này; các nhãn dưới đây không đi vào S.",
    ),
  );
  box.append(
    stackTable(
      ["Mã", "Nhãn FinBERT", "Điểm sắc thái", "Số tiêu đề theo nhãn"],
      data.holdings.map((h) => [h.short, h.has_news ? h.label : NO_NEWS_LABEL, h.has_news ? vSigned(h.score, 3) : "—", h.has_news ? labelCountsText(h.label_counts) : "—"]),
    ),
  );
  if (compareMode) {
    box.append(node("p", "method-note", "Phần vốn theo nhãn chỉ hiện ở chế độ một danh mục."));
  } else {
    box.append(node("h4", "cov-subtitle", "Vốn chia theo nhãn của mã"));
    box.append(capitalBar(data.portfolio.capital_by_label));
    if (data.portfolio.capital_by_label_note) box.append(node("p", "method-note", data.portfolio.capital_by_label_note));
  }
  return box;
}

function calcLines(view, name) {
  const prefix = name ? `${name}: ` : "";
  const covered = view.covered;
  const missing = view.held.filter((row) => !row.h.has_news);
  const lines = [
    `${prefix}C = ${covered.map((row) => `${viDigits(row.w, 6)} (${row.h.short})`).join(" + ") || "0"} = ${viDigits(view.coverage, 6)}${missing.length ? `. ${NO_NEWS_LABEL}: ${missing.map((row) => `${row.h.short} ${viDigits(row.w, 6)}`).join(", ")}` : ""}.`,
  ];
  if (covered.length && view.coverage > 0) {
    lines.push(`${prefix}${covered.map((row) => `r ${row.h.short} = ${viDigits(row.w, 6)} / ${viDigits(view.coverage, 6)} = ${viDigits(row.r, 6)}`).join(" · ")}`);
    lines.push(`${prefix}S = ${covered.map((row) => `${viDigits(row.r, 6)} × (${vSigned(row.h.score, 6)})`).join(" + ")} = ${vSigned(view.rawScore, 6)}`);
  }
  return lines;
}

function calcFold(extraLines, views) {
  const box = foldout("Chi tiết · Tính tay từ các số của lượt này", "cov-calc");
  const lines = [
    "Điểm mỗi mã s = trung bình P+ − trung bình P− của các tiêu đề được chấm của mã. w = phần vốn sau khi chuẩn hóa tổng = 1; C = tổng w của mã có tin; r = w / C; đóng góp c = r × s; S = tổng c. Đóng góp của một tiêu đề = r × s_tiêu đề / số tiêu đề của mã.",
  ];
  for (const { label, view } of views) lines.push(...calcLines(view, label));
  lines.push(...extraLines);
  for (const line of lines) box.append(node("p", "", line));
  return box;
}

function sourcesFold(data) {
  const box = foldout("Chi tiết · Nguồn tin, truy vấn, bộ nhớ đệm và phiên bản luật");
  const chips = node("div", "details-row");
  const inference = data.cache.inference_this_request || {};
  chips.append(node("span", "detail-chip", `Thời gian: tin ${data.timing_ms.news.toFixed(0)} ms · model ${data.timing_ms.inference.toFixed(0)} ms · tổng ${data.timing_ms.total.toFixed(0)} ms`));
  chips.append(node("span", "detail-chip", `Bộ nhớ đệm: ${inference.cache_hits ?? 0}/${inference.requested ?? 0} tiêu đề dùng lại · ${inference.model_calls ?? 0} tiêu đề chấm mới`));
  chips.append(node("span", "detail-chip", `Luật lọc ${data.relevance_rules} · cách tính ${data.method_version}`));
  chips.append(node("span", "detail-chip", `Mode: ${data.data_mode}`));
  box.append(chips);
  const options = data.config.experimental_options_on || [];
  box.append(
    node(
      "p",
      "method-note",
      `Tùy chọn thử nghiệm đang bật: ${options.length ? options.join(", ") : "không có (mặc định)"}. Cửa sổ tin ${data.config.lookback_days} ngày, chấm tối đa ${data.config.max_headlines_per_holding} tiêu đề mỗi mã, gọi truy vấn rộng (Google bậc 2) khi dưới ${data.config.tier2_below ?? "—"} tiêu đề qua luật, ${data.config.macro_limit} tin vĩ mô. Các con số này và danh sách từ khóa thể thao, mẫu trang dữ liệu là cấu hình demo, chưa được chứng minh là tối ưu.`,
    ),
  );
  for (const note of data.notes || []) box.append(node("p", "method-note", note));
  const headlines = data.holdings.flatMap((h) => h.headlines).concat(data.macro ? data.macro.headlines : []);
  // addProviderSummary (dùng chung với tab 1–2) gắn bảng vào cuối khung kết quả; chuyển bảng vào mục này.
  addProviderSummary({ headlines, providers: data.providers });
  const providerBox = resultPanel.lastElementChild;
  for (const wrap of providerBox.querySelectorAll(".table-wrap")) stackExisting(wrap);
  box.append(providerBox);
  return box;
}

function referenceSection(data, { compareMode, calc }) {
  const section = node("section", "cov-reference");
  section.append(node("h3", "table-title", "Tham khảo và chi tiết (không thay đổi S)"));
  section.append(macroFold(data.macro), labelFold(data, compareMode), oldFilterFold(data.holdings));
  section.append(node("p", "method-note", "Tab Danh mục (bài gốc) dùng trung bình tiêu đề gồm cả vĩ mô và có cách chọn tin khác. Không dùng chênh lệch với tab đó để kết luận tác dụng riêng của tỷ trọng vốn; dùng khung so sánh cùng tin ở trên."));
  section.append(calcFold(calc.extra || [], calc.views), sourcesFold(data));
  return section;
}

// ---------- Một danh mục ----------
function renderCoverageSingle(data) {
  resultPanel.replaceChildren();
  const view = backendView(data);
  resultPanel.append(singleSummary(data, view));
  resultPanel.append(sameBatchComparison(data, data.holdings.map(h => h.w * 100)));
  resultPanel.append(chartSection("Đóng góp số học của từng mã vào điểm S", contributionIntro(view), contributionChart(view)));
  resultPanel.append(observedScopeSection([{ label: "", view }]));
  resultPanel.append(referenceSection(data, { compareMode: false, calc: { views: [{ label: "", view }] } }));
  resultPanel.append(node("p", "cov-disclaimer", data.disclaimer));
  resultPanel.classList.remove("hidden");
}

// ---------- Hai danh mục A/B trên cùng một lô tin ----------
function compositionText(view) {
  return view.held.map((row) => `${row.h.short} ${vPct(row.w)}`).join(" · ");
}

function abCard(name, view) {
  const card = node("div", "cov-ab-card");
  card.append(node("div", "result-kicker", `Danh mục ${name}`));
  if (view.score === null || view.score === undefined) {
    card.append(node("strong", "cov-ab-score cov-ab-empty", "chưa có điểm"));
    card.append(node("p", "", emptyScoreText(view.direction)));
  } else {
    card.append(node("strong", "cov-ab-score", vSigned(view.score, 6)));
    card.append(node("p", "", `Tiêu đề ${leanText(view.score)}.`));
  }
  card.append(node("p", "", `Trên ${vPct(view.coverage)} vốn có tin · ${view.covered.length}/${view.held.length} mã · ${view.headlines} tiêu đề`));
  card.append(node("p", "cov-ab-mix", compositionText(view)));
  return card;
}

function deltaCard(A, B) {
  const card = node("div", "cov-ab-card cov-ab-delta");
  card.append(node("div", "result-kicker", "B − A"));
  if (A.score === null || A.score === undefined || B.score === null || B.score === undefined) {
    card.append(node("strong", "cov-ab-score cov-ab-empty", "chưa so được"));
    card.append(node("p", "", `${A.score == null ? "A" : "B"} chưa có điểm, nên không có chênh lệch S.`));
    return card;
  }
  const delta = B.score - A.score;
  card.append(node("strong", "cov-ab-score", vSigned(delta, 2)));
  const word = Number(Math.abs(delta).toFixed(4)) === 0 ? "S của B bằng S của A" : delta > 0 ? "S của B cao hơn S của A" : "S của B thấp hơn S của A";
  card.append(node("p", "", `${word}. Trên cùng một lô tin, chênh lệch S đến từ tỷ trọng vốn đã nhập; đây không phải chênh lệch lợi suất.`));
  if (!A.full || !B.full) {
    card.append(
      node(
        "p",
        "",
        `Mỗi S tính trên phần vốn có tin của chính danh mục đó (A ${vPct(A.coverage)}, B ${vPct(B.coverage)}), nên chênh lệch này chỉ so phần có tin. Không suy diễn kết quả cho các mã chưa có dữ liệu.`,
      ),
    );
  }
  return card;
}

function deltaChart(A, B) {
  const rows = A.rows.map((rowA, index) => {
    const rowB = B.rows[index];
    const h = rowA.h;
    const held = rowA.w > 0 || rowB.w > 0;
    if (!held) return null;
    let facts;
    let value = null;
    if (h.has_news) {
      const rA = rowA.r ?? 0;
      const rB = rowB.r ?? 0;
      value = (rB - rA) * h.score;
      const share = A.full && B.full ? "" : ` · trong phần có tin A ${vPct(rA)} → B ${vPct(rB)}`;
      facts = `vốn A ${vPct(rowA.w)} → B ${vPct(rowB.w)} · ${h.n} tiêu đề · điểm mã ${vSigned(h.score, 2)}${share}`;
    } else {
      facts = `vốn A ${vPct(rowA.w)} → B ${vPct(rowB.w)} · không có tiêu đề qua luật hiện tại`;
    }
    return { h, facts, value, body: holdingDetails(h) };
  });
  return divergingChart(rows.filter(Boolean), {
    valueHead: "Phần chênh",
    emptyText: "chưa có điểm · không tính vào S của A hay B",
    sumLabel: "Cộng các thanh = S của B − S của A",
    expected: B.score - A.score,
  });
}

function renderCoverageCompare(data, compare) {
  resultPanel.replaceChildren();
  const config = data.config || {};
  if (data.holdings.length !== compare.weightsA.length) {
    renderError({ error: { code: "compare_mismatch", message: "Số mã backend trả về khác số mã đã gửi; không so được A/B." } });
    return;
  }
  const A = portfolioView(data.holdings, compare.weightsA, config);
  const B = portfolioView(data.holdings, compare.weightsB, config);
  const info = snapshotInfo(data);
  const ok = matchesBackend(A, data.portfolio);

  const box = node("section", "cov-summary");
  const top = node("div", "cov-summary-top");
  top.append(node("div", "result-kicker", "So sánh sắc thái tin theo tỷ trọng vốn"), modeChip(info));
  box.append(top, node("h2", "", "Danh mục A và danh mục B"), scopeLine());
  box.append(
    node(
      "p",
      "cov-same-batch",
      `A và B dùng chung một lần lấy tin và một lượt chấm FinBERT cho ${data.holdings.length} mã. Vì dữ liệu tin giống nhau, phần chênh S phản ánh cách phân bổ vốn khác nhau.`,
    ),
  );
  if (!ok) {
    box.append(
      node(
        "p",
        "cov-warning",
        `S của A tính lại ở trình duyệt (${vSigned(A.score, 6)}) không khớp số backend (${vSigned(data.portfolio.score, 6)}). Không hiện phần so sánh; hãy báo lại lỗi này.`,
      ),
    );
    resultPanel.append(box);
    resultPanel.classList.remove("hidden");
    return;
  }
  const cards = node("div", "cov-ab-grid");
  cards.append(abCard("A", A), abCard("B", B), deltaCard(A, B));
  box.append(cards, duplicateCaveat());
  const facts = node("div", "cov-facts");
  facts.append(
    fact("Mã có tin trong lô", `${data.holdings.filter((h) => h.has_news).length}/${data.holdings.length} mã`, "tính trên mọi mã của A và B"),
    fact("Tiêu đề được chấm", `${data.holdings.reduce((sum, h) => sum + (h.n || 0), 0)} tiêu đề`, `${funnelSentence(funnelTotals(data.holdings))} Dùng chung cho A và B.`),
    fact("Dữ liệu", info.mode, info.text),
  );
  box.append(facts, hasNewsNote());
  resultPanel.append(box);

  resultPanel.append(sameBatchComparison(data, compare.weightsA, "A"), sameBatchComparison(data, compare.weightsB, "B"));

  // Biểu đồ chính: một biểu đồ, ba cách xem.
  const canDelta = A.score !== null && A.score !== undefined && B.score !== null && B.score !== undefined;
  const panels = [
    ["delta", "Vì sao B khác A", canDelta ? deltaChart(A, B) : null, "Mỗi thanh = (phần vốn trong phần có tin ở B − ở A) × điểm mã. Khi cả hai danh mục đủ 100% vốn có tin, đây đúng là (vốn ở B − vốn ở A) × điểm mã. Cộng các thanh ra đúng S của B − S của A. Mã không tìm thấy tin để xám, không có thanh."],
    ["A", "Đóng góp trong A", contributionChart(A), null],
    ["B", "Đóng góp trong B", contributionChart(B), null],
  ].filter(([, , chart]) => chart);
  const section = chartSection("Mã nào tạo ra chênh lệch S giữa A và B");
  const switcher = node("div", "cov-switch");
  switcher.setAttribute("role", "group");
  switcher.setAttribute("aria-label", "Cách xem biểu đồ");
  const bodies = [];
  panels.forEach(([key, label, chart, intro], index) => {
    const button = node("button", "", label);
    button.type = "button";
    button.dataset.view = key;
    button.setAttribute("aria-pressed", String(index === 0));
    switcher.append(button);
    const body = node("div", `cov-switch-panel${index === 0 ? "" : " hidden"}`);
    body.dataset.view = key;
    body.append(key === "delta" ? node("p", "cov-chart-intro", intro) : contributionIntro(key === "A" ? A : B), chart);
    bodies.push(body);
  });
  switcher.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    for (const other of switcher.querySelectorAll("button")) other.setAttribute("aria-pressed", String(other === button));
    for (const body of bodies) body.classList.toggle("hidden", body.dataset.view !== button.dataset.view);
  });
  section.append(switcher, ...bodies);
  resultPanel.append(section);

  resultPanel.append(observedScopeSection([{ label: "A", view: A }, { label: "B", view: B }]));

  const extra = [];
  if (canDelta) {
    const terms = A.rows
      .map((rowA, index) => ({ rowA, rowB: B.rows[index] }))
      .filter(({ rowA, rowB }) => rowA.h.has_news && (rowA.w > 0 || rowB.w > 0));
    extra.push(
      `S của B − S của A = ${terms.map(({ rowA, rowB }) => `(${viDigits(rowB.r ?? 0, 6)} − ${viDigits(rowA.r ?? 0, 6)}) × (${vSigned(rowA.h.score, 6)})`).join(" + ")} = ${vSigned(B.score - A.score, 6)}`,
    );
  }
  extra.push(
    `Kiểm tra: S của A tính lại ở trình duyệt = ${vSigned(A.score, 6)}, backend trả về ${vSigned(data.portfolio.score, 6)}; C của A ${viDigits(A.coverage, 6)} và ${viDigits(data.portfolio.coverage, 6)}. Khớp (chênh dưới 10⁻⁹). B dùng đúng các điểm mã đó với phần vốn của B.`,
  );
  resultPanel.append(referenceSection(data, { compareMode: true, calc: { views: [{ label: "A", view: A }, { label: "B", view: B }], extra } }));
  resultPanel.append(node("p", "cov-disclaimer", data.disclaimer));
  resultPanel.classList.remove("hidden");
}

function renderCoverageResult(data, compare = null) {
  headlineCap = (data.config && data.config.max_headlines_per_holding) ?? null;
  if (compare) renderCoverageCompare(data, compare);
  else renderCoverageSingle(data);
}

// ---------- Ô nhập: một danh mục, hoặc A/B dùng chung danh sách mã ----------
const compareToggle = $("#compareToggle");
const positionRows = $("#positionRows");

function setCompareMode(on) {
  positionRows.classList.toggle("compare", on);
  for (const element of document.querySelectorAll("#weightedPanel .compare-only")) element.classList.toggle("hidden", !on);
  $("#weightHeadA").textContent = on ? "Danh mục A (%)" : "Phần vốn (%)";
  $("#weightedSubmitText").textContent = on ? "So hai danh mục" : "Xem sắc thái theo vốn";
}

compareToggle.addEventListener("change", () => setCompareMode(compareToggle.checked));
setCompareMode(compareToggle.checked);

$("#comparePreset").addEventListener("click", () => {
  const example = [
    ["COMI", 20, 50],
    ["ETEL", 20, 30],
    ["FWRY", 20, 20],
    ["ADIB", 20, 0],
    ["EFIH", 20, 0],
  ];
  const symbols = document.querySelectorAll("#positionRows input[name=symbol]");
  const weightsA = document.querySelectorAll("#positionRows input[name=weight]");
  const weightsB = document.querySelectorAll("#positionRows input[name=weightB]");
  example.forEach(([symbol, a, b], index) => {
    symbols[index].value = symbol;
    weightsA[index].value = String(a);
    weightsB[index].value = String(b);
  });
});

$("#weightedForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const symbols = [...document.querySelectorAll("#positionRows input[name=symbol]")];
  const wa = [...document.querySelectorAll("#positionRows input[name=weight]")];
  const wb = [...document.querySelectorAll("#positionRows input[name=weightB]")];
  const rows=symbols.map((el,i)=>({symbol:el.value.trim().toUpperCase(),weight:Number(wa[i].value||0),b:Number(wb[i].value||0)})).filter(p=>p.symbol);
  const positions=rows.map(({symbol,weight})=>({symbol,weight}));
  const B=compareToggle.checked ? rows.map(p=>({symbol:p.symbol,weight:p.b})) : null;
  if ([positions,...(B?[B]:[])].some(ps=>ps.some(p=>!Number.isFinite(p.weight)||p.weight<0)||!ps.some(p=>p.weight>0))) {renderError({error:{message:'Mỗi danh mục cần vốn không âm và tổng lớn hơn 0.'}});return;}
  useOriginalPortfolio(rows.map(p=>p.symbol),event.submitter,data=>renderOriginalCapital(data,positions,B));
});

function tgNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "Chưa có dữ liệu";
  const number = Number(value);
  if (!Number.isFinite(number)) return "Chưa có dữ liệu";
  return number.toLocaleString("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 4) });
}

function tgPercent(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "Chưa đủ lịch sử";
  const number = Number(value) * 100;
  return (number > 0 ? "+" : "") + number.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";
}

function tgMetricCard(title, value, explanation, className = "") {
  const card = node("article", "tg-card tg-metric-card");
  card.append(node("div", "tg-card-label", title));
  card.append(node("strong", "tg-metric-value " + className, value));
  card.append(node("p", "tg-metric-explanation", explanation));
  return card;
}

function tgRuleRow(code, title, condition, label, note, activeCode) {
  const row = node("article", "tg-rule-row" + (code === activeCode ? " active" : ""));
  row.append(node("span", "tg-rule-label", label));
  const body = node("div", "tg-rule-copy");
  body.append(node("strong", "", title));
  body.append(node("p", "", condition));
  if (note) body.append(node("small", "", note));
  row.append(body);
  if (code === activeCode) row.append(node("span", "tg-rule-current", "Nhánh đang áp dụng"));
  return row;
}

function tgInferRulePath(decision) {
  if (decision.rule_path) return decision.rule_path;
  return null; // Backend owns the versioned classification trace.
}

function renderTinGiaMethod(decision) {
  const inputs = decision.inputs || {};
  const params = decision.parameters || {};
  const method = node("section", "tg-method tg-method-open");
  method.append(node("h3", "", "Cách hệ thống đi từ dữ liệu đến nhãn"));
  method.append(node("p", "tg-section-lead", "Đây là bộ quy tắc minh bạch để tham khảo cho người đang nắm cổ phiếu. FinBERT chấm sắc thái câu chữ; phần giá cho biết diễn biến đã quan sát. Kết quả chưa phải dự báo hay bằng chứng rằng tin gây ra biến động giá."));

  const steps = node("div", "tg-method-steps");
  const stepData = [
    ["1", "Chấm từng tiêu đề", "Điểm bài = xác suất FinBERT chấm tích cực trừ xác suất chấm tiêu cực. Điểm nằm từ −1 (tiêu cực) đến +1 (tích cực)."],
    ["2", "Gộp bài gần trùng", "Tiêu đề có độ giống nhau từ 80% trong khoảng 3 ngày được gom tạm; điểm nhóm là trung bình các điểm bài. Đây chưa phải xác nhận cùng một sự kiện."],
    ["3", "Giảm ảnh hưởng tin cũ", "Trọng số = 2 mũ (−số ngày tuổi ÷ 7): tin 7 ngày tuổi còn 1/2 trọng số; 14 ngày tuổi còn 1/4. Chỉ lấy tin công ty đã xác minh, đăng trước ngày giá ít nhất 1 ngày và không quá 30 ngày."],
    ["4", "Ghép với diễn biến giá", "Tính sắc thái S bằng trung bình có trọng số, độ mới F bằng trung bình trọng số, rồi dùng D = S × F để xét nhãn cùng biến động giá 5 phiên và ngưỡng lịch sử riêng của mã."],
  ];
  for (const [number, title, description] of stepData) {
    const item = node("article", "tg-method-step");
    item.append(node("span", "tg-method-step-number", number));
    const copy = node("div", "");
    copy.append(node("strong", "", title), node("p", "", description));
    item.append(copy);
    steps.append(item);
  }
  method.append(steps);
  method.append(node("p", "tg-context-separation", "Tin vĩ mô và tin ngoài công ty vẫn được hiển thị riêng để người dùng đọc, nhưng chưa cộng vào điểm mã cổ phiếu: hệ thống chưa biết từng doanh nghiệp phơi nhiễm với tin đó ở mức nào, hoặc tin có bất ngờ so với kỳ vọng ra sao. Tin cùng ngày giá chưa rõ thứ tự và tin đăng sau ngày giá cũng không vào nhãn."));

  const band = node("section", "tg-rulebook");
  band.append(node("h3", "", "Bảng quy tắc gán 5 nhãn"));
  band.append(node("p", "tg-section-lead", "D = S × F là điểm dùng xét nhãn sau giảm theo độ mới; S là sắc thái, F là độ mới tuyệt đối; R5 là phần trăm thay đổi giá trong 5 phiên; B là ngưỡng biến động thường gặp của mã; E là ngưỡng biến động cực đoan. So sánh được thực hiện theo đúng thứ tự trong bảng."));
  const activeCode = decision.rule_path?.code || (decision.label ? "" : "insufficient");
  const moderate = Number.isFinite(Number(params.sentiment_moderate)) ? Number(params.sentiment_moderate) : 0.2;
  const strong = Number.isFinite(Number(params.sentiment_strong)) ? Number(params.sentiment_strong) : 0.6;
  const minGroups = Number.isFinite(Number(params.strong_min_effective_groups)) ? Number(params.strong_min_effective_groups) : 3;
  const rules = node("div", "tg-rule-list");
  const rows = [
    ["insufficient", "Chưa đủ dữ liệu", "Chưa có giá đóng cửa và đủ lịch sử, hoặc không có nhóm tin công ty hợp lệ trong cửa sổ phân tích.", "Chưa gán nhãn", "Thiếu dữ liệu không được tự đổi thành Giữ."],
    ["neutral_sentiment", "Điểm tin chưa nghiêng rõ", `−${moderate.toFixed(2)} < D < +${moderate.toFixed(2)}.`, "Giữ", "Nhánh cân bằng; giá được trình bày để đối chiếu nhưng không đổi nhãn."],
    ["positive_avoid_chasing", "Tin tích cực nhưng giá đã tăng mạnh", `D ≥ +${moderate.toFixed(2)} và R5 > +B.`, "Giữ", "Tránh mua đuổi sau mức tăng lớn so với lịch sử của mã."],
    ["positive_price_conflict", "Tin tích cực nhưng giá giảm mạnh", `D ≥ +${moderate.toFixed(2)} và R5 < −B.`, "Giữ", "Tin và giá trái chiều; quy tắc chờ thêm."],
    ["buy_strong", "Tin tích cực mạnh, giá tăng vừa phải, đủ số nhóm", `D ≥ +${strong.toFixed(2)}, 0 < R5 ≤ +B và số nhóm tin hiệu dụng ≥ ${minGroups}.`, "Mua mạnh", "Nếu thiếu một trong các điều kiện mạnh thì chuyển xuống Mua."],
    ["buy", "Tin tích cực, giá chưa tăng/giảm quá ngưỡng", `D ≥ +${moderate.toFixed(2)}, −B ≤ R5 ≤ +B và không đồng thời đủ điều kiện Mua mạnh.`, "Mua", "Dành cho người đang nắm giữ: cân nhắc mua thêm theo quy tắc."],
    ["sell_strong", "Tin tiêu cực mạnh và giá giảm đáng kể", `D ≤ −${strong.toFixed(2)}, R5 < −B và số nhóm tin hiệu dụng ≥ ${minGroups}.`, "Bán mạnh", "Nếu thiếu điều kiện về điểm tin hoặc số nhóm thì chuyển xuống Bán."],
    ["sell", "Tin tiêu cực, giá giảm quá ngưỡng thường gặp", `D ≤ −${moderate.toFixed(2)} và R5 < −B, nhưng chưa đủ điều kiện Bán mạnh.`, "Bán", "Dành cho người đang nắm giữ: cân nhắc giảm vị thế theo quy tắc."],
    ["negative_no_confirmation", "Tin tiêu cực nhưng giá chưa giảm đáng kể", `D ≤ −${moderate.toFixed(2)} và R5 ≥ −B.`, "Giữ", "Chưa có xác nhận giảm giá theo ngưỡng lịch sử của mã."],
  ];
  for (const [code, title, condition, label, note] of rows) rules.append(tgRuleRow(code, title, condition, label, note, activeCode));
  band.append(rules);
  method.append(band);

  const provenance = node("section", "tg-threshold-notes");
  provenance.append(node("h3", "", "Các ngưỡng lấy từ đâu?"));
  const sources = node("div", "tg-threshold-grid");
  const normal = inputs.normal_move;
  const extreme = inputs.extreme_move;
  sources.append(tgMetricCard("B · NGƯỠNG BIẾN ĐỘNG THƯỜNG", tgPercent(normal), "Phân vị 75% của độ lớn tuyệt đối các biến động 5 phiên trong khoảng một năm lịch sử của chính mã này. Khoảng 3/4 biến động cũ nhỏ hơn B; quy tắc so với cả +B lẫn −B."));
  sources.append(tgMetricCard("E · NGƯỠNG BIẾN ĐỘNG CỰC ĐOAN", tgPercent(extreme), "Phân vị 90% của độ lớn tuyệt đối các biến động 5 phiên trong cùng lịch sử. Dùng để nhận diện biến động lớn theo cả hai chiều (|R5| > E); không chứng minh giá đắt/rẻ hay sắp đảo chiều."));
  sources.append(tgMetricCard("±0,20 / ±0,60 · NGƯỠNG ĐIỂM TIN", "Quy ước thử nghiệm", "±0,20 phân cách vùng cân bằng với vùng tin nghiêng hướng; ±0,60 là điều kiện sắc thái mạnh. Đây là các mốc thiết kế ban đầu, chưa được hiệu chỉnh bằng kiểm định lịch sử EGX."));
  sources.append(tgMetricCard("7 / 30 NGÀY · ĐỘ MỚI CỦA TIN", "Quy ước thử nghiệm", "7 ngày là thời gian để trọng số giảm còn một nửa; 30 ngày là giới hạn tuổi tin. Hai mốc này chưa được hiệu chỉnh hoặc kiểm định trên dữ liệu EGX của dự án."));
  provenance.append(sources);
  method.append(provenance);

  const formulas = node("div", "tg-formula-explainer");
  formulas.append(node("h4", "", "Cách tính các con số đang thấy"));
  const formulaList = document.createElement("ul");
  const formulaLines = [
    "Điểm một bài = xác suất tích cực − xác suất tiêu cực.",
    "Điểm một nhóm = trung bình điểm của các tiêu đề được gom tạm vào nhóm.",
    "Trọng số tuổi tin = 2 mũ (−số ngày tuổi ÷ 7); ví dụ tin 7 ngày tuổi có trọng số 0,5.",
    "S = tổng (trọng số × điểm nhóm) ÷ tổng trọng số; F = tổng trọng số ÷ số nhóm; D = S × F. Bảng nhãn dùng D, nên cả lô tin cũ sẽ yếu dần.",
    "Thay đổi giá R5 = (giá đóng cửa điều chỉnh mới nhất ÷ giá đóng cửa điều chỉnh cách đó 5 phiên − 1) × 100%.",
    "Số nhóm hiệu dụng = (tổng trọng số)² ÷ tổng bình phương từng trọng số; số này giảm khi trọng số tập trung ở ít nhóm tin.",
  ];
  for (const line of formulaLines) formulaList.append(node("li", "", line));
  const math = node('div', 'tg-math');
  math.innerHTML = '<math display="block"><mi>S</mi><mo>=</mo><mfrac><mrow><mo>∑</mo><msub><mi>w</mi><mi>g</mi></msub><msub><mi>s</mi><mi>g</mi></msub></mrow><mrow><mo>∑</mo><msub><mi>w</mi><mi>g</mi></msub></mrow></mfrac><mo>;</mo><mi>F</mi><mo>=</mo><mfrac><mrow><mo>∑</mo><msub><mi>w</mi><mi>g</mi></msub></mrow><mi>m</mi></mfrac><mo>;</mo><mi>D</mi><mo>=</mo><mi>S</mi><mo>×</mo><mi>F</mi></math>';
  formulas.append(math);
  formulas.append(formulaList);
  if (inputs.effective_groups !== undefined) formulas.append(node("p", "tg-card-note", `Trong kết quả hiện tại: ${tgNumber(inputs.effective_groups, 2)} nhóm tin hiệu dụng; điều kiện nhãn mạnh là từ ${minGroups} nhóm trở lên. Đây không nhất thiết bằng tổng số bài báo.`));
  method.append(formulas);

  const caution = node("p", "tg-method-caution", "Phân vị B/E được tính từ lịch sử giá của từng mã; các mốc điểm tin, độ tuổi tin, cách gom tiêu đề và số nhóm tối thiểu là quy ước thiết kế thử nghiệm. Chưa có kiểm định ngoài mẫu hay bằng chứng lợi nhuận, vì vậy độ nhạy ổn định chỉ có nghĩa nhãn không đổi trong 9 cấu hình lân cận đã thử; không chứng minh phương pháp hiệu quả.");
  method.append(caution);
  return method;
}

function tgScoreCard(title, group, note) {
  const card = node("article", "tg-card");
  card.append(node("div", "tg-card-label", title));
  if (group && group.aggregation_status === "not_aggregated_heterogeneous_context") {
    card.append(node("strong", "tg-score-value tg-muted", `${group.count} bài được chấm riêng`));
    card.append(node("p", "", "Không cộng thành một điểm chung: các tin chính sách, thị trường và địa chính trị không cùng một loại tác động."));
    card.append(node("p", "tg-card-note", note));
    return card;
  }
  if (group && group.aggregation_status === "not_aggregated_events_unresolved") {
    card.append(node("strong", "tg-score-value tg-muted", `${group.count} headline đang rà soát`));
    card.append(node("p", "", "Đây là danh sách tiêu đề đã chấm trước bước chọn tin cho quyết định. Điểm S phía trên chỉ dùng tập con đủ điều kiện ngày đăng và nhóm tiêu đề tạm; danh sách này không có điểm tổng riêng."));
    card.append(node("p", "tg-card-note", note));
    return card;
  }
  if (!group || group.score === null || group.score === undefined) {
    card.append(node("strong", "tg-score-value tg-muted", "Chưa có điểm"));
    card.append(node("p", "", "Chưa có tiêu đề được chấm trong nhóm này."));
    card.append(node("p", "tg-card-note", note));
    return card;
  }
  const score = Math.max(-1, Math.min(1, Number(group.score)));
  const tone = score > 0 ? "tg-positive" : score < 0 ? "tg-negative" : "tg-muted";
  card.append(node("strong", "tg-score-value " + tone, (score > 0 ? "+" : "") + score.toFixed(3)));
  card.append(node("span", "tg-count", group.count + " tiêu đề được chấm"));
  const rail = node("div", "tg-score-rail");
  const fill = node("span", "tg-score-fill " + (score >= 0 ? "positive" : "negative"));
  fill.style.left = score >= 0 ? "50%" : (50 + score * 50) + "%";
  fill.style.width = Math.abs(score) * 50 + "%";
  rail.append(fill, node("span", "tg-score-center"));
  card.append(
    rail,
    node("div", "tg-score-axis", "−1 tiêu cực · 0 trung tính · +1 tích cực"),
    node("p", "tg-card-note", note),
  );
  const published = (group.headlines || [])
    .map((row) => row.published_at)
    .filter((value) => value && !Number.isNaN(new Date(value).getTime()))
    .map((value) => new Date(value))
    .sort((a, b) => a - b);
  if (published.length) {
    const newest = published[published.length - 1].toISOString();
    const oldest = published[0].toISOString();
    card.append(node("p", "tg-card-note", `Ngày đăng trong lô: mới nhất ${formatAge(newest)}, cũ nhất ${formatAge(oldest)}.`));
  } else {
    card.append(node("p", "tg-card-note", "Nguồn không cung cấp ngày đăng đủ tin cậy để tính tuổi bài."));
  }
  return card;
}

function tgPriceChart(history, quoteValues) {
  const dailyOnly = !quoteValues?.as_of;
  if (dailyOnly && (history || []).length >= 2) {
    quoteValues = { last: history.at(-1).close, as_of: history.at(-1).date, daily_only: true };
  }
  const quoteDate = quoteValues && quoteValues.as_of ? quoteValues.as_of.slice(0, 10) : "";
  const prior = (history || []).filter((bar) => bar.date < quoteDate && Number.isFinite(Number(bar.close))).slice(-6);
  if (prior.length < 2 || !quoteValues || !Number.isFinite(Number(quoteValues.last))) {
    return node("p", "tg-card-note", "Biểu đồ cần ít nhất hai phiên giá đóng cửa trước ngày của snapshot.");
  }
  const values = prior.map((bar) => Number(bar.close)).concat(Number(quoteValues.last));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || Math.max(Math.abs(max) * 0.01, 0.01);
  const left = 36, right = 600, top = 16, bottom = 168;
  const pointX = (index) => left + (right - left) * index / Math.max(values.length - 1, 1);
  const pointY = (value) => bottom - (value - min) / spread * (bottom - top);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 620 205");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", dailyOnly ? "Giá đóng cửa các phiên gần đây" : "Giá đóng cửa các phiên trước và snapshot bị trễ mới nhất");
  for (let i = 0; i < 3; i += 1) {
    const y = top + (bottom - top) * i / 2;
    const line = document.createElementNS(svg.namespaceURI, "line");
    line.setAttribute("x1", String(left)); line.setAttribute("x2", String(right));
    line.setAttribute("y1", String(y)); line.setAttribute("y2", String(y));
    line.setAttribute("class", "tg-chart-grid"); svg.append(line);
  }
  const path = document.createElementNS(svg.namespaceURI, "polyline");
  path.setAttribute("points", values.map((value, index) => pointX(index) + "," + pointY(value)).join(" "));
  path.setAttribute("class", "tg-chart-line"); svg.append(path);
  values.forEach((value, index) => {
    const circle = document.createElementNS(svg.namespaceURI, "circle");
    circle.setAttribute("cx", String(pointX(index))); circle.setAttribute("cy", String(pointY(value)));
    circle.setAttribute("r", index === values.length - 1 ? "5" : "3.5");
    circle.setAttribute("class", index === values.length - 1 ? "tg-chart-current" : "tg-chart-close");
    const title = document.createElementNS(svg.namespaceURI, "title");
    title.textContent = (index === values.length - 1 ? (dailyOnly ? quoteDate : "Snapshot trễ") : prior[index].date) + ": " + tgNumber(value, 3) + " EGP";
    circle.append(title); svg.append(circle);
  });
  const labels = node("div", "tg-chart-labels");
  labels.append(node("span", "", prior[0].date), node("span", "", dailyOnly ? "Đóng cửa · " + quoteDate : "Snapshot · " + formatClock(quoteValues.as_of, false)));
  const wrap = node("div", "tg-chart-wrap");
  wrap.append(svg, labels, node("p", "tg-card-note", dailyOnly ? "Đường nối các mức đóng cửa đã quan sát; chưa phản ánh giá trong phiên hoặc dự báo." : "Giá đóng cửa lịch sử và snapshot trễ là hai loại mốc; đường nối chỉ giúp quan sát, không phải đường dự báo."));
  return wrap;
}

function addTinGiaHeadlines(title, group, categoryLabel) {
  const rows = group && group.headlines ? group.headlines : [];
  if (!rows.length) {
    resultPanel.append(node("p", "tg-card-note", "Chưa có tin " + categoryLabel.toLowerCase() + " được chấm trong lô hiện tại."));
    return;
  }
  const disclosure = node("details", "tg-news-details");
  disclosure.append(node("summary", "", `${title} · xem ${rows.length} tiêu đề`));
  disclosure.append(node("p", "tg-card-note", "Danh sách này chỉ gồm headline đã chấm. Mở “Nhật ký ứng viên trước xử lý” bên dưới để xem cả bản ghi chưa chấm, bị loại, trùng và trạng thái truy vấn nguồn."));
  const list = node("div", "headline-list");
  for (const item of rows) {
    const card = node("article", "headline");
    const main = document.createElement("div");
    const headlineTitle = node("div", "headline-title");
    headlineTitle.append(safeLink(item.url, item.title) || item.title || "Không có tiêu đề");
    main.append(headlineTitle);
    const meta = node("div", "headline-meta");
    meta.append(node("span", "time-chip", item.published_at ? `Đăng ${formatClock(item.published_at)} · ${formatAge(item.published_at)}` : "Nguồn không ghi ngày đăng"));
    meta.append(node("span", "source-chip", item.source || "Không rõ nguồn"));
    meta.append(node("span", "kind-chip", categoryLabel));
    if (item.symbol) meta.append(node("span", "kind-chip", item.symbol));
    main.append(meta);
    if (item.probabilities) {
      const positive = Number(item.probabilities.positive || 0);
      const negative = Number(item.probabilities.negative || 0);
      const neutral = Number(item.probabilities.neutral || 0);
      const scores = node("div", "headline-scores");
      scores.textContent = `Tích cực ${percent(positive)} · Tiêu cực ${percent(negative)} · Trung tính ${percent(neutral)} · s = ${(positive - negative).toFixed(3)}`;
      main.append(scores);
    }
    card.append(main);
    if (item.url && /^https:\/\//i.test(item.url)) {
      const link = node("a", "", "Mở nguồn ↗");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
    }
    list.append(card);
  }
  disclosure.append(list);
  resultPanel.append(disclosure);
}

function addTinGiaExcluded(rows) {
  if (!rows || !rows.length) return;
  const disclosure = node("details", "tg-news-details");
  disclosure.append(node("summary", "", `Bản ghi không tính vào điểm headline · ${rows.length}`));
  disclosure.append(node("p", "tg-card-note", "Các bản ghi này vẫn được giữ để giải thích bộ lọc Tin + Giá. Chúng không bị xóa khỏi lô gốc của C3."));
  const list = node("div", "headline-list");
  for (const item of rows) {
    const card = node("article", "headline");
    const main = document.createElement("div");
    const headlineTitle = node("div", "headline-title");
    headlineTitle.append(safeLink(item.url, item.title) || item.title || "Không có tiêu đề");
    main.append(headlineTitle);
    const meta = node("div", "headline-meta");
    meta.append(node("span", "kind-chip", "Không tính vào điểm"));
    meta.append(node("span", "source-chip", item.source || "Không rõ nguồn"));
    if (item.published_at) meta.append(node("span", "time-chip", `Đăng ${formatClock(item.published_at)} · ${formatAge(item.published_at)}`));
    main.append(meta, node("p", "tg-exclusion-reason", item.reason || "Không đạt điều kiện sử dụng trong điểm headline."));
    card.append(main);
    list.append(card);
  }
  disclosure.append(list);
  resultPanel.append(disclosure);
}

function addTinGiaCandidateLedger(ledger) {
  if (!ledger) return;
  const counts = ledger.counts || {};
  const candidates = ledger.candidates || [];
  const queries = ledger.provider_queries || [];
  const disclosure = node("details", "tg-news-details tg-candidate-ledger");
  disclosure.append(node(
    "summary",
    "",
    `Nhật ký ứng viên trước xử lý · ${counts.received || 0} bản ghi · ${counts.scored || 0} đã chấm · ${counts.unresolved || 0} chưa phân xử · ${counts.excluded || 0} loại · ${counts.grouped || 0} trùng`
  ));
  disclosure.append(node("p", "tg-card-note", ledger.source_scope_note || "Nhật ký phản ánh các response trong lượt gọi hiện tại."));
  disclosure.append(node("p", "tg-card-note", `${ledger.retention_note || ""} Phiên bản luật: ${ledger.filter_version || "—"}.`));

  const queryHeading = node("h4", "tg-ledger-heading", "Trạng thái truy vấn nguồn");
  disclosure.append(queryHeading);
  if (!queries.length) {
    disclosure.append(node("p", "tg-card-note", "Không có truy vấn nguồn được ghi nhận."));
  } else {
    const queryList = node("ul", "tg-query-list");
    const statusText = {
      available: "Có response",
      failed: "Lỗi gọi nguồn",
      skipped_missing_api_key: "Chưa cấu hình khóa",
    };
    for (const query of queries) {
      const item = document.createElement("li");
      const top = node("div", "tg-query-top");
      top.append(node("strong", "", query.query_id || query.provider || "Truy vấn"));
      top.append(node("span", "tg-ledger-state " + (query.status === "available" ? "available" : query.status === "failed" ? "failed" : ""), statusText[query.status] || query.status || "Không rõ"));
      item.append(top);
      const detail = `Nguồn ${query.provider || "—"} · ${query.scope === "company_candidate" ? "truy vấn theo công ty" : "truy vấn bối cảnh"} · response ${query.candidate_count_before_filter ?? 0} bản ghi · đã ghi ${query.candidate_count_after_review ?? 0} · chấm ${query.scored_count ?? 0} · loại ${query.excluded_count ?? 0} · trùng ${query.grouped_count ?? 0}`;
      item.append(node("span", "tg-card-note", detail));
      if (query.error_type) item.append(node("span", "tg-ledger-error", `Lỗi kỹ thuật: ${query.error_type}`));
      const queryLink = safeLink(query.query_url, "Mở truy vấn ↗");
      if (queryLink) item.append(queryLink);
      queryList.append(item);
    }
    disclosure.append(queryList);
  }

  disclosure.append(node("h4", "tg-ledger-heading", "Từng bản ghi nguồn trả về"));
  if (!candidates.length) {
    disclosure.append(node("p", "tg-card-note", "Lượt này chưa có bản ghi nào để phân loại."));
  } else {
    const stateLabels = {
      unresolved: "Chưa phân xử",
      context: "Giữ làm bối cảnh",
      excluded: "Loại khỏi điểm headline",
      grouped: "Trùng chính xác · nối bản gốc",
    };
    const list = node("div", "headline-list tg-ledger-rows");
    for (const candidate of candidates) {
      const card = node("article", "headline tg-ledger-row");
      const main = document.createElement("div");
      const title = node("div", "headline-title");
      title.append(safeLink(candidate.url, candidate.title) || candidate.title || "(Nguồn không trả tiêu đề)");
      main.append(title);
      const meta = node("div", "headline-meta");
      meta.append(node("span", "source-chip", candidate.source || "Không rõ nguồn"));
      meta.append(node("span", "kind-chip", candidate.scope === "company_candidate" ? "Kết quả truy vấn công ty" : "Kết quả truy vấn bối cảnh"));
      meta.append(node("span", "tg-ledger-state", stateLabels[candidate.processing_state] || candidate.processing_state || "Chưa rõ trạng thái"));
      meta.append(node("span", "time-chip", candidate.published_at ? `Đăng ${formatClock(candidate.published_at)} · ${formatAge(candidate.published_at)}` : "Nguồn không ghi ngày đăng"));
      meta.append(node("span", "time-chip", `Nhận ${formatClock(candidate.retrieved_at)}`));
      main.append(meta);
      main.append(node("p", "tg-exclusion-reason", candidate.reason || "Chưa có giải thích."));
      if (candidate.canonical_record_id) main.append(node("p", "tg-card-note", `Bản trùng được nối về mã bản ghi ${candidate.canonical_record_id}.`));
      if (candidate.probabilities) {
        const p = candidate.probabilities;
        main.append(node("div", "headline-scores", `FinBERT headline · Tích cực ${percent(p.positive)} · Tiêu cực ${percent(p.negative)} · Trung tính ${percent(p.neutral)} · s = ${Number(candidate.sentiment_score).toFixed(3)} · chưa phải tác động giá.`));
      }
      card.append(main);
      const queryLink = safeLink(candidate.query_url, "Truy vấn ↗");
      if (queryLink) card.append(queryLink);
      list.append(card);
    }
    disclosure.append(list);
  }
  resultPanel.append(disclosure);
}

function renderTinGiaResult(data) {
  resultPanel.replaceChildren();
  const rulePath = tgInferRulePath(data.decision);
  const top = node("div", "result-head");
  const heading = document.createElement("div");
  heading.append(node("div", "result-kicker", "Đối chiếu tin tức với giá quan sát · EGX"));
  heading.append(node("h2", "", data.symbol));
  heading.append(node("p", "result-subtitle", "Lượt lấy dữ liệu: " + formatClock(data.requested_at) + " · tiền tệ " + (data.currency || "EGP")));
  const decisionLabel = data.decision.label || "Chưa đủ dữ liệu";
  const labelTone = decisionLabel.includes("Mua") ? "sentiment-bullish" : decisionLabel.includes("Bán") ? "sentiment-bearish" : "sentiment-insufficient";
  top.append(heading, node("span", "sentiment-pill " + labelTone, decisionLabel));
  resultPanel.append(top);

  const decision = node("section", "tg-decision tg-verdict-card");
  const verdictHeader = node("div", "tg-verdict-header");
  const verdictCopy = node("div", "");
  verdictCopy.append(node("div", "tg-card-label", data.decision.label ? "KẾT LUẬN THEO QUY TẮC THỬ NGHIỆM" : "CHƯA ĐỦ DỮ LIỆU ĐỂ GÁN NHÃN"));
  verdictCopy.append(node("strong", "tg-verdict-title", data.decision.label || "Chưa gán Mua / Giữ / Bán"));
  verdictCopy.append(node("p", "tg-verdict-meaning", data.decision.method_note || "Nhãn dành cho người đang nắm cổ phiếu; chưa chứng minh hiệu quả đầu tư."));
  verdictHeader.append(verdictCopy);
  decision.append(verdictHeader);
  decision.append(node("p", "tg-verdict-message", data.decision.message || "Cần đủ giá lịch sử và nhóm tin công ty hợp lệ trước khi bộ quy tắc có thể gán nhãn."));
  const ruleInputs = data.decision.inputs;
  if (ruleInputs) {
    const metrics = node("div", "tg-current-metrics");
    metrics.append(tgMetricCard("ĐIỂM XÉT NHÃN · D = S × F", tgNumber(ruleInputs.sentiment, 4), "Điểm sắc thái đã giảm theo độ mới tuyệt đối. Mốc xét nhãn thử nghiệm là ±0,20 và ±0,60.", Number(ruleInputs.sentiment) > 0 ? "tg-positive" : Number(ruleInputs.sentiment) < 0 ? "tg-negative" : ""));
    metrics.append(tgMetricCard("GIÁ 5 PHIÊN · R5", tgPercent(ruleInputs.five_session_return), "Thay đổi giữa hai giá đóng cửa cách nhau 5 phiên hoàn tất; đây là biến động đã quan sát, không phải dự báo.", Number(ruleInputs.five_session_return) > 0 ? "tg-positive" : Number(ruleInputs.five_session_return) < 0 ? "tg-negative" : ""));
    metrics.append(tgMetricCard("NGƯỠNG THƯỜNG · B", tgPercent(ruleInputs.normal_move), "Mã này thường biến động trong vùng này trở xuống theo phân vị 75% lịch sử 5 phiên."));
    metrics.append(tgMetricCard("NGƯỠNG CỰC ĐOAN · E", tgPercent(ruleInputs.extreme_move), "Mốc phân vị 90% lịch sử 5 phiên; chỉ dùng để nhận diện biến động hiếm gặp."));
    metrics.append(tgMetricCard("NHÓM TIN HIỆU DỤNG", tgNumber(ruleInputs.effective_groups, 2), `Số nhóm sau khi xét trọng số tuổi tin; điều kiện nhãn mạnh cần từ ${data.decision.parameters?.strong_min_effective_groups || 3} nhóm.`));
    decision.append(metrics);
    decision.append(node('p', 'tg-section-lead', `Sắc thái S = ${tgNumber(ruleInputs.raw_sentiment, 4)}; độ mới F = ${tgNumber(ruleInputs.freshness, 4)}; D = S × F = ${tgNumber(ruleInputs.sentiment, 4)}. Tuổi tin tính đến ngày giá ${ruleInputs.price_date}.`));
    if (data.decision.risk) decision.append(node('p', 'tg-current-path', `Trạng thái biến động: ${({ordinary:'Chưa vượt B',elevated:'Vượt B',extreme:'Vượt E — cực đoan'})[data.decision.risk.level] || data.decision.risk.level}. ${data.decision.risk.message}`));
    const sensitivity = data.decision.sensitivity?.stable
      ? "Nhãn giữ nguyên trong 9 cấu hình lân cận đã thử. Đây chỉ là kiểm tra độ nhạy của quy tắc, không phải kiểm định khả năng sinh lời."
      : "Nhãn đổi khi thay các cấu hình lân cận đã thử; kết quả nhạy với tham số và cần được xem thận trọng.";
    decision.append(node("p", "tg-sensitivity-note", sensitivity));
  }

  if (rulePath) {
    const path = node("section", "tg-current-path");
    path.append(node("div", "tg-card-label", "VÌ SAO RA NHÃN NÀY? · NHÁNH ĐÃ KÍCH HOẠT"));
    path.append(node("h3", "", rulePath.title));
    path.append(node("p", "tg-current-condition", rulePath.condition));
    path.append(node("p", "", rulePath.meaning));
    decision.append(path);
  }

  const ruleDetails = node("details", "tg-method tg-group-details");
  const groupCount = (data.decision.groups || []).length;
  ruleDetails.append(node("summary", "", `Kiểm tra từng nhóm tin và đóng góp vào điểm tổng · ${groupCount} nhóm`));
  for (const group of data.decision.groups || []) {
    const block = node("section", "tg-card");
    block.append(node("strong", "", `${group.group_id} · ngày tin ${group.date} · điểm nhóm ${tgNumber(group.score, 3)} · tuổi ${group.age_days} ngày`));
    block.append(node("p", "", `Nhóm này chiếm ${(Number(group.normalized_weight || 0) * 100).toLocaleString("vi-VN", { maximumFractionDigits: 1 })}% tổng trọng số; đóng góp ${tgNumber(group.score_contribution, 4)} vào S. Giá đóng cửa trước ngày tin: ${group.price_before_news?.date || "chưa có mốc"} · ${tgNumber(group.price_before_news?.close, 3)} EGP.`));
    const reactions = group.observed_reaction || {};
    block.append(node("p", "", `Biến động giá quan sát sau ngày tin: 1 phiên ${tgPercent(reactions["1_sessions"]?.return)} · 3 phiên ${tgPercent(reactions["3_sessions"]?.return)} · 5 phiên ${tgPercent(reactions["5_sessions"]?.return)}.`));
    block.append(node("p", "tg-card-note", "Tính từ phiên đóng cửa trước ngày đăng tới 1/3/5 phiên sau ngày đăng. Đây chỉ là diễn biến cùng thời điểm, không thể quy phần trăm này cho bài báo; các cửa sổ có thể chồng lấn."));
    for (const member of group.members) block.append(safeLink(member.url, member.title) || node("p", "", member.title));
    block.append(node("p", "tg-card-note", "Gom theo độ giống tiêu đề và ngày đăng; đây là nhóm tạm, chưa xác minh các bài nói về cùng sự kiện."));
    ruleDetails.append(block);
  }
  for (const limitation of data.decision.limitations || []) ruleDetails.append(node("p", "tg-card-note", limitation));
  decision.append(ruleDetails);
  decision.append(node("p", "tg-verdict-footnote", "Lưu ý: thay đổi giá sau ngày tin được trình bày ở phần chi tiết như một đối chiếu theo thời gian, không khẳng định tin gây ra thay đổi. Dữ liệu hiện là giá đóng cửa theo ngày, không phải giá EGX thời gian thực."));
  resultPanel.append(decision);

  const price = data.price || {};
  if (price.status === "available") {
    const values = price.quote_values || {};
    const quote = price.quote || {};
    const grid = node("div", "tg-summary-grid");
    const quoteCard = node("article", "tg-card tg-price-card");
    quoteCard.append(node("div", "tg-card-label", price.price_kind === "daily_close" ? "Giá đóng cửa mới nhất" : "Giá mới nhất nhận được"));
    quoteCard.append(node("strong", "tg-price-value", tgNumber(values.last, 3) + " EGP"));
    const badge = quote.badge || {};
    quoteCard.append(node("span", "tg-source-badge " + (badge.kind === "delayed" ? "delayed" : ""), badge.text || "Trạng thái giá chưa xác minh"));
    quoteCard.append(node("p", "tg-card-note", price.price_kind === "daily_close" ? "Ngày giá: " + ((price.history || []).at(-1)?.date || "chưa rõ") + " · truy xuất lúc " + formatClock(quote.received_at) + "." : "Thời điểm nguồn: " + formatClock(quote.source_event_at) + " · nhận lúc " + formatClock(quote.received_at) + "."));
    grid.append(quoteCard);

    const dayCard = node("article", "tg-card");
    dayCard.append(node("div", "tg-card-label", "So với đóng cửa phiên trước"));
    const day = price.daily_change || {};
    const dayTone = Number(day.fraction) > 0 ? "tg-positive" : Number(day.fraction) < 0 ? "tg-negative" : "";
    dayCard.append(node("strong", "tg-price-value " + dayTone, tgPercent(day.fraction)));
    dayCard.append(node("p", "tg-card-note", "Chênh tuyệt đối: " + tgNumber(day.absolute, 3) + " EGP · so giá đóng cửa " + (day.reference_close?.date || "phiên trước") + "."));
    grid.append(dayCard);

    const weekCard = node("article", "tg-card");
    weekCard.append(node("div", "tg-card-label", "So với 5 phiên trước"));
    const five = price.five_session_change || {};
    const weekTone = Number(five.fraction) > 0 ? "tg-positive" : Number(five.fraction) < 0 ? "tg-negative" : "";
    weekCard.append(node("strong", "tg-price-value " + weekTone, tgPercent(five.fraction)));
    weekCard.append(node("p", "tg-card-note", five.reference_close ? "Mốc giá tham chiếu hiển thị: đóng cửa " + five.reference_close.date + " ở " + tgNumber(five.reference_close.close, 3) + " EGP. Phần trăm 5 phiên dùng Adj Close do Yahoo cung cấp; giá hiển thị là Close. Chưa đối soát độc lập sự kiện doanh nghiệp." : "Chưa đủ lịch sử ngày để xác định mốc năm phiên."));
    grid.append(weekCard);
    resultPanel.append(grid);

    const chartSection = node("section", "tg-chart-section");
    const chartTitle = node("div", "section-title");
    chartTitle.append(node("h3", "", "Diễn biến giá gần đây"));
    chartSection.append(chartTitle, tgPriceChart(price.history, price.price_kind === "daily_close" ? {} : { ...values, as_of: quote.source_event_at }));
    resultPanel.append(chartSection);
    for (const warning of price.warnings || []) resultPanel.append(node("p", "tg-card-note", warning));
  } else {
    const unavailable = node("section", "tg-decision tg-price-unavailable");
    unavailable.append(node("strong", "", "Chưa lấy được giá từ nguồn"));
    unavailable.append(node("p", "", price.message || "Chưa cấu hình hoặc chưa được nguồn cấp quyền."));
    const priceNote = price.error_code
      ? "Nguồn đã được gọi nhưng chưa trả dữ liệu dùng được. Kiểm tra quyền theo mã, gói dữ liệu và trạng thái provider."
      : "Bản máy này chưa có EODHD_API_TOKEN. Không có giá thì không hiển thị mốc thay thế hoặc giá giả.";
    unavailable.append(node("p", "tg-card-note", priceNote));
    resultPanel.append(unavailable);
  }

  resultPanel.append(renderTinGiaMethod({ ...data.decision, rule_path: rulePath }));

  const news = data.news || {};
  const alignment = news.price_alignment || {};
  if (alignment.price_date) {
    const counts = alignment.counts || {};
    resultPanel.append(node("p", "tg-card-note", `Đối chiếu thời gian với giá ngày ${alignment.price_date}: ${counts.after_price_date || 0} bài ra sau ngày giá, ${counts.same_day_order_unverified || 0} bài cùng ngày chưa rõ thứ tự. Với các bài này, chưa thể kết luận giá đã phản ứng với tin.`));
  }
  if (news.data_origin === "illustrative") resultPanel.append(node("p", "tg-decision", "Tin đang ở fixture minh họa; không ghép với giá thật để tạo tín hiệu."));
  const newsGrid = node("div", "tg-summary-grid tg-news-grid");
  const candidateRows = (news.candidate_ledger && news.candidate_ledger.candidates) || [];
  const companyChartCount = candidateRows.filter((row) => row.scope === "company_candidate" && row.reason_code === "market_data_chart_page").length;
  const companyDuplicateCount = candidateRows.filter((row) => row.scope === "company_candidate" && row.reason_code === "exact_duplicate").length;
  const companyExcludedNote = companyChartCount || companyDuplicateCount
    ? `${companyChartCount} trang biểu đồ và ${companyDuplicateCount} bản trùng URL-tiêu đề trong truy vấn công ty được giữ trong nhật ký nhưng không vào danh sách headline. `
    : "";
  const companyNote = news.status === "entity_mapping_pending"
    ? "Chưa xác minh tên doanh nghiệp và các tên gọi khác của mã này, nên chưa thu thập hoặc chấm tin công ty."
    : `Lô ứng viên truy vấn trong 90 ngày. ${companyExcludedNote}Bước quyết định phía trên chọn tin trong 30 ngày trước ngày giá và giảm trọng số theo tuổi và giảm điểm xét nhãn theo độ mới tuyệt đối; nhóm gần trùng chưa phải sự kiện đã xác minh.`;
  newsGrid.append(
    tgScoreCard("Tiêu đề được gắn với mã", news.company_news, companyNote),
    tgScoreCard("Tin bối cảnh ngoài công ty", news.macro_news, news.status === "entity_mapping_pending" ? "Chưa chạy thu thập tin cho mã này." : "FinBERT chỉ mô tả sắc thái từng headline. Chưa có bằng chứng surprise và mức phơi nhiễm riêng cho từng mã, nên nhóm này chưa đi vào nhãn."),
  );
  resultPanel.append(newsGrid);
  if (news.fetched_at) resultPanel.append(node("p", "tg-card-note", "Collector bắt đầu lấy lô tin lúc " + formatClock(news.fetched_at) + "; giờ lấy tin không phải giờ bài được đăng và có thể khác giờ của snapshot giá."));
  if (news.scope_note) resultPanel.append(node("p", "tg-card-note", news.scope_note));
  if (news.status === "unavailable" && news.message) resultPanel.append(node("p", "tg-card-note", "Tin chưa sẵn sàng: " + news.message));
  if (news.status === "empty" && news.message) resultPanel.append(node("p", "tg-card-note", news.message));
  addTinGiaHeadlines("Chi tiết headline đang đối chiếu với mã", news.company_news, "Headline ứng viên");
  addTinGiaHeadlines("Chi tiết tin bối cảnh ngoài công ty", news.macro_news, "Tin bối cảnh");
  addTinGiaExcluded(news.excluded_from_score);
  const reasonNames = {context_only:'Bối cảnh ngoài công ty',excluded_or_duplicate:'Bị loại bởi bộ lọc hoặc bản trùng',entity_not_verified:'Chưa xác định đúng doanh nghiệp',unscored_or_entity_ambiguous:'Chưa có xác suất hợp lệ',unknown_date:'Không rõ ngày đăng',outside_prior_30_calendar_days:'Không nằm trong 1–30 ngày trước ngày giá'};
  const exclusions = node('details', 'tg-news-details');
  exclusions.append(node('summary', '', `Không dùng trong nhãn · ${(data.decision.excluded || []).length} bản ghi`));
  const byId = new Map(candidateRows.map(r => [r.candidate_id,r]));
  for (const x of data.decision.excluded || []) exclusions.append(node('p','tg-card-note',`${byId.get(x.candidate_id)?.title || x.candidate_id}: ${reasonNames[x.reason] || x.reason}`));
  resultPanel.append(exclusions);
  addTinGiaCandidateLedger(news.candidate_ledger);

  const reasons = node("section", "tg-missing");
  reasons.append(node("h3", "", "Phạm vi sử dụng kết luận"));
  const list = document.createElement("ul");
  const reasonTexts = {
    return_forecast_not_calibrated: "Chưa có mô hình dự báo lợi suất được kiểm định ngoài mẫu.",
    mean_uncertainty_not_validated: "Chưa có khoảng bất định của kỳ vọng đã được hiệu chuẩn.",
    single_outcome_risk_not_validated: "Chưa xác nhận độ bao phủ khoảng biến động của một kết quả thực tế.",
    verified_bid_ask_and_costs_missing: "Chưa có bid/ask và phí thực thi xác minh để tính hòa vốn.",
    egx_intraday_entitlement_not_verified: "Chưa xác minh nguồn EGX intraday được cấp quyền; EODHD hiện là giá trễ.",
  };
  for (const code of data.decision.reason_codes || []) list.append(node("li", "", reasonTexts[code] || code));
  reasons.append(list, node("p", "tg-card-note", data.decision.method_note));
  resultPanel.append(reasons);

  const refs = node("section", "tg-references");
  refs.append(node("strong", "", "Nguồn kiểm tra"));
  const links = [
    ["Tài liệu EODHD về giá trễ", price.source_docs && price.source_docs.quote],
    [price.price_kind === "daily_close" ? "Tài liệu yfinance về lịch sử giá" : "Tài liệu EODHD về lịch sử giá", price.source_docs && price.source_docs.history],
    ["Tài liệu EODHD News API", "https://eodhd.com/financial-apis/stock-market-financial-news-api"],
    ["Bảng gói và lượt gọi API EODHD", "https://eodhd.com/pricing"],
    ["Tài liệu API EGID Feed / DelayedFeed", "https://ticker.egidegypt.com/index.html"],
  ].filter((row) => row[1]);
  for (const row of links) refs.append(safeLink(row[1], row[0] + " ↗") || row[0]);
  resultPanel.append(refs);
  resultPanel.classList.remove("hidden");
}

$("#tinGiaForm").addEventListener("submit", (event) => {
  event.preventDefault();
  renderTinGiaMarketView();
  const symbol = $("#tinGiaSymbol").value.trim().toUpperCase();
  const query = new URLSearchParams({ symbol });
  submitAnalysis("/api/v1/tin-gia/stock?" + query, null, event.submitter, renderTinGiaResult);
});

loadHealth();
