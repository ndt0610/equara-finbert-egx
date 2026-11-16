// US portfolio: separate fixture calculator and captured point-in-time inspector.
(() => {
  const form = document.querySelector("#usForm");
  const output = document.querySelector("#usResult");
  const errorBox = document.querySelector("#usError");
  const dataMode = document.querySelector("#usDataMode");
  const captureControls = document.querySelector("#usCaptureControls");
  const captureStatus = document.querySelector("#usCaptureStatus");
  const auditPanel = document.querySelector("#usAuditPanel");
  const positionsInput = document.querySelector("#usPositions");
  const positionsLabel = document.querySelector("#usPositionsLabel");
  let fixtureInputCache = positionsInput.value;
  let capturedInputCache = "";
  let universe = null;
  let auditLoaded = false;
  let submitGeneration = 0;
  let modeTouched = false;

  const el = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = content;
    return node;
  };
  const money = value => Number(value).toLocaleString("en-US", {style:"currency",currency:"USD",maximumFractionDigits:2});
  const pct = value => (Number(value) * 100).toLocaleString("vi-VN", {maximumFractionDigits:2}) + "%";
  const signed = value => value == null ? "Chưa có" : Number(value).toLocaleString("vi-VN", {maximumFractionDigits:4,minimumFractionDigits:2});
  const relevanceText = value => ({DIRECT_MENTION_UNVERIFIED:"Nhắc trực tiếp · chưa xác minh",SECTOR_MENTION_UNVERIFIED:"Theo ngành · chưa xác minh",
    POSSIBLE_NOISE_UNVERIFIED:"Nghi nhiễu · chưa xác minh",UNKNOWN_REVIEW:"Cần rà soát",UNSCORABLE_ADMIN_FILING:"Hồ sơ cấu trúc"})[value] || value;

  function parseHoldings(text, mode = dataMode.value) {
    const lines = text.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    if (!lines.length || lines.length > 20) throw Error("Nhập từ 1 đến 20 vị thế.");
    const seen = new Set();
    return lines.map((line, index) => {
      const fields = line.split(",").map(x => x.trim());
      if (mode === "captured" ? ![2,3].includes(fields.length) : fields.length !== 4) {
        throw Error(`Dòng ${index + 1}: định dạng ${mode === "captured" ? "mã, số lượng, kịch bản % (cột cuối tùy chọn)" : "mã, số lượng, giá, kịch bản %"}.`);
      }
      const [ticker, quantity, third, fourth] = fields;
      const price = mode === "captured" ? null : third;
      const change = mode === "captured" ? (third || "0") : fourth;
      if (!universe.has(ticker)) throw Error(`Dòng ${index + 1}: ${ticker} chưa thuộc danh sách 50 mã nghiên cứu.`);
      if (seen.has(ticker)) throw Error(`Mã ${ticker} bị nhập trùng.`);
      seen.add(ticker);
      const values = mode === "captured" ? [["số lượng", quantity],["kịch bản", change]] : [["số lượng", quantity],["giá", price],["kịch bản", change]];
      for (const [label, value] of values) {
        if (value === "" || !Number.isFinite(Number(value))) throw Error(`Dòng ${index + 1}: ${label} không hợp lệ.`);
      }
      if (Number(quantity) < 0 || Number(change) < -100 || (mode !== "captured" && Number(price) <= 0)) {
        throw Error(mode === "captured" ? `Dòng ${index + 1}: số lượng không âm và kịch bản không dưới −100%.` :
          `Dòng ${index + 1}: số lượng không âm, giá dương và kịch bản phải lớn hơn −100%.`);
      }
      return {ticker, quantity, price, change};
    });
  }

  function makeTable(headings, rows) {
    const wrap = el("div","table-wrap");
    const table = el("table","us-table");
    const thead = el("thead");
    const tr = el("tr");
    headings.forEach(h => {
      const th = el("th","",h);
      th.scope = "col";
      tr.append(th);
    });
    thead.append(tr);
    const tbody = el("tbody");
    rows.forEach(row => {
      const line = el("tr");
      row.forEach((cell,index) => {
        const td = el("td");
        if (cell instanceof Node) td.append(cell);
        else td.textContent = cell;
        td.dataset.label = headings[index];
        line.append(td);
      });
      tbody.append(line);
    });
    table.append(thead,tbody);
    wrap.append(table);
    return wrap;
  }

  function render(data, fixture) {
    output.replaceChildren();
    output.append(el("h2","","Danh mục Mỹ · dữ liệu minh họa"));
    output.append(el("p","us-note",fixture.fixture_notice));
    output.append(el("p","us-note",`Mốc quyết định mẫu: ${data.decision_at}. Phiên có thể giao dịch sớm nhất theo lịch: ${data.schedule.earliest_core_execution_session}; chưa có giá khớp lệnh.`));
    const metrics = el("div","us-metrics");
    for (const [label,value,explanation] of [
      ["Vốn cổ phiếu có tin",pct(data.coverage),`Chưa có tin: ${pct(data.uncovered_equity_ratio)} vốn cổ phiếu`],
      ["Sắc thái phần có tin",signed(data.covered_portfolio_score),`Chỉ đọc cùng độ phủ ${pct(data.coverage)}; không là dự báo giá`],
      ["Tổng danh mục",money(data.nav_usd),`Cổ phiếu ${money(data.equity_value_usd)} · tiền mặt ${money(data.cash_usd)}`],
      ["Kịch bản giả định",money(data.scenario.change_usd),`${pct(data.scenario.total_return)} trên tổng danh mục, trước phí`],
    ]) {
      const card = el("article","us-metric");
      card.append(el("span","",label),el("strong","",value),el("small","",explanation));
      metrics.append(card);
    }
    output.append(metrics);
    output.append(el("h3","","Vị thế và phần vốn được đại diện"));
    output.append(makeTable(
      ["Mã","Giá trị","Vốn cổ phiếu","Tin hợp lệ","Điểm tiêu đề theo sự kiện","Đóng góp thô","Kịch bản"],
      data.holdings.map(h => [
        h.ticker,money(h.position_value_usd),pct(h.equity_weight),
        h.news_status === "COVERED" ? `${h.event_count} sự kiện${h.conflicting_news ? " · có tin trái chiều" : ""}` : "Chưa có tin hợp lệ",
        signed(h.headline_sentiment_score),signed(h.raw_equity_contribution),
        `${pct(h.scenario_return)} → ${money(h.scenario_new_value_usd)}`,
      ]),
    ));
    output.append(el("p","us-note",`Tổng đóng góp sắc thái trên vốn cổ phiếu: ${signed(data.raw_equity_weighted_score)}. Đây chỉ là tổng phần đã quan sát; mã thiếu tin giữ điểm null. Tiền mặt chiếm ${pct(data.cash_nav_weight)} NAV.`));
    output.append(el("h3","","Tiêu đề và nguồn kiểm tra"));
    for (const item of data.news) {
      const article = el("article","us-news");
      article.append(el("strong","",`${item.ticker} · ${item.title}`));
      article.append(el("small","",`${item.source} · ${item.source_kind} · đăng ${item.published_at} · nhận ${item.ingested_at} · điểm ${signed(item.score)} · dữ liệu mẫu`));
      if (item.url) {
        const link = el("a","","Mở nguồn ↗");
        link.href = item.url; link.target = "_blank"; link.rel = "noreferrer";
        article.append(link);
      }
      output.append(article);
    }
    output.append(el("h3","","Nhóm sự kiện tạm"));
    output.append(makeTable(
      ["Mã","Số tiêu đề","Điểm nhóm","Bài nhận đầu tiên","Bài đại diện","Tình trạng"],
      data.events.map(event => [
        event.ticker, String(event.item_ids.length), signed(event.score),
        event.first_item_id,event.primary_item_id,
        event.conflicting_headlines ? "Tiêu đề trái chiều" : event.grouping_status === "exact_title" ? "Cùng tiêu đề" : "Event key do nguồn nhập",
      ]),
    ));
    if (data.rejected_news.length) output.append(el("p","us-note",`${data.rejected_news.length} tin không đủ điều kiện thời gian hoặc điểm; xem API để kiểm tra lý do.`));
    output.append(el("p","us-note",`Tin bối cảnh: ${data.context_news.length} bản ghi, tách khỏi điểm theo vốn.`));
    const comparison = el("details","us-comparison");
    comparison.append(el("summary","","Đối chiếu công thức theo từng bài cũ"));
    comparison.append(el("p","us-note",`Điểm cũ ${signed(data.legacy.score)}; điểm mới trên phần vốn có tin ${signed(data.covered_portfolio_score)} với độ phủ ${pct(data.coverage)}. Điểm cũ cho mỗi bài một phiếu và đưa bối cảnh vào mẫu số.`));
    comparison.append(makeTable(["Mã","Vốn thực","Tỷ trọng hiệu dụng cũ"],data.holdings.map(h=>[
      h.ticker,pct(h.equity_weight),pct(data.legacy.effective_ticker_shares[h.ticker] || 0),
    ])));
    comparison.append(el("p","us-note",`Tin bối cảnh chiếm ${pct(data.legacy.effective_context_share || 0)} trong phép tính cũ. Bản mới tính mỗi sự kiện một lần trong từng mã; hiện chỉ gom tiêu đề giống hệt hoặc event key được cung cấp.`));
    output.append(comparison);
    output.append(el("p","us-note","Kịch bản do bạn nhập, trước phí, cổ tức, thuế và chênh lệch tỷ giá; không ước lượng tác động của tin lên giá."));
    output.append(el("p","us-note","Thời điểm và nguồn trong API là khai báo của bên gửi dữ liệu. Bản demo này chỉ dùng fixture và chưa chứng minh dữ liệu đã sẵn có tại một quyết định lịch sử."));
    output.classList.remove("hidden");
  }

  function renderAudit(data) {
    auditPanel.replaceChildren();
    const details = el("details","us-comparison");
    details.append(el("summary","","Kiểm toán thực nghiệm FinBERT & Phase 3"));
    const counts = data.ledger_counts;
    auditPanel.append(el("p","us-note",`Toàn sổ cái: ${counts.sec_filings} hồ sơ SEC · ${counts.scored_news} tin có điểm FinBERT · ${counts.sip_price_bars} thanh giá SIP. ${data.artifact_status.phase3_reports_loaded}/6 báo cáo replay đã đọc. Mở kiểm toán để xem chi tiết.`));
    details.append(el("p","us-replay-warning","Các bảng là mô tả dữ liệu và replay hồi cứu, chưa có nhãn người độc lập hoặc bằng chứng lợi suất. Nhóm sự kiện đã được xem khi sửa thuật toán."));
    details.append(el("h3","","Phân phối điểm theo quy tắc liên quan chưa xác minh"));
    details.append(makeTable(["Nhóm","N","Dương","Trung tính","Âm","Net TB","Độ lệch chuẩn"],data.distribution.map(x => [
      x.category,String(x.count),String(x.positive),String(x.neutral),String(x.negative),signed(x.mean_net),signed(x.sd_net),
    ])));
    details.append(el("h3","","Ảnh hưởng cơ học của việc lọc tin nghi nhiễu"));
    details.append(makeTable(["Mã","Tin","Loại","Trung bình gốc","Sau lọc","Chênh lệch"],data.noise_effect.map(x => [
      x.ticker,String(x.news_count),String(x.excluded_count),signed(x.raw_mean),signed(x.filtered_mean),signed(x.delta),
    ])));
    details.append(el("h3","","Chênh lệch hai cách viết trong nhóm sự kiện chọn lọc"));
    details.append(makeTable(["Nhóm","Benzinga","fiscal.ai","Độ lệch tuyệt đối"],data.source_pairs.map(x => [
      x.group,signed(x.benzinga_net),signed(x.fiscal_net),signed(x.absolute_gap),
    ])));
    details.append(el("h3","","Giá mục tiêu trái chiều với điểm mô hình"));
    details.append(makeTable(["Mã","Tiêu đề","Giá cũ → mới","FinBERT net"],data.numeric_mismatches.map(x => [
      x.ticker,x.headline,`${x.previous} → ${x.current} · ${x.direction}`,signed(x.net_score),
    ])));
    details.append(el("h3","","Các tiêu đề nhiều tín hiệu"));
    details.append(makeTable(["Mã","Tiêu đề","p+ / p0 / p−","Net"],data.mixed_headlines.map(x => [
      x.ticker,x.headline,`${signed(x.p_pos)} / ${signed(x.p_neu)} / ${signed(x.p_neg)}`,signed(x.net_score),
    ])));
    details.append(el("h3","","Walk-forward Phase 3 · hồi cứu"));
    details.append(makeTable(["H","Bộ lọc","Dòng đánh giá","Có điểm tin","Brier giá","Brier giá + tin","Cấp hiệu lực"],data.phase3.map(x => [
      String(x.horizon),x.relevance_filter,String(x.evaluated_rows),String(x.scored_event_rows),
      signed(x.price_brier),signed(x.price_news_brier),x.validity_tier,
    ])));
    if (!data.phase3.length) details.append(el("p","us-note","Chưa tìm thấy báo cáo Phase 3 trong artifacts; hãy chạy replay trước."));
    auditPanel.append(details);
    auditPanel.classList.toggle("hidden",dataMode.value !== "captured");
  }

  function renderPriceChart(data) {
    const box = el('section', 'us-visual');
    box.append(el('h3', '', 'Diễn biến giá SIP điều chỉnh gần đây'));
    box.append(el('p', 'us-note', 'Một vintage giá cho mỗi mã, tối đa 21 phiên đến mốc quyết định. B và E là phân vị của |R5| trong cửa sổ này; cần ít nhất 10 quan sát R5 liên tiếp hợp lệ.'));
    const label = el('label', '', 'Chọn mã');
    const select = el('select');
    select.setAttribute('aria-label', 'Chọn mã xem biểu đồ giá');
    data.positions.forEach(p => { const option = el('option', '', p.ticker); option.value = p.ticker; select.append(option); });
    label.append(select); box.append(label);
    const content = el('div'); box.append(content);
    function draw() {
      content.replaceChildren();
      const p = data.positions.find(x => x.ticker === select.value);
      const chart = p.price_chart;
      if (!chart || chart.points.length < 2) { content.append(el('p', 'us-note', 'Chưa đủ giá SIP điều chỉnh cùng vintage tại mốc này.')); return; }
      const pts = chart.points, values = pts.map(x => Number(x.close_adj));
      const lo = Math.min(...values), hi = Math.max(...values), spread = hi - lo || 1;
      const ns = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('viewBox', '0 0 600 180'); svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', `${p.ticker}: giá điều chỉnh từ ${pts[0].session_date} đến ${pts[pts.length-1].session_date}`);
      const coords = values.map((v,i) => [20 + i * 560 / (values.length-1), 150 - (v-lo)/spread*120]);
      const line = document.createElementNS(ns, 'polyline'); line.setAttribute('points', coords.map(x=>x.join(',')).join(' ')); line.setAttribute('class','us-chart-line'); svg.append(line);
      coords.forEach((coord,i) => { const c = document.createElementNS(ns,'circle'); c.setAttribute('cx',coord[0]); c.setAttribute('cy',coord[1]); c.setAttribute('r','3'); c.setAttribute('class','us-chart-dot'); const title = document.createElementNS(ns,'title'); title.textContent = `${pts[i].session_date}: ${money(values[i])}`; c.append(title); svg.append(c); });
      content.append(svg, el('p','us-note',`${pts[0].session_date}: ${money(values[0])} · ${pts[pts.length-1].session_date}: ${money(values[values.length-1])}`));
      const metrics = el('div','us-metrics');
      for (const [name,value,note] of [['R5 · 5 phiên',chart.r5 == null ? 'Chưa đủ dữ liệu' : pct(chart.r5),'Giá điều chỉnh'],['B · phân vị 75%',chart.b75 == null ? 'Chưa đủ dữ liệu' : pct(chart.b75),`${chart.r5_samples} quan sát |R5|`],['E · phân vị 90%',chart.e90 == null ? 'Chưa đủ dữ liệu' : pct(chart.e90),`${chart.r5_samples} quan sát |R5|`],['Cửa sổ tin',`${data.window_days} ngày`,`Lọc: ${data.relevance_filter}; gom cụm thử nghiệm`]]) {
        const card = el('article','us-metric'); card.append(el('span','',name),el('strong','',value),el('small','',note)); metrics.append(card);
      }
      content.append(metrics);
    }
    select.addEventListener('change',draw); draw(); return box;
  }

  function renderMethod(data) {
    const box = el('section','us-visual');
    box.append(el('h3','','Từ sổ cái đến danh mục'));
    const grid = el('div','us-steps');
    const steps = [
      ['1 · Mốc thời gian', data.strict_pit_mode ? 'Chỉ dùng dữ liệu đã nhận trước cutoff; tin sau giờ đóng cửa chuyển sang phiên kế tiếp.' : 'Replay cho phép dùng dữ liệu nhận sau cutoff; kết quả chỉ phục vụ chẩn đoán.'],
      ['2 · Liên quan và sự kiện','Quy tắc lọc thử nghiệm và gom tiêu đề cùng sự kiện; chưa được xác thực bằng nhãn độc lập.'],
      ['3 · Độ phủ và sắc thái','Mã thiếu điểm giữ giá trị trống; hồ sơ SEC cấu trúc không tự tạo điểm sắc thái.'],
      ['4 · Kịch bản và kiểm định','NAV dùng close_raw; kịch bản do người dùng nhập. Walk-forward dùng giá mở cửa phiên tiếp theo.']];
    steps.forEach(([title,body])=>{const card=el('article','us-step');card.append(el('strong','',title),el('p','',body));grid.append(card);});
    box.append(grid,el('h3','','Cách tính các đại lượng'),el('div','us-formulas','C = Σ wᵢ (mã có điểm)     Scovered = Σ(wᵢ × sᵢ) / C\nΔV = Σ(nᵢ × Pᵢ raw × rᵢ)     Slegacy = Σ(q × x) / Σq'),
      el('p','us-note','wᵢ: tỷ trọng vốn cổ phiếu; sᵢ: điểm theo cụm; nᵢ: số cổ phiếu; Pᵢ: giá đóng cửa thô; rᵢ: thay đổi giả định. Công thức cũ dùng q là giá trị vị thế cho mỗi bài có điểm x. C = 0 thì Scovered không xác định.'));
    return box;
  }

  async function loadAudit() {
    if (auditLoaded) return;
    try {
      const response = await fetch("/api/v3/us/audit-summary");
      if (!response.ok) throw Error("Không đọc được kiểm toán sổ cái.");
      renderAudit(await response.json());
      auditLoaded = true;
    } catch (error) {
      auditPanel.replaceChildren(el("p","us-error",error.message || "Không đọc được kiểm toán."));
      auditPanel.classList.toggle("hidden",dataMode.value !== "captured");
    }
  }

  function renderCaptured(data) {
    output.replaceChildren();
    output.append(el("h2","","Snapshot từ sổ cái cục bộ"));
    if (!data.strict_pit_mode) output.append(el("p","us-replay-warning","REPLAY HỒI CỨU · chỉ để chẩn đoán, không phải PiT. Giá, tin và điểm có thể đã được Equara nhận sau mốc quyết định; không dùng như quyết định lịch sử hoặc tín hiệu giao dịch."));
    const provenance = el("details","us-comparison");
    provenance.append(el("summary","","Nguồn dữ liệu, quyền sử dụng và cấp hiệu lực"));
    provenance.append(el("p","us-note",`Cấp hiệu lực kỹ thuật: ${data.report_validity_tier}. Tầng nguồn: ${data.provenance_tiers.join(", ") || "CHƯA CÓ DỮ LIỆU"}.`));
    provenance.append(el("p","us-note","Metadata hồ sơ SEC công khai; quyền tái phân phối dữ liệu Alpaca cần kiểm tra riêng. Giá IEX chỉ mang tính tham khảo, không đại diện giá đóng cửa hợp nhất."));
    output.append(provenance);
    const noiseCount = data.excluded_items.filter(x => x.reason === "EXCLUDED_TARGET_NOISE_HEURISTIC").length;
    output.append(el("p","us-note",data.relevance_filter === "exclude_noise" ?
      `Bộ lọc tin nghi nhiễu thử nghiệm đang bật: ${noiseCount} bản ghi bị loại theo quy tắc; xem lý do trong nhật ký bên dưới.` :
      "Bộ lọc tin nghi nhiễu đang tắt: điểm sắc thái gồm cả các bản ghi có thể bị gán nhầm mã."));
    output.append(el("p","us-note",`Mốc quyết định: ${data.decision_ts_et} ET · ${data.decision_ts_utc} UTC. Phiên hoàn tất: ${data.schedule.decision_session}. Phiên giao dịch sớm nhất: ${data.schedule.earliest_core_execution_session}.`));
    output.append(el("p","us-note",`SHA-256 snapshot: ${data.snapshot_sha256}`));
    if (data.strict_pit_mode && !data.valuation_complete && data.positions.every(x => x.price_status === "MISSING_PRICE")) {
      output.append(el("p","us-replay-warning","Mốc này chưa có giá mà Equara đã nhận trước thời điểm quyết định. Nếu muốn xem dữ liệu giá tải về sau để nghiên cứu ngày cũ, chọn Replay hồi cứu ở trên; kết quả đó không còn là PiT."));
    }
    const metrics = el("div","us-metrics");
    for (const [label,value,note] of [
      ["NAV theo close_raw",data.nav_usd == null ? "Chưa xác định" : money(data.nav_usd),data.valuation_complete ? "Gồm tiền mặt; giá quan sát trong ledger" : "Thiếu giá, giá cũ hoặc feed IEX"],
      ["Độ phủ vốn có tin",data.coverage == null ? "Chưa xác định" : pct(data.coverage),data.coverage == null ? "Chưa có định giá đầy đủ" : `Vốn chưa có tin: ${pct(1-Number(data.coverage))}`],
      ["Sắc thái phần có tin",signed(data.covered_portfolio_score),`Điểm mỗi sự kiện một lần · cũ mỗi bài: ${signed(data.legacy_comparison.score)}`],
      ["Kịch bản giá giả định",data.scenario.change_usd == null ? "Chưa xác định" : money(data.scenario.change_usd),`${data.scenario.total_return == null ? "—" : pct(data.scenario.total_return)} NAV · do bạn nhập, không suy ra từ tin`],
    ]) {
      const card = el("article","us-metric");
      card.append(el("span","",label),el("strong","",value),el("small","",note));
      metrics.append(card);
    }
    output.append(metrics);
    output.append(renderPriceChart(data), renderMethod(data));
    output.append(el("p","us-note",`Đóng góp sắc thái trên toàn bộ vốn: ${signed(data.raw_equity_weighted_score)}. Mã thiếu tin giữ điểm null. Kịch bản do bạn nhập trên close_raw, trước phí, cổ tức, thuế và tỷ giá.`));
    output.append(el("h3","","Giá và sự kiện theo mã"));
    output.append(makeTable(
      ["Mã","Giá / feed","Phiên giá","close_raw / vốn","close_adj / R5","Cụm / bài","Sắc thái","Kịch bản","SEC chưa chấm"],
      data.positions.map(x => [x.ticker,`${x.price_status} / ${x.price_feed || "—"}`,x.price_session_date || "—",
        x.close_raw == null ? "—" : `${money(x.close_raw)} / ${money(x.position_value_usd)}`,
        x.close_adj == null ? "—" : `${money(x.close_adj)} / ${x.r5_adjusted == null ? "thiếu 6 phiên" : pct(x.r5_adjusted)}`,
        `${x.cluster_count} / ${x.article_count}${x.has_conflicting_sentiment ? " · trái chiều" : ""}`,
        signed(x.sentiment_score),`${pct(x.scenario_return)} → ${x.scenario_new_value_usd == null ? "Chưa xác định" : money(x.scenario_new_value_usd)}`,
        String(x.unscored_sec_filings_count)]),
    ));
    const comparison = el("details","us-comparison");
    comparison.append(el("summary","","Đối chiếu công thức theo vốn và mỗi bài một phiếu"));
    comparison.append(el("p","us-note",`Cũ trên ${data.legacy_comparison.headline_count} bài có điểm: ${signed(data.legacy_comparison.score)}. Mới theo vốn và cụm sự kiện: ${signed(data.covered_portfolio_score)}. Chênh lệch có thể do số tin từng mã, cách gom sự kiện và độ phủ; không đo hiệu quả dự báo.`));
    const scoredCount = new Map(data.positions.map(x => [x.ticker, 0]));
    data.events.filter(x => x.net_score != null).forEach(x => scoredCount.set(x.ticker, (scoredCount.get(x.ticker) || 0) + 1));
    comparison.append(makeTable(["Mã","Tỷ trọng vốn","Tỷ trọng hiệu dụng cũ","Bài có điểm"],data.positions.map(x => [
      x.ticker,data.equity_value_usd == null ? "—" : pct(Number(x.position_value_usd)/Number(data.equity_value_usd)),
      data.legacy_comparison.effective_ticker_shares[x.ticker] == null ? "—" : pct(data.legacy_comparison.effective_ticker_shares[x.ticker]),String(scoredCount.get(x.ticker) || 0),
    ])));
    output.append(comparison);
    const inspector = el("details","us-comparison us-inspector");
    inspector.append(el("summary","",`Truy nguyên sự kiện và nhật ký chặn · ${data.events.length} hợp lệ / ${data.excluded_items.length} lượt loại`));
    inspector.append(el("p","us-note",`Tin và hồ sơ hợp lệ: ${data.events.length}. Nhật ký có ${data.excluded_items.length} lượt loại theo lý do, gồm cả tin, điểm và giá. Hồ sơ SEC cấu trúc không được chấm sắc thái khi thiếu văn bản.`));
    const numericWarnings = data.events.filter(x => x.numeric_target_info && x.numeric_target_info.finbert_direction_disagrees);
    if (numericWarnings.length) {
      output.append(el("p","us-replay-warning",`${numericWarnings.length} tiêu đề có chiều thay đổi giá mục tiêu trái dấu với điểm FinBERT. Mở truy nguyên để xem từng trường hợp; đây là tín hiệu kiểm tra câu chữ, không phải kết luận giá cổ phiếu.`));
      inspector.append(makeTable(["Mã","Tiêu đề","Giá cũ → mới","FinBERT net"],numericWarnings.map(x => [
        x.ticker,x.headline,`${x.numeric_target_info.previous} → ${x.numeric_target_info.current}`,signed(x.net_score),
      ])));
    }
    if (data.events.length > 150) inspector.append(el("p","us-note","Bảng hiển thị 150 sự kiện đầu tiên; API trả đầy đủ các bản ghi."));
    inspector.append(makeTable(["Mã","Loại","Tiêu đề","FinBERT net · p+ / p0 / p−","Liên quan / số học","Mốc nguồn / cơ sở","Equara nhận / chấm","Phiên khả thi","Trạng thái"],
      data.events.slice(0,150).map(x => {
        const headline = el("div","us-headline-cell");
        headline.append(el("span","",x.headline));
        if (x.source_url && /^https:\/\//.test(x.source_url)) {
          const link = el("a","us-source-link",`Mở nguồn ${x.source_name} ↗`);
          link.href = x.source_url; link.target = "_blank"; link.rel = "noreferrer";
          headline.append(link);
        }
        return [x.ticker,x.item_type,headline,
        x.net_score == null ? "Chưa chấm" : `${signed(x.net_score)} · ${signed(x.p_pos)} / ${signed(x.p_neu)} / ${signed(x.p_neg)}`,
        `${relevanceText(x.relevance_label)}${x.numeric_target_info ? ` · ${x.numeric_target_info.previous} → ${x.numeric_target_info.current} ${x.numeric_target_info.direction}${x.numeric_target_info.finbert_direction_disagrees ? " · CẢNH BÁO TRÁI DẤU" : ""}` : ""}`,
        `${x.provider_accepted_raw || x.published_at_utc} / ${x.publication_time_basis || "—"}`,
        `${x.ingested_at_utc} / ${x.scored_at_utc || "—"}`,`${x.timing}: ${x.earliest_tradable_session}`,
        `${x.scoring_status} · ${x.provenance_tier}`];
      })));
    inspector.append(el("h3","","Cụm sự kiện và lý do"));
    if (data.clusters.length > 150) inspector.append(el("p","us-note","Bảng hiển thị 150 cụm đầu tiên; API trả đầy đủ."));
    inspector.append(makeTable(["Mã","Bài trong cụm","Điểm","Lý do","Mâu thuẫn"],
      data.clusters.slice(0,150).map(x => [x.ticker,x.item_ids.join(", "),signed(x.score),x.clustering_reason.join(", "),x.has_conflicting_sentiment ? "Có" : "Không"])));
    inspector.append(el("h3","","Bản ghi bị chặn"));
    if (data.excluded_items.length > 100) inspector.append(el("p","us-note","Hiển thị 100 bản ghi đầu tiên; API trả toàn bộ nhật ký để kiểm tra."));
    inspector.append(makeTable(["Bản ghi","Lý do"],data.excluded_items.slice(0,100).map(x=>[x.item_id,x.reason])));
    output.append(inspector);
    output.classList.remove("hidden");
  }

  async function capture(source) {
    const buttons = ["#usCaptureSec", "#usCaptureNews", "#usCapturePrices"].map(x => document.querySelector(x));
    buttons.forEach(x => {x.disabled = true;});
    captureStatus.textContent = `Đang thu thập ${source}…`;
    try {
      const catalog = await fetch("/api/v3/us/universe").then(r => r.json());
      universe = new Set(catalog.items.map(x => x.ticker));
      const tickers = parseHoldings(positionsInput.value).map(x => x.ticker);
      const endTs = source === "alpaca_prices" ? document.querySelector("#usPriceEndUtc").value.trim() : "";
      const response = await fetch("/api/v3/us/capture", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source,tickers,end_ts_utc:endTs || null})});
      const data = await response.json();
      if (!response.ok) throw Error(data.detail || "Thu thập thất bại.");
      captureStatus.textContent = `Đã ghi ${data.captured} bản ghi từ ${source}. ${data.captured_live || 0} bản ghi mới sau lần quét trước; xem snapshot để kiểm tra.`;
      await submit();
    } catch (error) {
      captureStatus.textContent = error.message || "Thu thập thất bại.";
    } finally {
      buttons.forEach(x => {x.disabled = false;});
    }
  }

  async function submit(event) {
    if (event) event.preventDefault();
    const generation = ++submitGeneration;
    if (window.location.protocol === "file:") {
      errorBox.textContent = "Bạn đang mở HTML trực tiếp. Chạy C:\\equara_tin_gia_env\\Scripts\\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8124 rồi mở http://127.0.0.1:8124 để kết nối sổ cái.";
      errorBox.classList.remove("hidden");
      output.classList.add("hidden");
      return;
    }
    errorBox.classList.add("hidden");
    output.replaceChildren(el("p","us-note","Đang dựng kết quả cho đầu vào hiện tại…"));
    output.classList.remove("hidden");
    try {
      const catalog = await fetch("/api/v3/us/universe").then(r => {if(!r.ok) throw Error("Không đọc được danh sách mã."); return r.json();});
      universe = new Set(catalog.items.map(x => x.ticker));
      const holdings = parseHoldings(positionsInput.value);
      const cash = document.querySelector("#usCash").value;
      if (cash === "" || !Number.isFinite(Number(cash)) || Number(cash) < 0) throw Error("Tiền mặt phải là số không âm.");
      if (dataMode.value === "captured") {
        const cutoff = document.querySelector("#usDecisionCutoff").value.trim();
        const relevanceFilter = document.querySelector("#usRelevanceFilter").value;
        const strictPitMode = document.querySelector("#usTimeMode").value === "strict";
        const response = await fetch("/api/v3/us/snapshot", {method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({holdings:holdings.map(x=>({ticker:x.ticker,quantity:x.quantity})),cash_usd:Number(cash),
            decision_ts_utc:cutoff || null,strict_pit_mode:strictPitMode,relevance_filter:relevanceFilter,
            scenario_returns:Object.fromEntries(holdings.map(x=>[x.ticker,Number(x.change)/100]))})});
        const data = await response.json();
        if (!response.ok) throw Error(data.detail || "Không dựng được snapshot.");
        if (generation !== submitGeneration) return;
        renderCaptured(data);
        await loadAudit();
        return;
      }
      const fixture = await fetch("/api/v3/us/fixture").then(r => {if(!r.ok) throw Error("Không đọc được dữ liệu mẫu."); return r.json();});
      const payload = {
        decision_at: fixture.decision_at,
        cash_usd: cash,
        news: fixture.news,
        scenario_returns: Object.fromEntries(holdings.map(x => [x.ticker,String(Number(x.change)/100)])),
        holdings: holdings.map(x => ({
          ticker: x.ticker, quantity: x.quantity,
          price: {ticker:x.ticker,price_usd:x.price,as_of:fixture.price_as_of,
            ingested_at:fixture.price_ingested_at,adjustment_method:"manual",
            provenance_tier:"FIXTURE_DEMO",source:"User-entered fixture reference price"},
        })),
      };
      const response = await fetch("/api/v3/us/portfolio/exposure",{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "Dữ liệu danh mục không hợp lệ.");
      if (generation !== submitGeneration) return;
      render(data,fixture);
    } catch (error) {
      if (generation !== submitGeneration) return;
      output.classList.add("hidden");
      errorBox.textContent = error.message || "Không tính được danh mục.";
      errorBox.classList.remove("hidden");
    }
  }
  form.addEventListener("submit",submit);
  dataMode.addEventListener("change",() => {
    modeTouched = true;
    const captured = dataMode.value === "captured";
    if (captured) {
      fixtureInputCache = positionsInput.value;
      capturedInputCache = capturedInputCache || fixtureInputCache.split(/\r?\n/).map(line => {
        const fields = line.split(",").map(x=>x.trim());
        return [fields[0],fields[1],fields[3] || "0"].join(", ");
      }).join("\n");
      positionsInput.value = capturedInputCache;
      positionsLabel.textContent = "Mỗi dòng: mã, số cổ phiếu, kịch bản (%) tùy chọn";
    } else {
      capturedInputCache = positionsInput.value;
      positionsInput.value = fixtureInputCache;
      positionsLabel.textContent = "Mỗi dòng: mã, số cổ phiếu, giá tham chiếu USD, thay đổi giả định (%)";
    }
    captureControls.classList.toggle("hidden",!captured);
    auditPanel.classList.toggle("hidden",!captured);
    document.querySelector("#usFixtureBanner").classList.toggle("hidden",captured);
    submit();
  });
  document.querySelector("#usLoadTen").addEventListener("click",() => {
    positionsInput.value = "AAPL, 1, 0\nMSFT, 1, 0\nNVDA, 1, 0\nJPM, 1, 0\nGS, 1, 0\nXOM, 1, 0\nCVX, 1, 0\nUNH, 1, 0\nLLY, 1, 0\nCAT, 1, 0";
    capturedInputCache = positionsInput.value;
    submit();
  });
  document.querySelector("#usCaptureSec").addEventListener("click",()=>capture("sec"));
  document.querySelector("#usCaptureNews").addEventListener("click",()=>capture("alpaca_news"));
  document.querySelector("#usCapturePrices").addEventListener("click",()=>capture("alpaca_prices"));
  (async () => {
    try {
      const response = await fetch('/api/v3/us/audit-summary');
      const data = await response.json();
      if (response.ok) window.dispatchEvent(new CustomEvent('us-ledger-counts', {detail: data.ledger_counts}));
      if (response.ok && !modeTouched && data.ledger_counts.scored_news > 0 && data.ledger_counts.sip_price_bars > 0 && dataMode.value === 'fixture') {
        capturedInputCache = 'AAPL, 1, 0\nMSFT, 1, 0\nNVDA, 1, 0\nJPM, 1, 0\nGS, 1, 0\nXOM, 1, 0\nCVX, 1, 0\nUNH, 1, 0\nLLY, 1, 0\nCAT, 1, 0';
        document.querySelector('#usTimeMode').value = 'replay';
        dataMode.value = 'captured'; dataMode.dispatchEvent(new Event('change'));
        return;
      }
    } catch (_) { /* Fixture remains available when ledger is unavailable. */ }
    if (!modeTouched) submit();
  })();
})();
