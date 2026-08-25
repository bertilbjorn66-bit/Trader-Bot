import pytest

from research.event_calibration_audit import (
    EventRelease,
    fit_logistic_calibrator,
    validate_calibration,
)


def test_event_release_rejects_future_knowledge() -> None:
    event = EventRelease('x', 'CPI', release_at=100, known_at=101, revision=0)
    with pytest.raises(ValueError):
        event.validate()


def test_event_release_accepts_revisions() -> None:
    event = EventRelease('x', 'CPI', release_at=100, known_at=95, revision=2)
    event.validate()


def test_calibrator_is_deterministic_and_validates_on_separate_data() -> None:
    scores = [0.1, 0.2, 0.3, 0.4, 0.5] * 8
    outcomes = [0, 0, 0, 1, 1] * 8
    fit = fit_logistic_calibrator(scores, outcomes)
    validation = validate_calibration(fit, scores, outcomes)
    assert fit.model.training_observations == 40
    assert validation.training_observations == 40
    assert validation.validation_observations == 40
    assert validation.information_leakage is False
    assert 0 <= validation.validation.brier_score <= 1
    assert validation.validation.expected_calibration_error >= 0
