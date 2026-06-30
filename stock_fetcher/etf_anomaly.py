"""
ETF 價格異常偵測：標記單日 |return| 超過閾值的事件。

設計原則：
- 純偵測，不修改原始資料
- 用 close（非 adj_close）偵測，因為 adj_close 已被 yfinance 套用權息調整，
  反而會把真的瑕疵藏起來
- 推測可能的調整因子（×2/×4/×10 等常見分割比），協助使用者手動修補
"""
from __future__ import annotations

# 異常閾值：單日 |return| 超過 30% 視為可疑
DEFAULT_THRESHOLD = 0.30

# 常見分割/合併因子，用來推測「應該乘以多少才會連續」
COMMON_FACTORS = [2, 3, 4, 5, 10]


def detect_price_anomalies(prices: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """
    偵測單日大幅跳動的異常事件。

    Args:
        prices: [{"date": "YYYY-MM-DD", "close": float, ...}, ...]，需依日期升序
        threshold: 單日 return 絕對值閾值（0.30 = 30%）

    Returns:
        [{
            "date": "2014-01-02",
            "prev_date": "2013-12-31",
            "prev_close": 58.70,
            "close": 14.67,
            "return_pct": -75.04,
            "suggested_factor": 4,
            "suggested_action": "可能漏掉 1:4 分割調整，前段資料 ÷ 4 才會連續",
        }, ...]
    """
    anomalies: list[dict] = []
    prev = None
    for p in prices:
        close = p.get("close")
        if close is None or close <= 0:
            continue
        if prev is not None:
            ret = (close - prev["close"]) / prev["close"]
            if abs(ret) >= threshold:
                anomalies.append(_build_anomaly(prev, p, ret))
        prev = p
    return anomalies


def _build_anomaly(prev: dict, curr: dict, ret: float) -> dict:
    factor, action = _suggest_factor(prev["close"], curr["close"])
    return {
        "date": curr["date"],
        "prev_date": prev["date"],
        "prev_close": round(prev["close"], 4),
        "close": round(curr["close"], 4),
        "return_pct": round(ret * 100, 2),
        "suggested_factor": factor,
        "suggested_action": action,
    }


def _suggest_factor(prev_close: float, curr_close: float) -> tuple[int | None, str]:
    """
    從前後價格比推測可能的調整因子。
    若 prev/curr 接近某個整數因子（誤差 < 5%），就建議該因子。
    """
    if curr_close <= 0:
        return None, "無法推測（價格 0）"
    ratio = prev_close / curr_close  # >1 表示「跌」（前高後低，可能漏調分割）
    inv_ratio = curr_close / prev_close  # >1 表示「漲」（可能漏調合併）

    for f in COMMON_FACTORS:
        if abs(ratio - f) / f < 0.05:
            return f, f"可能漏掉 1:{f} 分割調整，前段資料 ÷ {f} 才會連續"
        if abs(inv_ratio - f) / f < 0.05:
            return f, f"可能漏掉 {f}:1 合併調整，前段資料 × {f} 才會連續"
    return None, "非整數倍跳動，可能為真實事件或資料缺失"
