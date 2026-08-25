from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from oncemesh import FilesystemStore, InMemoryMetrics, run_shadow
from oncemesh.adapters import build_html_to_markdown_action, html_to_markdown_artifacts


html = b"<h1>OnceMesh</h1><p>Compute once. Reuse safely.</p>"
action = build_html_to_markdown_action(html)
now = datetime.now(timezone.utc)

with TemporaryDirectory() as directory:
    store = FilesystemStore(directory, name="organization")
    metrics = InMemoryMetrics()

    for run in range(2):
        outcome = run_shadow(
            action,
            [store],
            lambda: html_to_markdown_artifacts(html),
            metrics,
            publish_to=store,
            producer="example:local",
            fresh_until=now + timedelta(hours=1),
            now=now,
        )
        print(f"run={run + 1} candidate={outcome.lookup.hit} match={outcome.artifact_match}")

    print(metrics.summary())
