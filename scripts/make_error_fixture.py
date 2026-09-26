from pathlib import Path

from cuauto.storage import ArtifactStore

evidence = Path("evidence")
store = ArtifactStore(evidence)
artifact = store.load("offline-capability.json")
data = artifact.model_dump(mode="json")
data["capability_id"] = "injected_application_error"
data["steps"][0]["destination"] = "http://127.0.0.1:8765/error"
store.save("error-capability.json", type(artifact).model_validate(data))
print("saved evidence/error-capability.json")
