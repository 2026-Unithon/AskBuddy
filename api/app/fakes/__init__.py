"""C0 단계의 가짜 어댑터 (CP-03).

실제 색인·전달·렌더링을 대신한다. **품질을 흉내 내는 것이 아니라 계약을 지킨다.**
W 와 R 이 서로를 기다리지 않고 각자 개발하려면 상대편 자리에 계약대로 동작하는
무언가가 있어야 한다. 여기 있는 것들은 그 자리를 채우고, R1/W4 에서 실제 구현으로
교체된다.

가짜라는 이유로 검사를 느슨하게 두지 않는다. 여기서 통과한 것이 실제 구현에서
막히면 계약이 아니라 구현에 맞춰 개발한 것이 된다.
"""
from app.fakes.indexer import FakeIndexer
from app.fakes.outbox import FakeOutbox
from app.fakes.renderer import RENDERER_VERSION, FakeRenderer, RenderError

__all__ = ["FakeIndexer", "FakeOutbox", "FakeRenderer", "RenderError",
           "RENDERER_VERSION"]
