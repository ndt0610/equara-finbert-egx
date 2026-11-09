"""Ba module nâng cấp cho bản tái dựng Equara AI / FinBERT.

1. time_confidence      — Trọng số thời gian (Time-Decay) × độ rõ ràng (Confidence Weight)
2. portfolio_weighting  — Tỷ trọng vốn + hệ số nhạy cảm vĩ mô (macro beta)
3. ttl_cache + charts   — Bộ nhớ đệm TTL và tự động xuất 3 biểu đồ PNG

Phần lõi (backend/services/sentiment.py, backend/providers/*) không bị sửa.
"""
