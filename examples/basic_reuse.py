from datetime import datetime, timedelta, timezone

from oncemesh import MemoryStore, Policy, publish_result, reuse


action = {
    "spec_version": "oncemesh.action/v0",
    "operation": {"name": "document.parse", "version": "1"},
    "inputs": {
        "content": {
            "digest": "sha256:" + ("a" * 64),
            "media_type": "text/html",
        }
    },
    "executor": {"name": "example-parser", "version": "2.1.0", "config": {}},
    "output_schema": "oncemesh.example/markdown-v1",
    "vary": {},
}

now = datetime.now(timezone.utc)
organization = MemoryStore("organization")
publish_result(
    organization,
    action,
    {"document": (b"# Parsed document\n", "text/markdown")},
    producer="team-a",
    produced_at=now,
    fresh_until=now + timedelta(hours=1),
)

outcome = reuse(
    action,
    [organization],
    Policy(now=now, trusted_producers=frozenset({"team-a"})),
)

assert outcome.hit
print(outcome.artifacts["document"].decode())
