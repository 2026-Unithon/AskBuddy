"""계획 8 Task 8: 로그인된 기기 이름."""
import pytest

from app.auth.devices import device_label


@pytest.mark.parametrize("ua,label", [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.1 Mobile/15E148 Safari/604.1", "아이폰 Safari"),
    ("Mozilla/5.0 (Linux; Android 15; SM-S928N) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36", "안드로이드 Chrome"),
    ("Mozilla/5.0 (Linux; Android 15; SM-S928N) AppleWebKit/537.36 SamsungBrowser/27.0 Chrome/125.0 Mobile Safari/537.36", "안드로이드 삼성 인터넷"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36", "Mac Chrome"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0", "Windows Edge"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 KAKAOTALK 10.9.0", "아이폰 카카오톡"),
    (None, "알 수 없는 기기"),
])
def test_device_label(ua, label):
    assert device_label(ua) == label
