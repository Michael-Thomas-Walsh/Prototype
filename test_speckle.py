
from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account

PROJECT_ID = "0f3cb45af1"
MODEL_ID = "ee03c40d73"

client = SpeckleClient(host="app.speckle.systems")

account = get_default_account()
if account is None:
    raise RuntimeError(
        "No Speckle account found. Sign in using Speckle Manager."
    )

client.authenticate_with_account(account)

model = client.model.get_with_versions(
    MODEL_ID,
    PROJECT_ID,
    versions_limit=1
)

print("Model:", model.name)

versions = model.versions.items
if not versions:
    raise RuntimeError("No published model versions found.")

latest = versions[0]

print("Latest version:", latest.id)
print("Referenced object:", latest.referenced_object)