from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.notifications.router import (
    SubscriptionKeys,
    SubscriptionRequest,
    _validate_subscription,
)
from app.notifications.service import aggregate_delivery_status, push_is_configured
from app.errors import ApiError


class NotificationPolicyTest(unittest.TestCase):
    def test_any_requested_delivery_makes_event_requested(self):
        self.assertEqual(
            aggregate_delivery_status(["FAILED", "REQUESTED"]), "REQUESTED"
        )

    def test_all_failed_deliveries_make_event_failed(self):
        self.assertEqual(aggregate_delivery_status(["FAILED", "FAILED"]), "FAILED")

    def test_no_delivery_stays_pending_for_in_app_notification(self):
        self.assertEqual(aggregate_delivery_status([]), "PENDING")

    def test_push_requires_all_vapid_settings(self):
        with patch(
            "app.notifications.service.get_settings",
            return_value=SimpleNamespace(
                vapid_public_key="public",
                vapid_private_key="",
                vapid_subject="mailto:owner@example.com",
            ),
        ):
            self.assertFalse(push_is_configured())

    def test_push_rejects_invalid_subject(self):
        with patch(
            "app.notifications.service.get_settings",
            return_value=SimpleNamespace(
                vapid_public_key="public",
                vapid_private_key="private",
                vapid_subject="not-a-contact",
            ),
        ):
            self.assertFalse(push_is_configured())

    def test_push_accepts_https_contact_subject(self):
        with patch(
            "app.notifications.service.get_settings",
            return_value=SimpleNamespace(
                vapid_public_key="public",
                vapid_private_key="private",
                vapid_subject="https://example.com",
            ),
        ):
            self.assertTrue(push_is_configured())

    def test_rejects_non_https_subscription_endpoint(self):
        request = SubscriptionRequest(
            endpoint="http://push.example.test/subscription",
            keys=SubscriptionKeys(p256dh="a" * 20, auth="b" * 8),
        )
        with self.assertRaises(ApiError) as raised:
            _validate_subscription(request)
        self.assertEqual(raised.exception.code, "INVALID_PUSH_ENDPOINT")

    def test_accepts_browser_subscription_shape(self):
        request = SubscriptionRequest(
            endpoint="https://push.example.test/subscription",
            keys=SubscriptionKeys(p256dh="a" * 20, auth="b" * 8),
        )
        _validate_subscription(request)


if __name__ == "__main__":
    unittest.main()
