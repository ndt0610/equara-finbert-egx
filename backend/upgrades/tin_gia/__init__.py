"""Tầng Tin + Giá — phân tích một mã cho người đang nắm cổ phiếu.

Mô-đun này tách khỏi nâng cấp danh mục theo vốn C3. Nó không đặt lệnh và không gọi điểm portfolio,
macro-beta hoặc tỷ trọng vốn của C3 để tạo nhãn. Quote thật, nhãn đã kiểm định và dữ liệu illustrative
được giữ riêng; khi thiếu nguồn/mô hình/chi phí thì nhãn thật là null.
"""

from __future__ import annotations

PHIEN_BAN_TANG = "tin-gia-v1"
PHIEN_BAN_PHUONG_PHAP = "TG-SPEC-1"

__all__ = ["PHIEN_BAN_TANG", "PHIEN_BAN_PHUONG_PHAP"]
