"""Notebook Colab: mọi ô code biên dịch được, và ô phần C chạy được với nguồn tin giả lập (không cần Colab)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from tests.test_coverage import fake_probs, handler_factory

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "Equara_AI_FinBERT_Colab.ipynb"


def cells():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def python_source(cell) -> str:
    # Bỏ dòng lệnh IPython (%pip …) để biên dịch bằng Python thường.
    return "\n".join("pass" if line.lstrip().startswith(("%", "!")) else line for line in "".join(cell["source"]).splitlines())


def test_every_code_cell_compiles_and_old_beta_cells_are_gone():
    for index, cell in enumerate(cells()):
        if cell["cell_type"] == "code":
            compile(python_source(cell), f"cell {index}", "exec")
    text = json.dumps(cells(), ensure_ascii=False)
    assert "MÃ:VỐN%:BETA" not in text and "analyze_portfolio_weighted" not in text
    assert "[NÂNG CẤP C] Nạp dự án và phần C" in text and "Nạp 3 module" not in text


def test_part_c_cell_runs_with_mocked_news(monkeypatch, capsys):
    source = next(python_source(c) for c in cells() if "".join(c["source"]).startswith("# [NÂNG CẤP C] Nạp dự án"))
    calls: list[str] = []
    real_client = httpx.AsyncClient

    class MockedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler_factory(calls))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", MockedClient)
    shown = []
    namespace = {
        "PROJECT_DIR": str(ROOT),
        "MODEL_REVISION": "0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031",
        "DEVICE": "cpu",
        "classify_texts": lambda texts: [fake_probs(t) for t in texts],
        "get_eodhd_api_token": lambda: None,
        "display": shown.append,
        "pd": pytest.importorskip("pandas"),
    }
    exec(compile(source, "part_c_cell", "exec"), namespace)
    result = namespace["run_coverage"]("COMI:50, ETEL:30, FWRY:20")
    namespace["display_coverage"](result)
    assert result["portfolio"]["coverage"] == pytest.approx(0.8)  # FWRY không có tin phù hợp trong nguồn giả lập
    assert result["config"]["experimental_options_on"] == []
    printed = capsys.readouterr().out
    assert "Vốn được đại diện: 80% vốn" in printed and "không phải tư vấn đầu tư" in printed
    assert "Khoảng giới hạn" not in printed and "Chỉ tổng hợp tin đã chấm" in printed
    assert len(shown) >= 4
    with pytest.raises(ValueError):
        namespace["parse_positions"]("COMI:50, COMI:50")
