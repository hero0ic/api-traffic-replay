from replay_core.fingerprint import fingerprint_requests
from replay_core.models import RequestCollection, RequestSpec


def test_fingerprint_stable_for_same_requests() -> None:
    collection = RequestCollection(
        name="demo",
        requests=[RequestSpec(id="health", method="GET", path="/health")],
    )
    assert fingerprint_requests(collection) == fingerprint_requests(collection)


def test_fingerprint_changes_when_path_changes() -> None:
    left = RequestCollection(
        name="demo",
        requests=[RequestSpec(id="user", method="GET", path="/users/1")],
    )
    right = RequestCollection(
        name="demo",
        requests=[RequestSpec(id="user", method="GET", path="/users/2")],
    )
    assert fingerprint_requests(left) != fingerprint_requests(right)
