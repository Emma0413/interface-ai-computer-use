import pytest
from conftest import FakeSurface


def test_success_and_typed_output(runtime, artifact):
    surface = FakeSurface()
    result = runtime(surface).run(artifact, {"member_id": "M1001"})
    assert result.kind == "success" and result.outputs == {"balance": "1245.67"}


def test_business_outcome(runtime, artifact):
    result = runtime(FakeSurface()).run(artifact, {"member_id": "M9999"})
    assert result.kind == "business_outcome" and result.outcome == "member_not_found"


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        ("ambiguous", "ambiguous_control"),
        ("missing", "missing_control"),
        ("bad_output", "input_or_output_validation"),
    ],
)
def test_surface_failures(runtime, artifact, failure, category):
    result = runtime(FakeSurface(failure=failure)).run(artifact, {"member_id": "M1001"})
    assert result.kind == "failure" and result.error.category == category


def test_bounded_transient_retry(runtime, artifact):
    surface = FakeSurface(failure="timeout")
    result = runtime(surface).run(artifact, {"member_id": "M1001"})
    assert result.kind == "success" and surface.failures == 1


@pytest.mark.parametrize("value", ["", "bad", "M1234567890123", 123])
def test_input_validation(runtime, artifact, value):
    result = runtime(FakeSurface()).run(artifact, {"member_id": value})
    assert result.kind == "failure" and result.error.category == "input_or_output_validation"


def test_checkpoint_failure(runtime, artifact):
    data = artifact.model_dump(mode="json")
    data["checkpoint"]["value"] = "Never there"
    result = runtime(FakeSurface()).run(type(artifact).model_validate(data), {"member_id": "M1001"})
    assert result.kind == "failure" and result.error.category == "checkpoint_mismatch"


def test_no_model_surface(runtime, artifact):
    surface = FakeSurface()
    runtime(surface).run(artifact, {"member_id": "M1001"})
    assert surface.calls == ["navigate", "fill", "click", "click", "extract"]
