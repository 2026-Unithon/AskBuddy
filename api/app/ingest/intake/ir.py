"""공통 중간 형식(IR) — 분류기와 로직 추출기는 파일이 아니라 이것만 본다(설계 4-2)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LocatorKind = Literal["PAGE", "TIME", "DATE", "LINE", "WHOLE"]


@dataclass(frozen=True)
class Locator:
    kind: LocatorKind
    start: str
    end: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class Candidate:
    """코드가 만든 경계 후보 하나. 표본이 아니면 text·images 가 비고 sampled=False 다."""
    candidate_id: str
    locator: Locator
    text: str
    images: tuple[Path, ...] = ()
    sampled: bool = True


@dataclass(frozen=True)
class ProbeResult:
    normalizer: str
    candidates: tuple[Candidate, ...]

    def sampled(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.sampled)

    def summary(self) -> dict:
        """기록용 요약. 원문은 담지 않는다(B-D6)."""
        sampled = self.sampled()
        return {"normalizer": self.normalizer, "candidates": len(self.candidates),
                "sampled": [c.candidate_id for c in sampled],
                "chars": sum(len(c.text) for c in sampled),
                "images": sum(len(c.images) for c in sampled)}

    def sample_hash(self) -> str:
        h = hashlib.sha256(self.normalizer.encode())
        for c in self.candidates:
            h.update(f"\x00{c.candidate_id}\x00{c.locator.kind}:{c.locator.start}-{c.locator.end}"
                     f"\x00{int(c.sampled)}\x00{c.text}".encode())
            for img in c.images:
                h.update(hashlib.sha256(img.read_bytes()).digest())
        return h.hexdigest()
