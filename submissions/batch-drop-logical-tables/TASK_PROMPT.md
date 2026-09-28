Repo URL: https://github.com/GreptimeTeam/greptimedb
Issue URL: (none)
Commit Hash: 2b596fd52df31dcad779794877a296de7746f736
Title: Support batch DDL drop for Metric Engine logical tables
Language: Rust
Category: feature_request

Task prompt:

Metasrv accepts a batched drop-table DDL task for Metric Engine logical tables, but submitting one panics instead of dropping anything. Implement it.

A batch targets logical tables of one physical Metric table. On success every existing target is dropped as if dropped on its own: its table metadata is removed, cached metadata for it is invalidated by both table id and table name, and its logical regions are dropped on the datanodes leading the physical table's regions. The physical table, its regions and the other logical tables must stay untouched, and later single-table drops on that physical table must keep working.

Validate the whole batch before changing anything. A missing target is skipped when its task sets drop_if_exists; otherwise the batch fails with the same table-not-found error a single-table drop reports. A target that is not a logical table, or targets belonging to different physical tables, reject the batch. A rejected batch changes no table metadata and drops no region. Listing the same table more than once must not fail the batch or affect other tables.

If the procedure manager restarts while a batch is running, the recovered batch must finish dropping every target. Single-table drop behavior is unchanged.
