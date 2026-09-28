# Candidate 1: Support batch DDL drop for Metric Engine logical tables (research phase)

Evidence labels: [SOURCE] repo source, [EXECUTED] command/test actually run, [UPSTREAM] GitHub/upstream-git evidence, [PLATFORM] Olympus evidence, [INFERENCE] reasoning not directly proven.

## 1. Base verification (Stage A)

- [EXECUTED] `git rev-parse HEAD` = `2b596fd52df31dcad779794877a296de7746f736` ("ci: deploy MinIO chart with Silo images (#9362)", 2026-09-27). Worktree clean before research.
- [EXECUTED] `git ls-remote https://github.com/GreptimeTeam/greptimedb HEAD refs/heads/main` = `2b596fd52df31dcad779794877a296de7746f736` on 2026-09-28. The pin is the current upstream tip, not a historical commit.
- [EXECUTED] Clone was shallow (50 commits); unshallowed from origin (6231 commits) before any history search.

## 2. Exact source-path map

| Role | Location |
| --- | --- |
| Task variant | `src/common/meta/src/rpc/ddl.rs:93` `DdlTask::DropLogicalTables(Vec<DropTableTask>)` |
| Wire decode (proto `DropTableTasks` -> variant) | `src/common/meta/src/rpc/ddl.rs:275-283` |
| Wire encode | `src/common/meta/src/rpc/ddl.rs:396-402` |
| **Gap** | `src/common/meta/src/ddl_manager.rs:1004` `DropLogicalTables(_) => todo!(),` |
| Metasrv gRPC entry | `src/meta-srv/src/service/procedure.rs:111-160` (`ddl()` decodes `task.try_into()` then `submit_ddl_task`) |
| Single-table drop procedure | `src/common/meta/src/ddl/drop_table.rs` (states Prepare -> DeleteMetadata -> InvalidateTableCache -> DatanodeDropRegions -> DeleteTombstone) |
| Drop executor | `src/common/meta/src/ddl/drop_table/executor.rs` (`on_prepare`, `on_delete_metadata`, `invalidate_table_cache`, `on_drop_regions`, `on_delete_metadata_tombstone`) |
| Metadata fill for logical tables | `src/common/meta/src/ddl/drop_table/metadata.rs` (logical: physical route reused, no rollback, soft-drop forced off) |
| Metadata keys removed | `src/common/meta/src/key.rs:990-1117` (`table_metadata_keys`, tombstone create/delete) |
| Batch precedent: create | `src/common/meta/src/ddl/create_logical_tables*.rs`, handler `ddl_manager.rs:1249` |
| Batch precedent: alter | `src/common/meta/src/ddl/alter_logical_tables*.rs` (validator: same physical id, locks on physical + every logical id), handler `ddl_manager.rs:1518` |
| Loader registration | `ddl_manager.rs:322-374` |
| Region keeper | `src/common/meta/src/region_keeper.rs:64` (`register_with_role` returns `None` if the region is already registered) |
| Datanode batched drop | `src/datanode/src/region_server.rs:919-923` (`Body::Drops` -> batch DDL), `src/metric-engine/src/engine.rs:198` (loops single logical drops) |
| Frontend multi-table DROP | `src/operator/src/statement/ddl.rs:1536-1586` (`drop_tables`: per-table `DropTable` tasks, never emits the batch variant) |
| Test harness | `src/common/meta/src/test_util.rs` (`new_ddl_context`), `src/common/meta/src/ddl/test_util.rs` (`create_physical_table`, `create_logical_table`), `ddl/test_util/datanode_handler.rs` (`DatanodeWatcher`), `ddl_manager.rs` tests (`ddl_manager_with_context`) |

## 3. Git-history search (full history, 6231 commits)

- [EXECUTED] `git log -S'DropLogicalTables'`: only `1fab7ab75` (2024-01-26, "feat: batch create ddl (#3194)"), which introduced the variant together with `DropTableTasks` and the `todo!()` arm.
- [EXECUTED] `git log -G'DropLogicalTables'` on main: #3194, #3541 (drop database), #3810 (create flow), #3900 (drop flow), #3807 (create view), #5035 (alter db ttl), #6625 (refactor: remove procedure executor), #7060 (COMMENT). Each only reflows the dispatch match; none touches the arm's body.
- [EXECUTED] `git blame -L1004` -> `19ad9a7f85` (#6625, 2025-08-01), a refactor that kept `todo!()`.
- [EXECUTED] `git log -S` for `drop_logical_tables`, `DropLogicalTablesProcedure`: no hits on main. Commit-message grep for "drop logical tables", "batch drop", "DropTableTasks", "drop_table_tasks": no hits.

## 4. All-state upstream audit

Upstream GitHub API tools were not attachable in this session (the fork has the same repo name). The audit therefore used anonymous git plus the public GitHub REST/web search.

- [EXECUTED][UPSTREAM] Fetched **all 7050 upstream PR heads** (`refs/pull/*/head`: open, closed, merged, draft) and all 237 upstream branches into `refs/upstream-pr/*` and `refs/upstream-heads/*`.
- [EXECUTED][UPSTREAM] `git log -S/-G 'DropLogicalTables'` over every PR/branch ref excluding main: only merge-base noise (pre-squash commits of #3194/#3541/#3807/#3810/#3900/#5035/#6625), a gh-pages rustdoc deploy, a backport-review doc diff (`5b8c9c07eb`, contains the `todo!()` line verbatim), a rebased fork branch (`c4d55cbdea`), and a WIP COMMENT branch (`8557dcce94`). None implements the arm.
- [EXECUTED][UPSTREAM] **Decisive blob check.** Across 5623 ref tips containing `src/common/meta/src/ddl_manager.rs` there are 117 distinct blobs. 87 mention `DropLogicalTables`, and **all 87 still contain `DropLogicalTables(_) => todo!()`**. No PR head, open or closed, ever replaced the arm.
- [EXECUTED][UPSTREAM] `-G 'drop_logical_tables|DropLogicalTablesProcedure|DropLogicalTablesData|drop_logical_table'` over all refs: only `test_undrop_logical_table_skips_datanode_open` (soft-drop series), which is unrelated.
- [EXECUTED][UPSTREAM] No ref anywhere constructs `DdlTask::DropLogicalTables` outside the proto round-trip code.
- [UPSTREAM] GitHub search API (`repo:GreptimeTeam/greptimedb`):
  - `DropLogicalTables`: 0 results. `DropTableTasks`: 0. `"drop logical tables"`: 9 results, all soft-drop/lifecycle PRs (#8554, #8458, #8061, #8627), #7691 (unmerged node-manager refactor; its ref has the `todo!()` unchanged), #5561, #3615, #3692, #4231. None implements batch drop.
  - `"drop multiple tables"`: #4020 (issue) and #4085 (merged 2024-06-04). #4085 added SQL `DROP TABLE a, b` as a **frontend loop of single `DropTable` tasks** (`98c19ed0fa`: operator/sql/sqlness only, no common-meta change). Its review thread never discussed the batch task, atomicity, or metric logical tables.
  - **#4085 is related but not equivalent.** It added generic SQL multiple-table `DROP TABLE` by invoking ordinary single-table drop operations one after another, and it explicitly left the gRPC path unsupported (its description says the implementation "supports SQL requests but is not ready for gRPC"). This task targets the pre-existing `DropTableTasks` / `DdlTask::DropLogicalTables` Metric Engine logical-table DDL path, which still panics at the pinned commit and needs batch-safe logical-table semantics (validation of the whole batch, one shared physical table, and recovery of the whole batch). The two do not overlap.
  - #3194 (introduced the variant): its review thread has no discussion of batch drop, no plan, and no decision not to implement.
  - Discussions search "drop logical tables": nothing relevant.
- [UPSTREAM] Soft-drop PRs #8061/#8458/#8554 explicitly keep metric logical **soft-drop/undrop/purge** unsupported (rejected seed R4). This candidate is **hard** drop, which single-table drop already performs for logical tables (soft-drop falls back to hard drop, `drop_table/metadata.rs:37-42`). No maintainer decision against batch hard drop was found.
- [SOURCE] `docs/style-guide.md:21` says to use `unimplemented!()` "for things that aren't likely to be implemented". The arm uses `todo!()`, which signals the maintainers' intent to implement it.
- [PLATFORM] Olympus duplicate/similarity check: **UNVERIFIED** (not accessible from here).

## 5. Current-HEAD proof and reproduction

Disposable reproducer (not committed): `scratchpad/repro_drop_logical_tables.patch`, a test appended to the `ddl_manager.rs` test module, applied only while running and reverted immediately afterwards. Setup: `new_ddl_context` with a `DatanodeWatcher`, `create_physical_table("phy")`, three logical tables `a`, `b`, `c` via the existing logical-create helper, and `ddl_manager_with_context`.

- [EXECUTED] **Wire path.** A `SubmitDdlTaskRequest` with `DdlTask::DropLogicalTables([a, b])` encodes to a `DdlTaskRequest` whose `task` field decodes (`DdlTask::try_from`, the same call metasrv's `ddl` handler makes) back into `DropLogicalTables` with 2 tasks. The assertion held.
- [EXECUTED] **Baseline.** Submitting `DdlTask::DropTable(c)` for logical table `c` through the same manager succeeds (`unwrap()` passed).
- [EXECUTED] **Gap.** Submitting the decoded `DropLogicalTables([a, b])` through `DdlManager::submit_ddl_task`, inside `tokio::spawn`, gives `JoinError { is_panic: true }`, message `"not yet implemented"`. Afterwards `a`, `b` and `phy` still exist and no region request was sent.
- Command: `CARGO_TARGET_DIR=/home/user/greptimedb-target cargo test -p common-meta --lib repro_drop_logical_tables_gap -- --nocapture` gave `test ... ok` (the test observes the panic rather than asserting behavior) and `1 passed; 602 filtered out`.
- [SOURCE] In production the panic unwinds the gRPC handler task (release profile has no `panic = "abort"`), so the client gets a transport-level failure instead of a DDL response. Nothing in-tree emits this variant; the path is reachable only via metasrv's public `ddl` RPC (`DdlTaskRequest.drop_table_tasks`).

## 6. Comparison with single logical-table drop

[SOURCE] Single logical-table drop (`DropTableProcedure`) does the following:
1. **Prepare.** Checks existence by name; a missing table is `Done` with `drop_if_exists`, else `TableNotFound`. Reads the physical route via `get_physical_table_route(logical_id)`. Rollback is disabled for logical tables, and soft drop falls back to hard drop.
2. **DeleteMetadata.** Registers the **physical** region ids as operating in `MemoryRegionKeeper`, then tombstones the logical table's name, info, route and repart keys in one KV transaction. The physical table's info and route are not modified, and physical columns are left in place (#5561).
3. **InvalidateTableCache.** Invalidates `CacheIdent::TableName` and `CacheIdent::TableId` for the table.
4. **DatanodeDropRegions.** Sends `Drop(RegionId(logical_id, n))` to each physical region's leader peer and `Close` to followers; `RegionNotFound` is tolerated. Removes route regions from the leader registry and deregisters failure detectors.
5. **DeleteTombstone.** Deletes the tombstoned keys permanently and releases the keeper guards.

[EXECUTED] Baseline run: the drop of `c` succeeded through `submit_ddl_task`. A second run to print the baseline's exact region requests was cancelled to relieve shared-build contention; the request shape above is from source and will be asserted by the NEW tests.

Batch-specific consequences:
- [SOURCE] `register_with_role` returns `None` for an already-registered `(datanode, region)`, producing `RegionOperatingRace` (`StatusCode::Unexpected`, not retryable). Two targets in one batch share the same physical region ids.
- [SOURCE] The frontend `DROP TABLE a, b` (#4085) validates existence up front but then runs independent procedures, so a later failure leaves earlier tables dropped. The batch task is the only atomic-validation, single-procedure path.

## 7. Proposed frozen scope

**Entry point.** `DdlManager::submit_ddl_task` with `DdlTask::DropLogicalTables`, which is what metasrv's `ddl` gRPC receives for a `DdlTaskRequest` carrying `DropTableTasks`. No SQL, parser, or frontend change.

**In scope**
1. The batch no longer panics. An empty batch is rejected (precedent: `EmptyDdlTasks` for batch create/alter).
2. **Validate the whole batch before any destructive effect** (no metadata change, no cache invalidation, no region request, no region left registered as operating):
   - A missing target is skipped when its task sets `drop_if_exists`. Otherwise the whole batch fails with table-not-found (single-drop parity, `StatusCode::TableNotFound`).
   - Every present target must be a metric logical table. A physical table or an ordinary table in the batch rejects the batch.
   - All present targets must belong to the same physical table. Otherwise the batch is rejected (precedent: the alter-logical-tables validator).
   - A target listed more than once is dropped once and does not fail the batch.
3. **Effects on success, same as dropping each target individually:**
   - The target's table name, info, and route are gone, and the name can be reused (tombstones cleaned up).
   - Cached metadata is invalidated for every dropped table, by id and by name.
   - Each target's logical regions (`RegionId(logical_id, n)` for every physical region `n`) receive a drop on the region's leader datanode. A single or batched region drop request is acceptable.
   - The physical table's metadata and regions are untouched, and so are surviving logical tables.
   - No region remains registered as operating once the operation finishes.
4. **Retry / recovery**
   - A transient (retryable) datanode failure while dropping regions is retried and the batch completes. A datanode reporting region-not-found counts as already dropped (single-drop parity).
   - If metasrv's procedure manager restarts while the batch is in flight, the recovered operation completes the whole batch.
   - Resubmitting a completed batch behaves like re-dropping absent tables: success with `drop_if_exists`, table-not-found without it.
5. Existing single-table drop (logical, physical, ordinary) behavior is unchanged.

**Out of scope (hidden tests must not require):** frontend/SQL routing of `DROP TABLE a, b`; soft-drop/undrop/purge of logical tables (hard drop only, as today); dropping physical tables through the batch; splitting a multi-physical batch; removing columns from the physical table; atomicity against KV storage faults inside the metadata transaction; a name whose current table id differs from the task's `table_id`; events/metrics; concurrency with other DDL beyond normal procedure locking.

**Category:** `feature_request` (implement an existing but unimplemented DDL task).

**Draft task prompt (~170 words, to be frozen only after approval):**

> Metasrv accepts batched drop-table tasks for metric logical tables, but submitting one panics instead of dropping anything. Implement that batch drop.
>
> A batch must have the same end result as dropping each target individually: the tables disappear and their names can be reused, cached metadata for each dropped table is invalidated, each target's logical regions are dropped on the datanodes, and the shared physical table, its regions, and other logical tables are left untouched. No region should remain registered as operating afterwards.
>
> Validate the whole batch before changing anything. A missing target is skipped when its task allows `drop_if_exists` and otherwise fails the batch as table-not-found. A target that is not a logical table, targets on different physical tables, or an empty batch must be rejected. A table listed twice is dropped once. A rejected batch must leave every table, region, and cache untouched.
>
> Transient datanode errors must be retried, and if metasrv restarts mid-operation, recovery must finish the whole batch. Single-table drop and SQL behavior are unchanged.

## 8. Estimated production files / effective LOC

[INFERENCE] Reference solution, about 450-650 effective LOC across 4-6 files:
- new `src/common/meta/src/ddl/drop_logical_tables.rs` (+ optional `validator`/`metadata` submodules): procedure, serializable data, states, lock keys (catalog/schema read, `TableNameLock` + `TableLock::Write` per target, and a lock on the physical table), `recover()`, about 350-450 LOC;
- `ddl_manager.rs`: dispatch arm, `handle_drop_logical_table_tasks`, `submit_drop_logical_table_tasks`, loader registration, about 60-80 LOC;
- `ddl.rs` module declaration; `error.rs` (invalid-arguments error, e.g. `DropLogicalTablesInvalidArguments`); `metrics.rs` label, about 20-30 LOC;
- optionally `key.rs`: multi-table tombstone create/delete in one transaction, about 50-80 LOC.

Architectural traps that give natural depth (no invented ambiguity):
- [SOURCE] Single logical drop registers the **physical** region ids in `MemoryRegionKeeper`. Reusing that per target inside one procedure collides on the second target (`RegionOperatingRace`, non-retryable `Unexpected`).
- [SOURCE] A handler that loops single `DropTable` procedures passes the happy path but loses the unsubmitted remainder on a metasrv restart. The recovery requirement catches this through observable state.
- Procedure persistence plus loader registration by `TYPE_NAME` are required for recovery.

## 9. Test architecture

All NEW tests drive the public `DdlManager::submit_ddl_task` (and the public `ProcedureManager` API for restart). They never name the solver's procedure type, state enum, or data struct.

**NEW** (new file `src/common/meta/src/ddl/tests/drop_logical_tables.rs` plus a `mod` line in `ddl/tests.rs`; the harness builds its own `LocalManager` + `DdlManager` and a no-op repartition factory):

| # | Requirement | Basis | Oracle |
| --- | --- | --- | --- |
| 1 | batch of 2 over a 3-region/2-peer physical table succeeds | prompt | names/info/route absent for a,b; physical + c intact |
| 2 | every logical region dropped exactly once; physical and c regions not addressed | prompt + repo (single drop) | set of region ids from `Drop` and `Drops` bodies |
| 3 | cache invalidated by id and name for each target | prompt + repo | recording `CacheInvalidator` (pub field; precedent in `create_database.rs` tests) |
| 4 | names reusable | prompt | recreate `a` via existing logical-create helper |
| 5 | region keeper empty after success and after rejection | prompt + repo (existing drop tests assert it) | `memory_region_keeper.len() == 0` |
| 6 | duplicate target dropped once | prompt | each region id addressed once; success |
| 7 | missing member with `drop_if_exists` | prompt | others dropped, success |
| 8 | missing member without it | prompt + repo | `StatusCode::TableNotFound`; KV dump unchanged; no region requests |
| 9 | mixed physical parents rejected atomically | prompt | `is_err`; KV dump unchanged; no requests; no invalidation |
| 10 | physical-table / ordinary-table target rejected atomically | prompt | same as 9 |
| 11 | empty batch rejected | prompt | `is_err` |
| 12 | transient retryable datanode error retried | prompt | first drop returns retryable error, final state complete |
| 13 | region-not-found tolerated | prompt + repo | success, metadata gone |
| 14 | restart recovery completes whole batch | prompt | gate blocks first region drop; `stop()`; new manager on same state store + `register_loaders`; `start()`; await recovered ids from `list_procedures`/`procedure_watcher`; assert full completion |
| 15 | resubmit after success | prompt + repo | `drop_if_exists` true -> Ok, no requests; false -> TableNotFound |

Synchronization is by channels and gates only. Timeouts serve only as stall detectors.

**BASE:** existing `common-meta` suites on the touched production paths: `ddl::tests::drop_table`, `ddl::tests::create_logical_tables`, `ddl::tests::alter_logical_tables`, `ddl_manager::tests`, `key::` tombstone/metadata tests, `cache_invalidator`/`cache::registry` tests.

**Mutation coverage plan:** happy-path-only (killed by 8-11, 14); mutate-before-validate (8-10 KV-unchanged); only-first-target (1-2); per-target keeper registration (1, as `RegionOperatingRace`); handler looping single procedures (14); no loader registration (14); no dedup (6); stale cache (3); tombstone not cleaned (4); physical regions dropped (2).

## 10. Contamination verdict

**ORIGINALITY PASS** (Olympus duplicate check [PLATFORM] UNVERIFIED).
- No upstream PR (open, closed, merged, draft; 7050 heads), branch (237), issue, or discussion implements or rejects batch hard drop of logical tables. All 87 upstream `ddl_manager.rs` variants that mention the task keep `todo!()`.
- It is not an old-commit resurrection: the pin is the current upstream tip.
- No overlap with the sealed repartition-staging challenge or the append-mode delete challenge.
- The adjacent soft-drop decisions (#8061/#8458/#8554) cover soft-drop/undrop/purge only and are out of scope here.

**Local verdict: PROCEED to reference-solution and test-patch work after user approval.**

Residual risks:
1. Reachability is API-level only (metasrv `ddl` RPC); no SQL surface triggers it. The prompt should therefore frame it as the metasrv DDL API.
2. The duplicate-target and error-code choices are contract decisions; they are stated explicitly in the prompt to keep them fair.
3. Test runtime: the restart-recovery test needs a second `LocalManager` over the same state store; it is deterministic (gate + channel) but must be run 20x for flakiness.
4. The platform duplicate check is pending.
