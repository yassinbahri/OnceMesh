# 0024 — SQLite WAL is the high-contention local index

Status: accepted

The JSON filesystem index remains the transparent correctness reference.
SQLite/WAL becomes the recommended local backend when several processes share
an adapter index.

SQLite provides crash rollback, bounded writer serialization, concurrent
readers, durable atomic row updates, integrity checks, and broad availability
without another dependency. It does not change immutable object storage or
framework adapters.

WAL `NORMAL` synchronization is the default performance profile and covers the
process-crash semantics required here. Deployments requiring the newest commit
to survive operating-system or power failure select `FULL` explicitly. Both
profiles preserve database consistency.

The publication callback runs inside a database write transaction. This keeps
the previous revision committed through publication failure but means slow
immutable stores hold the single SQLite writer slot longer. Distributed indexes,
remote object/index two-phase commit, and automatic orphan collection remain
separate concerns.
