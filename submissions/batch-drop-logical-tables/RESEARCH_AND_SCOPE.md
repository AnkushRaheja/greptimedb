# Research and Scope: Support batch DDL drop for Metric Engine logical tables

- Repo: https://github.com/GreptimeTeam/greptimedb
- Commit: `2b596fd52df31dcad779794877a296de7746f736`
- Category: `feature_request`
- Language: Rust

## Gap

[SOURCE] `DdlTask::DropLogicalTables(Vec<DropTableTask>)` (`src/common/meta/src/rpc/ddl.rs`) is decoded from the public metasrv DDL request (`DdlTaskRequest` carrying `DropTableTasks`). `DdlManager::submit_ddl_task` dispatches it to `DropLogicalTables(_) => todo!()` (`src/common/meta/src/ddl_manager.rs:1004`).

[EXECUTED] A disposable reproducer at the pinned commit showed three things:
- A `DropLogicalTables([a, b])` task survives the proto round trip.
- A single `DropTable` of a sibling logical table succeeds.
- The batch panics with "not yet implemented", leaving every table untouched and sending no region request.

[SOURCE] Nothing in-tree emits the variant. The frontend's SQL `DROP TABLE a, b` (#4085) runs one single-table drop procedure per table, so a later failure leaves earlier tables dropped.

## How single logical-table drop works (the parity reference)

`DropTableProcedure` runs these steps:
1. **Prepare.** Checks existence by name, honouring `drop_if_exists`, and reads the physical route.
2. **DeleteMetadata.** Registers the *physical* region ids as operating, then tombstones name, info, route and repart keys.
3. **InvalidateTableCache.** Invalidates `TableName` and `TableId`.
4. **DatanodeDropRegions.** Sends `Drop(RegionId(logical_id, n))` to leaders and `Close` to followers; `RegionNotFound` is tolerated.
5. **DeleteTombstone.** Removes the tombstones permanently.

Logical tables never roll back, and soft drop falls back to hard drop.

## Frozen scope (approved, with the user's adjustments)

**In scope** (every item is stated in the task prompt):
1. A batch of logical tables of **one** physical Metric table drops every existing target. Each target's metadata is removed and its cache is invalidated by id and by name. Its logical regions are dropped on the datanodes leading the physical regions.
2. The physical table, its regions and the other logical tables stay untouched, and later single-table drops keep working.
3. Whole-batch validation happens before any change:
   - a missing target is skipped with `drop_if_exists`, otherwise the batch fails as table-not-found (same error as a single-table drop);
   - a non-logical target is rejected;
   - targets on different physical tables are rejected (mandatory: no splitting);
   - a rejected batch changes no metadata and drops no region.
4. A duplicated target must not fail the batch or affect other tables. No particular deduplication strategy is required.
5. After a procedure-manager restart mid-batch, the recovered batch finishes every target.
6. Single-table drop is unchanged.

**Out of scope:** frontend/SQL routing; soft-drop/undrop/purge; dropping physical tables through the batch; splitting multi-physical batches; physical-column cleanup; atomicity against KV storage faults; a name whose current id differs from the task's `table_id`; events and metrics; concurrency with other DDL beyond normal procedure locking; transient-retry and region-not-found semantics beyond recovery.

**User adjustments applied**
1. The title was narrowed.
2. Tests check observable atomicity only.
3. The same-physical-table rule is mandatory, with rejection instead of splitting.
4. Duplicates: only the externally relevant property is required.

The recovery requirement is kept, and the #4085 distinction is recorded in the audit.

## Reference solution summary

`solution.patch` changes 6 files: +599 / -1 lines, about 450 effective LOC.

**New `ddl/drop_logical_tables.rs`: `DropLogicalTablesProcedure`**
- States: Prepare, DeleteMetadata, InvalidateTableCache, DatanodeDropRegions, DeleteTombstone.
- Prepare validates everything before any mutation:
  - resolves names in one batch read;
  - applies the missing-target and `drop_if_exists` rules;
  - dedups by table id;
  - requires logical routes that all share one physical table;
  - checks that this physical table is the one locked at submission.
- The physical regions are registered as operating **once** per batch, and re-registered in `recover()`.
- Metadata is tombstoned and later deleted with batch helpers.
- Region drops reuse `DropTableExecutor::on_drop_regions` per target, run concurrently.
- Each step persists its state. The procedure has no rollback, matching single logical drop.
- Locks:
  - catalog/schema read;
  - name lock and write lock per target;
  - a read lock on the physical table, skipped when the physical table itself is named, to avoid a shared-plus-exclusive self-deadlock before validation rejects the batch.

**`ddl_manager.rs`**
- A dispatch arm and handler, which reject an empty batch with `EmptyDdlTasks`.
- `submit_drop_logical_table_tasks`, which resolves the lock set from the first existing target.
- Loader registration, which recovery needs.

**`key.rs`**
- `delete_logical_tables_metadata` and `delete_logical_tables_metadata_tombstone`: one tombstone call per batch, chunked by the backend's transaction limit.

**`error.rs`, `metrics.rs`, `ddl.rs`**
- A new `DropLogicalTablesInvalidArguments` error (`InvalidArguments`), a `greptime_meta_procedure_drop_tables` histogram, and the module declaration.

## Architectural traps (natural difficulty)

- Single logical drop registers the shared physical region ids. Doing that per target inside one batch hits `RegionOperatingRace` on the second target (mutant m06).
- A handler that loops single drop procedures passes happy paths but loses the rest of the batch on restart (m07).
- Recovery needs per-step persistence (m08) and loader registration (m04).
