"""계획 9 Task 10: 문의·의견 알림 메일(SES). 글은 싣지 않는다."""
import asyncio
from unittest.mock import patch

from app.bootstrap import feedback_mail


class FakeSes:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send_email(self, **kwargs):
        if self.fail:
            raise RuntimeError("ses down")
        self.sent.append(kwargs)


def settings(**over):
    base = dict(feedback_mail_from="noreply@example.com", feedback_mail_to="ops@example.com", aws_region="ap-northeast-2")
    return type("S", (), {**base, **over})()


def test_sends_kind_and_id_without_body():
    ses = FakeSes()
    with patch.object(feedback_mail, "get_settings", lambda: settings()):
        assert asyncio.run(feedback_mail.notify_feedback(feedback_id=7, kind="INQUIRY", client=ses)) is True
    mail = ses.sent[0]
    assert mail["FromEmailAddress"] == "noreply@example.com"
    assert mail["Destination"] == {"ToAddresses": ["ops@example.com"]}
    assert mail["Content"]["Simple"]["Subject"]["Data"] == "[AskBuddy] 문의 #7"
    assert "7" in mail["Content"]["Simple"]["Body"]["Text"]["Data"]


def test_idea_subject():
    ses = FakeSes()
    with patch.object(feedback_mail, "get_settings", lambda: settings()):
        asyncio.run(feedback_mail.notify_feedback(feedback_id=8, kind="IDEA", client=ses))
    assert ses.sent[0]["Content"]["Simple"]["Subject"]["Data"] == "[AskBuddy] 의견 #8"


def test_unset_config_sends_nothing():
    ses = FakeSes()
    with patch.object(feedback_mail, "get_settings", lambda: settings(feedback_mail_to="")):
        assert asyncio.run(feedback_mail.notify_feedback(feedback_id=7, kind="INQUIRY", client=ses)) is False
    assert ses.sent == []


def test_failure_is_swallowed():
    with patch.object(feedback_mail, "get_settings", lambda: settings()):
        assert asyncio.run(feedback_mail.notify_feedback(feedback_id=7, kind="INQUIRY", client=FakeSes(fail=True))) is False
