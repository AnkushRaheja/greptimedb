# Requirement / Test Matrix: Support batch DDL drop for Metric Engine logical tables

All NEW tests live in `src/common/meta/src/ddl/tests/batch_drop_logical_tables.rs`. They drive only public
surfaces: `DdlManager::submit_ddl_task` with `DdlTask::DropLogicalTables`, the `ProcedureManager` API
(`stop`, `start`, `list_procedures`, `procedure_watcher`, `procedure_state`), the metadata managers, and
two repo-precedented test doubles: a `MockDatanodeHandler` (as in `ddl/test_util/datanode_handler.rs`)
and a `CacheInvalidator` set on the public `DdlContext::cache_invalidator` field (as in the
`create_database.rs` tests). No test names or reads the solver's procedure type, state enum, data
layout, error variant, transaction shape, lock keys or dedup strategy.

Fixture: a physical Metric table whose 3 regions are led by datanodes 1, 2 and 3, and logical tables
created with the existing logical-table create helper.

## Matrix

| # | Requirement (prompt sentence) | Basis | Test | Oracle |
|---|---|---|---|---|
| R1 | A batch of logical tables of one physical table succeeds instead of panicking | PROMPT | `test_batch_drop_logical_tables` | `submit_ddl_task` returns `Ok` |
| R2 | Each target's table metadata is removed | PROMPT; REPO (single drop removes name/info/route) | all success tests | name key absent, `table_info_manager().get(id)` and `table_route_storage().get(id)` are `None` |
| R3 | Logical regions are dropped on the datanodes leading the physical regions | PROMPT; REPO (single drop sends `Drop(RegionId(logical_id, n))` to leaders) | all success tests | recorded `(datanode, region)` drop set is a superset of `{(n, RegionId(target, n))}`; `Drop` and batched `Drops` bodies both accepted |
| R4 | Physical table, its regions and other logical tables stay untouched | PROMPT | all success tests | raw name/info/route values of physical table and survivor are byte-identical; no drop or close request addresses any region of a non-target table (including physical region ids) |
| R5 | Later single-table drops on that physical table keep working | PROMPT | `test_batch_drop_logical_tables`, `..._with_duplicate_targets`, `..._recovers_after_restart` | a subsequent `DdlTask::DropTable` of the survivor succeeds and drops only its regions |
| R6 | Cached metadata invalidated by table id and table name for every removed table | PROMPT; REPO (single drop invalidates `TableId` and `TableName`) | `..._invalidates_caches`, `..._skips_absent_table_if_exists`, `..._with_duplicate_targets`, `..._recovers_after_restart` | recorded idents contain `CacheIdent::TableId(id)` and `CacheIdent::TableName(name)` for each removed target; extra idents allowed |
| R7 | Missing target skipped with `drop_if_exists` | PROMPT | `..._skips_absent_table_if_exists` | batch Ok; others dropped; all-absent batch is a no-op (no region request, survivors unchanged) |
| R8 | Missing target without `drop_if_exists` fails the batch with the same table-not-found error as a single-table drop | PROMPT; REPO | `..._rejects_absent_table` | the single-table drop of the absent table and the batch both report `StatusCode::TableNotFound`; missing target placed first and in the middle |
| R9 | Non-logical target (physical Metric table, ordinary table) rejects the batch | PROMPT | `..._rejects_non_logical_tables` | `is_err()` only (no error code or text asserted); four orderings |
| R10 | Targets of different physical tables reject the batch | PROMPT | `..._rejects_different_physical_tables` | `is_err()` only; two orderings |
| R11 | A rejected batch changes no table metadata and drops no region | PROMPT | R8/R9/R10 tests | raw name/info/route values of every involved table byte-identical before/after; no drop request recorded; a later valid batch still succeeds |
| R12 | A duplicated target must not fail the batch or affect other tables | PROMPT | `..._with_duplicate_targets` | Ok; targets dropped; survivor/physical unchanged; no request to non-target regions. Number of drop requests per logical region is **not** asserted |
| R13 | If metasrv restarts while a batch is running, the recovered batch finishes dropping every target | PROMPT | `..._recovers_after_restart` | first destructive region request is held until the manager is stopped; a new manager on the same persisted state (`register_loaders`, `start`) is awaited for every recovered procedure; all end `Done`; every target dropped (metadata + region drops after restart); survivor/physical unchanged; later single drop works |
| R14 | Single-table drop behavior is unchanged | PROMPT; REPO | BASE (all 602 existing common-meta unit tests, including `ddl::tests::drop_table`) | existing assertions |

## Fairness notes

- **No exact counts.** Region-drop assertions use set containment for targets and a prohibition for non-targets. Re-sending a drop (for example after recovery) or batching drops per datanode are both accepted.
- **No error text, and a status code only where the prompt defines one.** Only R8 checks a code. Its expected value is whatever a single-table drop of the same missing table reports, and the test measures that first.
- **Atomicity is checked on metadata only.** Rejection atomicity is asserted through the raw metadata values of the involved tables and the absence of drop requests. The test does not assert that the metadata KV store as a whole is unchanged, nor any transaction structure.
- **Recovery is implementation-agnostic.**
  - Synchronization is a channel, and there is no sleep.
  - Timeouts (60 s) only detect stalls; they never decide pass or fail.
  - The test awaits every procedure the manager recovers, so a design that uses sub-procedures also passes.
- **Duplicates.** Only the externally relevant property is asserted: no failure, no effect on other tables or the physical regions, and consistent metadata.
- **Restart model.** The prompt says metasrv restarts. The test models that by stopping the procedure manager and starting a new one over the same persisted procedure state and metadata store, which is the durable state a restarted metasrv recovers from.

## Mutation coverage

See `LOCAL_VALIDATION_REPORT.md` for the executed mutant results.
