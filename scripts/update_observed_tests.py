from pathlib import Path
import re
root=Path(__file__).resolve().parents[1];p=root/'tests/test_coverage.py';s=p.read_text(encoding='utf-8')
s=s.replace('đóng góp, khoảng giới hạn','đóng góp từ tin đã chấm')
s=s.replace('test_example_50_30_20_gives_plus_030_and_bound_004_044','test_missing_holding_is_not_imputed_and_observed_score_is_030')
s=s.replace('test_only_40_percent_covered_gives_bound_minus036_084_and_no_direction','test_observed_score_is_not_suppressed_by_missing_capital')
s=re.sub(r'    assert out\["bound"\]\["low"\].*\n', '    assert "bound" not in out\n',s)
s=s.replace('out["direction"] == "undetermined"','out["direction"] == "positive"')
s=s.replace('out["bound"] is None','"bound" not in out')
a=s.index('            assert -1 <= out["bound"]');b=s.index('\n\ndef test_direction_',a)
s=s[:a]+'''            assert -1 <= out["score"] <= 1
            assert "bound" not in out
            assert out["score_scope"] == "observed_scored_news"
'''+s[b:]
s=s.replace('test_direction_needs_coverage_above_half_even_with_perfect_score','test_direction_describes_observed_news_regardless_of_capital_share')
a=s.index('def test_case_c_and_c2_');b=s.index('\ndef test_default_config',a)
s=s[:a]+'''def test_removed_coverage_gate_cannot_hide_observed_score(monkeypatch):
    monkeypatch.setenv("COVERAGE_MIN_FOR_SCORE", "0.99")
    config = CoverageConfig.from_environment()
    _, out = portfolio(("A", 1, 0.4), ("B", 99, None), config=config)
    assert out["score"] == pytest.approx(0.4)
    assert "min_coverage_for_score" not in config.to_dict()
    assert out["represented_symbols"] == ["A"]
    assert out["unscored_symbols"] == ["B"]

def test_all_three_scored_example_and_missing_not_same_as_neutral():
    _, out = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, 0.1))
    assert out["score"] == pytest.approx(0.26)
    assert out["coverage"] == 1
    assert out["unscored_symbols"] == []
    _, neutral = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, 0))
    _, absent = portfolio(("A", 50, 0.6), ("B", 30, -0.2), ("C", 20, None))
    assert neutral["score"] == pytest.approx(0.24)
    assert absent["score"] == pytest.approx(0.30)

def test_balanced_score_is_distinct_from_no_data():
    _, zero = portfolio(("A", 50, 0.4), ("B", 50, -0.4))
    _, empty = portfolio(("A", 100, None))
    assert zero["score"] == 0 and zero["direction"] == "balanced"
    assert empty["score"] is None and empty["direction"] == "no_company_news"

'''+s[b:]
s=s.replace('p["coverage"] == pytest.approx(1.0) and p["bound"]["low"] == pytest.approx(p["bound"]["high"])','p["coverage"] == pytest.approx(1.0) and "bound" not in p')
s=s.replace('body["portfolio"]["direction"] == "undetermined"','body["portfolio"]["score"] == pytest.approx(body["holdings"][0]["score"])')
a=s.index('def test_portfolio_explanation_');b=s.index('\ndef test_case_e_',a)
s=s[:a]+'''def test_portfolio_ui_has_observed_scope_without_hypothetical_bounds():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Các mã tham gia điểm tổng hợp" in js
    assert "không gán điểm 0" in js
    assert "boundSection" not in js and "view.bound" not in js

'''+s[b:]
p.write_text(s,encoding='utf-8')
p=root/'tests/check_browser.py';s=p.read_text(encoding='utf-8')
s=s.replace('and page.locator(".cov-collapse").count() == 1','and "Các mã tham gia điểm tổng hợp" in page.locator("#result").inner_text()')
s=s.replace('and p["bound"]','and "bound" not in p')
a=s.index('    bound_text =');b=s.index('    funnel_checks(page, data)',a)
s=s[:a]+'''    assert "HRHO: chưa có tin được chấm" in page.locator("#result").inner_text()
    assert page.locator(".cov-bound-track").count() == 0
'''+s[b:]
s=re.sub(r'    rows_out.append\(f"\| coverage \| COMI:50,ETEL:30,HRHO:20.*\n','    rows_out.append("| coverage | COMI:50,ETEL:30,HRHO:20 | POST 200 | HRHO chưa có điểm, không suy diễn | — |")\n',s)
s=re.sub(r'        expected_bounds = .*\n','        expected_bounds = 0\n',s)
p.write_text(s,encoding='utf-8')
print('Updated regression contracts for observed-only scoring')
