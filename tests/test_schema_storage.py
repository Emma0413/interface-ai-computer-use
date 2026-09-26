import pytest
from pydantic import ValidationError

from cuauto.models import CapabilityArtifact
from cuauto.redaction import contains_secret, redact
from cuauto.storage import ArtifactError, ArtifactStore, atomic_write_text


def test_round_trip(tmp_path, artifact):
    store = ArtifactStore(tmp_path)
    store.save("valid.json", artifact)
    assert store.load("valid.json") == artifact


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(schema_version="2.0.0"),
        lambda d: d.update(revision="one"),
        lambda d: d["steps"].append(d["steps"][0]),
        lambda d: d["steps"][1].update(value={"param": "absent"}),
        lambda d: d["steps"][1].update(action="shell"),
        lambda d: d["steps"][1].update(retry={"max_attempts": 99}),
    ],
)
def test_invalid_artifacts(artifact, change):
    data = artifact.model_dump(mode="json")
    change(data)
    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(data)


def test_unsafe_path(tmp_path):
    with pytest.raises(ArtifactError):
        ArtifactStore(tmp_path).load("../x.json")


def test_corrupt(tmp_path):
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(ArtifactError):
        ArtifactStore(tmp_path).load("bad.json")


def test_redaction_recursive_and_secret_detection():
    value = {
        "nested": [{"authorization": "Bearer abc.123"}],
        "email": "a@example.com",
        "ssn": "123-45-6789",
    }
    clean = redact(value)
    assert clean["nested"][0]["authorization"] == "[REDACTED]"
    assert "example" not in clean["email"] and "123-45" not in clean["ssn"]
    assert contains_secret("password=bad")


def test_coordinates_must_be_fragile(artifact):
    data = artifact.model_dump(mode="json")
    data["steps"][1]["locators"] = [{"strategy": "coordinates", "value": "1,2"}]
    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(data)


def test_atomic_result_write_replaces_file_and_rejects_symlink(tmp_path):
    result = tmp_path / "result.json"
    result.write_text("old", encoding="utf-8")
    atomic_write_text(result, '{"kind":"success"}')
    assert result.read_text(encoding="utf-8") == '{"kind":"success"}'
    assert not list(tmp_path.glob("*.tmp"))

    target = tmp_path / "target.json"
    target.write_text("protected", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ArtifactError, match="symlink"):
        atomic_write_text(link, "overwrite")
    assert target.read_text(encoding="utf-8") == "protected"
