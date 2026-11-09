from pathlib import Path
import re,zipfile
root=Path(__file__).resolve().parents[1]
files=['backend/upgrades/coverage.py','frontend/app.js','frontend/index.html','tests/test_coverage.py']
with zipfile.ZipFile(root/'artifacts/before_observed_scope.zip','w') as z:
    for f in files:z.write(root/f,f)
p=root/files[0];s=p.read_text(encoding='utf-8')
end=s.index('"""',3)+3
s='''"""Tổng hợp sắc thái từ các tin đã thu thập và chấm, theo vốn từng mã.

s_i là điểm tin của mã; w_i là tỷ trọng vốn. Chỉ các mã có điểm mới tham gia:
C = tổng w_i của các mã có điểm; r_i = w_i/C; đóng góp = r_i*s_i; S = tổng đóng góp.
C chỉ mô tả phạm vi vốn được đại diện, không đo tỷ lệ thông tin thu đủ.
Không gán điểm hay tính khoảng giả định cho mã chưa có dữ liệu.
Tin vĩ mô hiển thị riêng. Khi không có vốn nào có điểm, S=None.
"""'''+s[end:]
s=s.replace('METHOD_VERSION = "coverage-v2"','METHOD_VERSION = "observed-capital-v3"')
s=re.sub(r'^    min_coverage_for_score:.*\n','',s,flags=re.M)
s=re.sub(r'        if self.min_coverage_for_score is not None and[^\n]+:\n            raise ValueError\([^\n]+\)\n','',s)
s=re.sub(r'^            min_coverage_for_score=.*\n','',s,flags=re.M)
s=re.sub(r'        if self.min_coverage_for_score is not None:\n            on.append\([^\n]+\)\n','',s)
a=s.index('DIRECTION_TEXT =');b=s.index('\n\ndef summarize_portfolio',a)
s=s[:a]+'''DIRECTION_TEXT = {
    "positive": "Điểm tổng hợp của các tin đã chấm nghiêng tích cực; chỉ đại diện cho các mã có điểm.",
    "negative": "Điểm tổng hợp của các tin đã chấm nghiêng tiêu cực; chỉ đại diện cho các mã có điểm.",
    "balanced": "Điểm tổng hợp của các tin đã chấm bằng 0; không suy diễn cho mã chưa có dữ liệu.",
    "no_company_news": "Chưa có tin được chấm cho phần vốn đã nhập, nên chưa có điểm tổng hợp.",
}'''+s[b:]
s=s.replace('Tính w_i, C, r_i, c_i, S, khoảng giới hạn, hướng và phần vốn theo nhãn.','Tính điểm quan sát theo vốn, đóng góp từng mã và phạm vi kết quả.')
s=s.replace('    bound: dict[str, float] | None = None\n','')
a=s.index('        gap = 1.0 - coverage');b=s.index('\n    return {',a)
s=s[:a]+'''        direction = "positive" if score > 0 else "negative" if score < 0 else "balanced"
'''+s[b:]
s=re.sub(r'^        "(?:bound|bound_rule|bound_is_not|min_coverage_for_score)":.*\n','',s,flags=re.M)
s=s.replace('        "coverage": coverage,','''        "score_scope": "observed_scored_news",
        "represented_symbols": [h.symbol for h in covered if h.w > 0],
        "unscored_symbols": [h.symbol for h in holdings if h.w > 0 and not h.has_news],
        "scope_note": "Chỉ tổng hợp tin đã chấm. Tỷ trọng vốn được đại diện không đo mức đầy đủ của tin; mã chưa có dữ liệu không được gán điểm.",
        "coverage": coverage,''')
p.write_text(s,encoding='utf-8')

p=root/'frontend/app.js';s=p.read_text(encoding='utf-8')
a=s.index('  let score = null;',s.index('function portfolioView'));b=s.index('\n}',a)
s=s[:a]+'''  const score = rawScore;
  const direction = score === null ? "no_company_news" : score > 0 ? "positive" : score < 0 ? "negative" : "balanced";
  return finishView({ rows, coverage, score, rawScore, direction });'''+s[b:]
s=s.replace('    bound: p.bound,\n','')
a=s.index('  const bothBound',s.index('function matchesBackend'));b=s.index('\n}',a)
s=s[:a]+'''  return close(view.coverage, portfolio.coverage) && close(view.score, portfolio.score);'''+s[b:]
a=s.index('// ---------- Dải khoảng giới hạn');b=s.index('// ---------- Mục tham khảo',a)
s=s[:a]+'''// ---------- Phạm vi của điểm quan sát ----------
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

'''+s[b:]
s=s.replace('boundSection(', 'observedScopeSection(')
a=s.index('  if (view.bound) {',s.index('function calcLines'));b=s.index('  return lines;',a)
s=s[:a]+s[b:]
s=re.sub(r'^  if \(!view.full && view.bound\).*\n','',s,flags=re.M)
s=s.replace('phần vốn này được để ngoài S và đưa vào khoảng giới hạn.','mã này chưa có điểm, nên không tham gia S. Hệ thống không gán điểm thay thế.')
s=s.replace('Cả danh mục có thể nằm ở đâu thì xem dải khoảng bên dưới.','Không suy diễn kết quả cho các mã chưa có dữ liệu.')
s=s.replace('fact("Độ phủ vốn"','fact("Vốn được đại diện"')
s=s.replace('vốn được phủ','vốn được đại diện')
s=s.replace('// khoảng = [C·S − (1 − C), C·S + (1 − C)]. Mã không tìm thấy tin: r và c là null, không phải 0.','// Chỉ tính từ tin đã chấm. Mã chưa có dữ liệu: r và c là null, không gán điểm 0.')
s=s.replace('//   3. Dải khoảng giới hạn chỉ khi còn vốn chưa có tin; đủ 100% thì thay bằng một câu giải thích.','//   3. Liệt kê mã được tính và mã chưa có dữ liệu, không suy diễn điểm ngoài tập tin đã chấm.')
s=s.replace('rồi đối chiếu S, C và khoảng của A','rồi đối chiếu S và phạm vi vốn của A')
a=s.index('function emptyScoreText(');b=s.index('\n}',a)
s=s[:a]+'''function emptyScoreText(direction) {
  return "Chưa có dữ liệu để tính điểm";'''+s[b:]
p.write_text(s,encoding='utf-8')
p=root/'frontend/index.html';s=p.read_text(encoding='utf-8').replace('tin-gia-rules-v2','observed-capital-v3')
s=s.replace('xem sắc thái tiêu đề được tìm thấy phủ tới bao nhiêu phần vốn và mã nào đóng góp vào điểm.','tổng hợp điểm các tin đã thu thập và chấm theo tỷ trọng vốn; xem từng mã đóng góp bao nhiêu vào kết quả.')
s=s.replace('S chỉ tính sắc thái trên phần vốn có tiêu đề qua bộ lọc; phần vốn không có tin được thể hiện riêng.','Điểm tổng hợp chỉ dùng các mã có tin đã chấm. Mã chưa có dữ liệu được thông báo riêng, không tự gán điểm; tỷ trọng của các mã có điểm được chuẩn hóa lại.')
p.write_text(s,encoding='utf-8')
print('Migrated backend and both single/comparison views to observed news only')
