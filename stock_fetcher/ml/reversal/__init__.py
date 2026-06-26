"""Reversal (起漲) model.

里程碑 2：先完整複製 momentum 設定與模型，驗證雙引擎結構可正常運作。
後續里程碑會調整：
  - Label 定義（pre-filter 限定糾結態、upper/lower/holding 重新設定）
  - 特徵子集（強化糾結持續性、量縮等起漲訊號）
  - 超參數
"""
from .model import train_model, predict_today, get_model_status

__all__ = ["train_model", "predict_today", "get_model_status"]
