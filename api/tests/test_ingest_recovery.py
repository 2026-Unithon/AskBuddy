"""동일 개수의 구간 변경을 같은 구간으로 보지 않는 회귀."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest

from app.ingest import recovery


def settings(**kw):
    return NS(**(dict(video_segment_sec=60, frame_interval_sec=3,
        video_max_frames_to_model=20, video_input_mode='frames', pdf_input_mode='HYBRID') | kw))


def test_same_count_changed_content_settings_and_media_are_distinct(tmp_path):
    image = tmp_path / 'frame'
    image.write_bytes(b'first')
    src = dict(source_type='VIDEO')
    def fingerprint(text='original', config=None):
        return recovery.layout_hash(src, '', [], [(text, [image])], config or settings())
    baseline = fingerprint()
    assert baseline == fingerprint()
    assert baseline != fingerprint('changed')
    assert baseline != fingerprint(config=settings(video_segment_sec=120))
    image.write_bytes(b'second')
    assert baseline != fingerprint()


@pytest.mark.asyncio
async def test_recovery_scope_and_stale_write_rejected():
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    with pytest.raises(recovery.RecoveryConflict):
        await recovery.load(conn, 2, 3, 4)
    assert conn.fetchrow.await_args.args[1:] == (2, 3, 4)
    conn.fetchrow.return_value = {'recovery_state': {'phase': 'COMMITTED'}}
    with pytest.raises(recovery.RecoveryConflict):
        await recovery.replace(conn, 1, 3, 4, None, {})
    conn.execute.assert_not_awaited()
