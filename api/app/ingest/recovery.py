"""작업 자료별 추출 복구본. 검색 캐시가 아니며 승인 지식으로 노출하지 않는다."""
import hashlib
import json
from pathlib import Path


class RecoveryConflict(RuntimeError):
    pass


def layout_hash(src, text, media, segments, settings) -> str:
    # 경로 이름 대신 실제 바이트와 순서를 비교한다. 설정 변경도 보수적으로 거절한다.
    def files(paths):
        return [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (paths or [])]

    config = {k: getattr(settings, k) for k in (
        'video_segment_sec', 'frame_interval_sec', 'video_max_frames_to_model',
        'video_input_mode', 'pdf_input_mode')}
    # 구간 겹침은 구간 내용을 바꾼다. 0(기존 동작)이면 싣지 않아 지난 복구본의 hash 가 그대로다.
    # 잘림 분할 깊이·동시 호출 수는 구간 구성(seg{i})을 바꾸지 않으므로 싣지 않는다 (W1-2)
    overlap = getattr(settings, 'video_segment_overlap_sec', 0)
    if overlap:
        config['video_segment_overlap_sec'] = overlap
    payload = dict(version=1, source_type=src['source_type'],
                   text=text, media=files(media),
                   segments=[dict(text=t, media=files(m)) for t, m in segments],
                   config=config)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def load(conn, store_id: int, job_id: int, source_id: int, *, lock=False):
    row = await conn.fetchrow(
        "select recovery_state from ingest_job_sources "
        "where store_id=$1 and job_id=$2 and source_id=$3" + (' for update' if lock else ''),
        store_id, job_id, source_id)
    if row is None:
        raise RecoveryConflict('복구할 작업 자료가 없습니다.')
    value = row['recovery_state']
    return json.loads(value) if isinstance(value, str) else value


async def replace(conn, store_id: int, job_id: int, source_id: int, expected, state):
    # 호출자의 짧은 transaction 안에서 CAS하며 실패한 호출이 다른 복구본을 덮지 않는다.
    if await load(conn, store_id, job_id, source_id, lock=True) != expected:
        raise RecoveryConflict('다른 처리에서 복구 상태를 변경했습니다.')
    await conn.execute(
        "update ingest_job_sources set recovery_state=$4::jsonb, updated_at=now() "
        "where store_id=$1 and job_id=$2 and source_id=$3",
        store_id, job_id, source_id, json.dumps(state, ensure_ascii=False))
