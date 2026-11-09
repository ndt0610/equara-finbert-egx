// Explicit extension of the ORIGINAL headline mean, not an equal-stock mean.
function capitalFromOriginal(data, positions) {
  const normalize = s => String(s).trim().toUpperCase().replace(/\.EGX$/, "") + ".EGX";
  const symbols = positions.map(p => normalize(p.symbol));
  const weights = positions.map(p => Number(p.weight));
  if (!symbols.length || new Set(symbols).size !== symbols.length || weights.some(w => !Number.isFinite(w) || w < 0) || !weights.some(w => w > 0)) throw new Error("Mã không trùng; vốn không âm và tổng vốn phải lớn hơn 0.");
  if (symbols.length !== data.symbols.length || data.symbols.some(s => !symbols.includes(normalize(s)))) throw new Error("Danh sách mã khác lô tin gốc; cần lấy lô tin đúng danh sách.");
  const total = weights.reduce((a,b) => a+b,0), k = symbols.length;
  const rows = data.headlines.map(h => {
    const score = Number(h.probabilities.positive) - Number(h.probabilities.negative);
    const index = h.kind === "macro" ? -1 : symbols.indexOf(normalize(h.symbol));
    if (!Number.isFinite(score) || (h.kind !== "macro" && index < 0)) throw new Error("Không xác minh được điểm hoặc mã của tin gốc.");
    return { ...h, score, multiplier: h.kind === "macro" ? 1 : k * weights[index] / total };
  });
  const denominator = rows.reduce((a,r) => a+r.multiplier,0);
  for (const row of rows) {
    row.share = denominator > 0 ? row.multiplier / denominator : null;
    row.contribution = row.share === null ? null : row.share * row.score;
  }
  return {rows, denominator, score: denominator > 0 ? rows.reduce((a,r) => a+r.contribution,0) : null,
    baseline: rows.length ? rows.reduce((a,r) => a+r.score,0)/rows.length : null,
    groups: symbols.map((symbol,i) => ({symbol, capital: weights[i]/total, rows: rows.filter(r => r.kind !== "macro" && normalize(r.symbol) === symbol)}))};
}

// In-memory snapshot only. Both tabs reuse the exact response, including probabilities.
let originalPortfolioSnapshot = null;
function originalKey(symbols) { return symbols.map(s => String(s).trim().toUpperCase().replace(/\.EGX$/, "")).sort().join(","); }
async function useOriginalPortfolio(symbols, button, render, fresh = false) {
  if (!symbols.length || symbols.length > 5 || new Set(symbols.map(s=>originalKey([s]))).size !== symbols.length) {
    renderError({error:{message:"Nhập từ 1–5 mã, không trùng nhau."}}); return;
  }
  const key = originalKey(symbols);
  if (!fresh && originalPortfolioSnapshot?.key === key) { render(originalPortfolioSnapshot.data); return; }
  await submitAnalysis('/api/sentiment/portfolio?' + new URLSearchParams({symbols:symbols.join(',')}), null, button, data => {
    originalPortfolioSnapshot = {key,data}; render(data);
  });
}
function originalSnapshotNote(data, onRefresh) {
  const box = node('section','cov-summary');
  box.append(node('h3','table-title','Lô tin dùng chung với bản gốc'));
  const time = data.data_freshness?.completed_at_utc || data.data_freshness?.requested_at_utc;
  box.append(node('p','method-note',`${data.headlines.length} tiêu đề; giữ nguyên xác suất FinBERT và cả tin vĩ mô. ${time ? 'Thời điểm lô tin: '+formatClock(time,true)+'. ' : ''}Hai tab dùng lại lô này khi cùng danh sách mã. Chỉ nút bên dưới mới lấy lô mới; không tự làm mới ngầm.`));
  const b=node('button','link-button','Lấy lô tin mới cho cả hai tab'); b.type='button'; b.addEventListener('click',()=>onRefresh(b));box.append(b);return box;
}
function renderOriginalPortfolio(data) {
  renderSuccessfulResult(data);
  // Original freshness block describes initial collection; this note makes reuse explicit.
  resultPanel.prepend(originalSnapshotNote(data, b=>useOriginalPortfolio(data.symbols,b,renderOriginalPortfolio,true)));
}
function renderOriginalCapital(data, positions, positionsB = null) {
  resultPanel.replaceChildren();
  resultPanel.append(node('h2','','Bản gốc và bản điều chỉnh theo vốn'));
  resultPanel.append(originalSnapshotNote(data,b=>useOriginalPortfolio(data.symbols,b,d=>renderOriginalCapital(d,positions,positionsB),true)));
  const sets = positionsB ? [['A',positions],['B',positionsB]] : [['',positions]];
  for (const [name, initial] of sets) {
    const section=node('section','cov-summary');
    section.append(node('h3','table-title',name ? `Danh mục ${name} so với bản gốc` : 'Cùng đầu vào; chỉ điều chỉnh trọng số'));
    const controls=node('div','cov-facts'), cards=node('div','cov-ab-grid'), detail=node('div',''), status=node('p','method-note');
    const inputs=initial.map(p=>{
      const label=node('label','',`${p.symbol} · phần vốn `), input=node('input','');
      input.type='number';input.min='0';input.step='any';input.value=p.weight;input.setAttribute('aria-label',`Vốn cùng bản gốc ${name} ${p.symbol}`.trim());
      label.append(input);controls.append(label);return input;
    });
    const render=()=>{
      cards.replaceChildren();detail.replaceChildren();
      const current=initial.map((p,i)=>({...p,weight:Number(inputs[i].value)}));
      let result;try {result=capitalFromOriginal(data,current);} catch(e) {status.textContent=e.message;return;}
      current.forEach((p,i)=>{initial[i].weight=p.weight;});
      for(const [title,score] of [['Bản gốc: mỗi tin một phiếu',data.score],['Điều chỉnh trọng số theo vốn',result.score]]) {
        const card=node('div','cov-ab-card');card.append(node('div','result-kicker',title),node('strong','cov-ab-score',score==null?'Chưa có điểm':vSigned(score,6)));cards.append(card);
      }
      const delta=result.score==null?null:result.score-data.score;
      status.textContent=delta==null?'Không có tin mang trọng số dương; không gán điểm 0.':`Chênh lệch với chính bản gốc: ${vSigned(delta,6)}. ${Math.abs(delta)<1e-9?'Hai kết quả bằng nhau.':'Đầu vào không đổi; chênh lệch đến từ trọng số.'} Đổi vốn trong khung cập nhật toàn bộ kết quả bên dưới, không lấy/chấm tin mới.`;
      if (Math.abs(result.baseline-data.score)>1e-9) {status.textContent='Điểm gốc không khớp xác suất trong lô tin; dừng so sánh.';cards.replaceChildren();return;}
      const groups=result.groups.map(g=>[g.symbol, vPct(g.capital),String(g.rows.length),g.rows.length ? vSigned(g.rows.reduce((s,r)=>s+r.score,0)/g.rows.length,6) : 'Không có tin riêng',vPct(g.rows.reduce((s,r)=>s+(r.share||0),0)),result.score==null?'—':vSigned(g.rows.reduce((s,r)=>s+(r.contribution||0),0),6)]);
      const macro=result.rows.filter(r=>r.kind==='macro');
      groups.push(['Vĩ mô chung','Không phải khoản vốn',String(macro.length),macro.length?vSigned(macro.reduce((s,r)=>s+r.score,0)/macro.length,6):'Không có tin',vPct(macro.reduce((s,r)=>s+(r.share||0),0)),result.score==null?'—':vSigned(macro.reduce((s,r)=>s+(r.contribution||0),0),6)]);
      detail.append(stackTable(['Nhóm tin','Vốn nhập','Số tin','Điểm trung bình','Tỷ trọng trong phép tính','Đóng góp vào điểm'],groups));
      const missing=result.groups.filter(g=>!g.rows.length).map(g=>g.symbol);
      if(missing.length) detail.append(node('p','method-note',`Không có tin riêng của ${missing.join(', ')} trong lô bản gốc. Không suy ra sắc thái các mã này từ vĩ mô và không tự gán điểm tin cho chúng.`));
      detail.append(node('p','method-note','Tỷ trọng trong phép tính còn phụ thuộc số bài của từng mã và số tin vĩ mô, nên không bằng tỷ trọng vốn nhập. Đây là điều chỉnh từng tin theo vốn để kế thừa đúng bản gốc, không phải trung bình điểm mã thuần theo vốn.'));
      const articles=foldout('Từng tin đóng góp bao nhiêu vào điểm?');
      articles.append(stackTable(['Tiêu đề','Nhóm','Điểm tin x','Hệ số q','Tỷ trọng q / Σq','Đóng góp q × x / Σq'],result.rows.map(r=>[safeLink(r.url,r.title)||r.title,r.kind==='macro'?'Vĩ mô':r.symbol,vSigned(r.score,6),viDigits(r.multiplier,4),r.share==null?'—':vPct(r.share),r.contribution==null?'—':vSigned(r.contribution,6)])));
      detail.append(articles);
    };
    inputs.forEach(input=>input.addEventListener('input',render));
    section.append(controls,cards,status,detail);resultPanel.append(section);render();
  }
  const formula=foldout('Vì sao chia vốn đều thì bằng đúng bản gốc?');formula.open=true;
  formula.append(node('p','','K là số mã đang so; wᵢ là vốn mã i chia tổng vốn. Tin riêng mã i: q = K × wᵢ. Tin vĩ mô: q = 1. Điểm S = Σ(q × x) / Σq, với x = P(tích cực) − P(tiêu cực).'));
  formula.append(node('p','','Chia vốn đều: wᵢ = 1/K nên mọi q = 1, kể cả vĩ mô. Công thức trở về đúng trung bình từng tiêu đề của bản gốc. K chỉ là số mã, không phải ngưỡng tối ưu. Hệ số vĩ mô cố định 1 giữ nguyên trọng số nền của từng bài; đây là quy ước kế thừa bản gốc, không đo độ nhạy kinh tế.'));
  formula.append(node('p','','Không bổ sung tin, lọc lại, tách vĩ mô khỏi điểm hoặc đổi xác suất so với tab gốc. Cách này cũng kế thừa hạn chế của tập tin gốc. Đóng góp hiển thị là số học vào điểm; không phải mức tin làm giá thay đổi.'));
  resultPanel.append(formula);addProviderSummary(data);resultPanel.classList.remove('hidden');
}
