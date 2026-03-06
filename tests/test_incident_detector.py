from datetime import datetime, timedelta, timezone

from app.incidents.detector import SpikeDetector


def test_spike_detector_triggers_at_threshold_in_window() -> None:
    detector = SpikeDetector(window_minutes=15, threshold=5)
    now = datetime.now(timezone.utc)
    events = [now - timedelta(minutes=14), now - timedelta(minutes=10), now - timedelta(minutes=7), now - timedelta(minutes=4), now - timedelta(minutes=1)]

    assert detector.is_spike(events, now=now) is True


def test_spike_detector_does_not_trigger_when_old_events_outside_window() -> None:
    detector = SpikeDetector(window_minutes=15, threshold=5)
    now = datetime.now(timezone.utc)
    events = [now - timedelta(minutes=30), now - timedelta(minutes=14), now - timedelta(minutes=12), now - timedelta(minutes=8), now - timedelta(minutes=2)]

    assert detector.is_spike(events, now=now) is False


def test_spike_detector_handles_naive_and_aware_datetimes() -> None:
    detector = SpikeDetector(window_minutes=15, threshold=2)
    now = datetime.now(timezone.utc)
    aware_event = now - timedelta(minutes=4)
    naive_event = (now - timedelta(minutes=2)).replace(tzinfo=None)

    assert detector.is_spike([aware_event, naive_event], now=now) is True
