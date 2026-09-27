"""준혁 — 카드 임베딩 비용 귀속.

임베딩 생성 자체의 모델·차원은 app.config 가 단일 출처다 (D4).
색인 적재는 publish_cards → R 색인 준비 경로 하나다.
"""
from app.ingest.embed.service import card_usage_context

__all__ = ["card_usage_context"]
