"""준혁 — 임베딩 적재.

임베딩 생성 자체의 모델·차원은 app.config 가 단일 출처다 (D4).
"""
from app.ingest.embed.service import embed_card

__all__ = ["embed_card"]
