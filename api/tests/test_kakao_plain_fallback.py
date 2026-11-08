"""카카오톡 내보내기가 아닌 .txt(일반 메모)는 실패하지 않고 일반 글로 읽는다(2026-11-08 사용자 실화면)."""
import pytest

from app.ingest.preprocess import kakao


def test_plain_memo_is_read_as_text():
    memo = "마감 때는 머신 청소\n원두 소분하고 쓰레기 정리\n"
    parsed = kakao.parse_or_plain(memo, message_numbers=False)
    assert parsed["message_count"] == 0
    assert parsed["parsed_text"] == "마감 때는 머신 청소\n원두 소분하고 쓰레기 정리"
    assert parsed["participants"] == []


def test_real_export_still_parsed():
    export = "2026년 11월 8일 오전 9:00, 사장 : 우유는 월목 발주\n"
    parsed = kakao.parse_or_plain(export, message_numbers=False)
    assert parsed["message_count"] == 1


def test_empty_file_still_fails():
    with pytest.raises(kakao.NotKakaoExport):
        kakao.parse_or_plain("   \n", message_numbers=False)
