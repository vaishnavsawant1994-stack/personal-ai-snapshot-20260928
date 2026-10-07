from __future__ import annotations

from datetime import datetime, timezone

from notifications.service import DEFAULT_PREFERENCES, NotificationService, _inside_quiet_hours


class Registry:
    def __init__(self):
        self.devices = [{'id': 'trusted-1', 'revoked': 0, 'metadata': {'push.apns.token': ''}}]
        self.values = {}

    def metadata(self, device_id):
        return self.values

    def set_metadata(self, device_id, key, value):
        self.values[key] = value
        return True

    def list(self):
        return self.devices


class FakeApns:
    configured = True

    def __init__(self):
        self.sent = []

    def send_device(self, *args, **kwargs):
        self.sent.append((args, kwargs))


def test_notification_preferences_persist_and_workflow_event_is_idempotent(tmp_path):
    registry, apns = Registry(), FakeApns()
    service = NotificationService(tmp_path / 'notifications.sqlite3', registry, apns)
    try:
        prefs = service.preferences('trusted-1')
        assert prefs['events']['needs_review']['enabled'] is True
        service._on_event('workflow.approval_required', {'run_id': 'run-1'})
        service._on_event('workflow.approval_required', {'run_id': 'run-1'})
        items = service.list('trusted-1')
        assert len(items) == 1
        assert items[0]['category'] == 'needs_review'
        assert items[0]['body'] == 'A workflow is waiting for your approval.'
        assert service.mark_read('trusted-1', items[0]['id'])
        assert service.list('trusted-1')[0]['read_at']
        assert not service.mark_read('other-device', items[0]['id'])
    finally:
        service.close()


def test_quiet_hours_cross_midnight_and_timezone():
    config = {'quiet_hours': {'enabled': True, 'start': '22:00', 'end': '08:00', 'timezone': 'Asia/Kolkata'}}
    assert _inside_quiet_hours(config, datetime(2025, 1, 1, 18, 0, tzinfo=timezone.utc))
    assert not _inside_quiet_hours(config, datetime(2025, 1, 1, 5, 0, tzinfo=timezone.utc))
    assert DEFAULT_PREFERENCES['daily_summary']['time'] == '08:00'
