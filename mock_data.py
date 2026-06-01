"""Mock data for UI development — no external API calls needed."""
from __future__ import annotations

import random
from datetime import date, timedelta

# ── AAPL ──────────────────────────────────────────────────────────────────────
_AAPL: dict = {
    "symbol": "AAPL",
    "is_mock": True,
    "latest_quote": {
        "symbol": "AAPL",
        "current_price": 302.12,
        "previous_close": 298.97,
        "market_cap": 4_437_343_923_004,
        "currency": "USD",
        "query_time": "2026-05-21T10:00:00",
    },
    "kline_7d": [
        {"date": "2026-05-12", "open": 292.56, "high": 295.27, "low": 290.10, "close": 294.80, "volume": 45_748_100},
        {"date": "2026-05-13", "open": 293.50, "high": 300.92, "low": 292.30, "close": 298.87, "volume": 52_684_300},
        {"date": "2026-05-14", "open": 299.82, "high": 300.45, "low": 295.38, "close": 298.21, "volume": 35_324_900},
        {"date": "2026-05-15", "open": 297.90, "high": 303.20, "low": 296.52, "close": 300.23, "volume": 54_862_800},
        {"date": "2026-05-18", "open": 300.24, "high": 300.66, "low": 294.91, "close": 297.84, "volume": 34_483_000},
        {"date": "2026-05-19", "open": 296.97, "high": 300.51, "low": 296.35, "close": 298.97, "volume": 42_199_700},
        {"date": "2026-05-20", "open": 298.18, "high": 303.80, "low": 297.50, "close": 302.12, "volume": 23_053_202},
    ],
    "catalysts": [
        {
            "original_title": "Apple Reports Record Q2 Revenue of $98B, Services Hits All-Time High",
            "link": "https://example.com/aapl-q2",
            "published": "2026-05-15T22:00:00",
            "source": "Bloomberg",
            "sentiment": "Bullish",
            "catalyst_type": "earnings",
            "summary": "蘋果Q2營收破紀錄達980億美元，超預期5%；服務業務貢獻276億創歷史新高，EPS 1.65美元優於預期。",
        },
        {
            "original_title": "Apple Intelligence Gains 40M Users, JPMorgan Upgrades to Buy With $360 Target",
            "link": "https://example.com/aapl-upgrade",
            "published": "2026-05-18T14:30:00",
            "source": "JPMorgan",
            "sentiment": "Bullish",
            "catalyst_type": "analyst_rating",
            "summary": "摩根大通將AAPL目標價上調至360美元，因Apple Intelligence用戶3個月內突破4000萬，超預期40%。",
        },
        {
            "original_title": "EU Launches Antitrust Probe Into Apple App Store, Up to $5B Fine at Risk",
            "link": "https://example.com/aapl-eu",
            "published": "2026-05-19T09:00:00",
            "source": "Reuters",
            "sentiment": "Bearish",
            "catalyst_type": "regulation",
            "summary": "歐盟對App Store展開反壟斷調查，若裁定違規最高罰款50億美元，盤前股價應聲下跌2.3%。",
        },
        {
            "original_title": "Apple Vision Pro 2 Mass Production Starts, $2,499 Price Tag for Q4 2026",
            "link": "https://example.com/aapl-vp2",
            "published": "2026-05-20T11:00:00",
            "source": "Nikkei Asia",
            "sentiment": "Neutral",
            "catalyst_type": "product_launch",
            "summary": "Vision Pro 2開始量產，售價下調至2499美元（原3499），預計Q4上市，市場反應多空交織。",
        },
    ],
    "sentiment_summary": {"bullish": 2, "bearish": 1, "neutral": 1, "total": 4},
}

# ── TSLA ──────────────────────────────────────────────────────────────────────
_TSLA: dict = {
    "symbol": "TSLA",
    "is_mock": True,
    "latest_quote": {
        "symbol": "TSLA",
        "current_price": 184.35,
        "previous_close": 196.72,
        "market_cap": 591_432_000_000,
        "currency": "USD",
        "query_time": "2026-05-21T10:00:00",
    },
    "kline_7d": [
        {"date": "2026-05-12", "open": 198.50, "high": 202.30, "low": 195.80, "close": 196.72, "volume": 89_234_500},
        {"date": "2026-05-13", "open": 196.72, "high": 198.90, "low": 190.20, "close": 192.45, "volume": 112_456_700},
        {"date": "2026-05-14", "open": 191.00, "high": 195.40, "low": 188.60, "close": 189.30, "volume": 98_321_400},
        {"date": "2026-05-15", "open": 190.00, "high": 193.20, "low": 185.10, "close": 187.80, "volume": 134_567_800},
        {"date": "2026-05-18", "open": 185.00, "high": 189.90, "low": 182.30, "close": 188.45, "volume": 87_654_300},
        {"date": "2026-05-19", "open": 188.50, "high": 191.00, "low": 182.80, "close": 183.20, "volume": 102_345_600},
        {"date": "2026-05-20", "open": 182.00, "high": 187.50, "low": 180.10, "close": 184.35, "volume": 76_543_200},
    ],
    "catalysts": [
        {
            "original_title": "Tesla Q1 Deliveries Miss by 20%, Worst Quarter Since 2020",
            "link": "https://example.com/tsla-q1",
            "published": "2026-05-13T06:00:00",
            "source": "Wall Street Journal",
            "sentiment": "Bearish",
            "catalyst_type": "earnings",
            "summary": "Tesla Q1交車量34.7萬輛，較預期低20%，創2020年以來最差季度；EPS 0.45美元遠遜預期0.73美元。",
        },
        {
            "original_title": "Elon Musk Commits to Staying as Tesla CEO Through 2027",
            "link": "https://example.com/tsla-musk",
            "published": "2026-05-16T18:00:00",
            "source": "Financial Times",
            "sentiment": "Bullish",
            "catalyst_type": "management",
            "summary": "馬斯克公開承諾至少執掌Tesla至2027年，並排除出售持股計畫，緩解市場對其分心於其他業務的擔憂。",
        },
        {
            "original_title": "NHTSA Opens Formal Investigation Into Tesla FSD After 3 Fatal Crashes",
            "link": "https://example.com/tsla-nhtsa",
            "published": "2026-05-19T14:00:00",
            "source": "Reuters",
            "sentiment": "Bearish",
            "catalyst_type": "litigation",
            "summary": "美國NHTSA就Tesla FSD系統涉及3起死亡事故展開正式調查，可能觸發大規模召回，股價下跌4.1%。",
        },
    ],
    "sentiment_summary": {"bullish": 1, "bearish": 2, "neutral": 0, "total": 3},
}

# ── NVDA ──────────────────────────────────────────────────────────────────────
_NVDA: dict = {
    "symbol": "NVDA",
    "is_mock": True,
    "latest_quote": {
        "symbol": "NVDA",
        "current_price": 1087.45,
        "previous_close": 1052.30,
        "market_cap": 2_678_000_000_000,
        "currency": "USD",
        "query_time": "2026-05-21T10:00:00",
    },
    "kline_7d": [
        {"date": "2026-05-12", "open": 1020.00, "high": 1045.50, "low": 1015.20, "close": 1038.90, "volume": 34_567_800},
        {"date": "2026-05-13", "open": 1038.90, "high": 1062.30, "low": 1032.10, "close": 1055.70, "volume": 42_345_600},
        {"date": "2026-05-14", "open": 1055.70, "high": 1068.90, "low": 1048.20, "close": 1052.30, "volume": 38_921_300},
        {"date": "2026-05-15", "open": 1050.00, "high": 1075.40, "low": 1047.80, "close": 1068.50, "volume": 51_234_700},
        {"date": "2026-05-18", "open": 1070.00, "high": 1095.60, "low": 1062.30, "close": 1082.10, "volume": 45_678_900},
        {"date": "2026-05-19", "open": 1080.00, "high": 1088.90, "low": 1065.40, "close": 1071.30, "volume": 39_876_500},
        {"date": "2026-05-20", "open": 1072.00, "high": 1098.50, "low": 1068.90, "close": 1087.45, "volume": 28_945_600},
    ],
    "catalysts": [
        {
            "original_title": "NVIDIA Q1 Revenue Hits Record $26B, Data Center Up 427% YoY",
            "link": "https://example.com/nvda-q1",
            "published": "2026-05-15T20:00:00",
            "source": "Bloomberg",
            "sentiment": "Bullish",
            "catalyst_type": "earnings",
            "summary": "NVIDIA Q1營收260億美元創歷史新高，數據中心年增427%；預計Q2營收280億，再度超出市場預期。",
        },
        {
            "original_title": "US Expands AI Chip Export Restrictions to 40 More Countries",
            "link": "https://example.com/nvda-export",
            "published": "2026-05-17T16:00:00",
            "source": "Wall Street Journal",
            "sentiment": "Bearish",
            "catalyst_type": "regulation",
            "summary": "美國擴大AI晶片出口管制至40個新增國家，NVIDIA估計年損失約30億美元營收，盤前跌3.5%。",
        },
        {
            "original_title": "Microsoft Signs $10B Blackwell GPU Deal With NVIDIA Through 2027",
            "link": "https://example.com/nvda-msft",
            "published": "2026-05-19T11:00:00",
            "source": "Reuters",
            "sentiment": "Bullish",
            "catalyst_type": "m_and_a",
            "summary": "微軟與NVIDIA簽訂100億美元Blackwell GPU採購協議，鎖定至2027年，大幅提升NVIDIA營收能見度。",
        },
    ],
    "sentiment_summary": {"bullish": 2, "bearish": 1, "neutral": 0, "total": 3},
}

# ── Registry & fallback ────────────────────────────────────────────────────────
_REGISTRY: dict[str, dict] = {"AAPL": _AAPL, "TSLA": _TSLA, "NVDA": _NVDA}


def get_mock_response(ticker: str) -> dict:
    if ticker in _REGISTRY:
        return _REGISTRY[ticker]
    return _build_generic(ticker)


def _build_generic(ticker: str) -> dict:
    rng = random.Random(ticker)
    base = rng.uniform(50, 500)
    klines, price = [], base
    d = date(2026, 5, 12)
    for _ in range(9):
        if d.weekday() < 5:
            o = round(price, 2)
            h = round(o * rng.uniform(1.003, 1.018), 2)
            l = round(o * rng.uniform(0.982, 0.997), 2)
            c = round(rng.uniform(l, h), 2)
            klines.append({"date": str(d), "open": o, "high": h, "low": l, "close": c,
                            "volume": rng.randint(5_000_000, 80_000_000)})
            price = c
            if len(klines) == 7:
                break
        d += timedelta(days=1)

    current = klines[-1]["close"] if klines else base
    prev = klines[-2]["close"] if len(klines) > 1 else base

    return {
        "symbol": ticker,
        "is_mock": True,
        "latest_quote": {
            "symbol": ticker, "current_price": current, "previous_close": prev,
            "market_cap": int(current * rng.randint(100_000_000, 5_000_000_000)),
            "currency": "USD", "query_time": "2026-05-21T10:00:00",
        },
        "kline_7d": klines,
        "catalysts": [],
        "sentiment_summary": {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0},
    }
