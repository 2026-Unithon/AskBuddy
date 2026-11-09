"""사람 눈에 같은 글인지 견줄 때 쓰는 정리. 띄어쓰기와 보이지 않는 글자(폭 0 공백·BOM 등)를 뺀다."""
from __future__ import annotations

import re

# 폭 0 공백·폭 0 비결합자·결합자·단어 결합자·BOM. str.split() 이 공백으로 보지 않는 글자들
_INVISIBLE = re.compile("[​‌‍⁠﻿]")


def squash(text: str | None) -> str:
    return _INVISIBLE.sub("", "".join((text or "").split()))
