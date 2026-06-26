"""Momentum continuation model (沿用原 ml_model 設定).

Public API:
    train_model(): Walk-forward training
    predict_today(): Inference on latest data
    get_model_status(): Check trained model metadata
"""
from .model import train_model, predict_today, get_model_status

__all__ = ["train_model", "predict_today", "get_model_status"]
