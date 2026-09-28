# Candidate 4: Batching-flow dirty windows when the time index is defaulted

Research-phase report (handoff sections 21/23). No reference solution, test.patch, solution.patch or Dockerfile was written.

- Worktree: `/home/user/greptimedb/.claude/worktrees/agent-a2a8a1374cdb99a04`
- HEAD: `2b596fd52df31dcad779794877a296de7746f736` ("ci: deploy MinIO chart with Silo images (#9362)"), which equals `origin/main`. [EXECUTED]
- The worktree was clean before the disposable reproduction and was restored afterward (see section 5).

## Verdict

**REJECT (too small, not enough long-horizon depth). Originality: CONDITIONAL PASS.**

The handoff's main risk does not disqualify the candidate. For a time index with a **constant** default, no layer fills in the timestamp before the batching-flow notification. The default SQL, gRPC-row and COPY FROM write paths reach the `handle_rows` skip-branch, so the dirty window is silently lost. This is proven from source. The executed reproduction is **pending: blocked on shared-disk capacity** (section 5). For **impure** defaults (`current_timestamp()`/`now()`), the frontend already fills in the value before mirroring, so that half of the handoff premise is already handled.

The defect is real and has no upstream implementation. It still fails the platform's long-horizon constraints (section 2.8):

- The fix is about 30 to 80 effective LOC in 1 or 2 files.
- The source TODO points solvers straight at the fix location.
- A sibling path in the repo (the table batcher) and the streaming engine both already show how to do it.

Expected rollout pass rate is well above 50%, and the successful-run median would be under 200 LOC. There is no natural broadening. Every adjacent gap found is either contaminated (#8428/#8420), a separate contract (deletes are never mirrored), or a different subsystem (partition routing, bulk-insert impure defaults). Combining any of them would be "bolting" (section 3.3).

---

## 1. Exact source-path map

### Flownode side (batching engine)

- `src/flow/src/batching_mode/time_window.rs:270` `TimeWindowExpr::handle_rows(rows_list)`. For each `api::v1::Rows` it looks up `self.column_name` in `rows.schema`. **L278** has the TODO `// TODO(discord9): handle case where time index column is not present(i.e. DEFAULT constant value)`. **L284-286**: `let Some(ts_col_index) = ... else { warn!("can't found time index column in schema: ..."); continue; };`. That Rows contributes no window and no dirty signal. When the column is present, the vector type comes from the **row's** proto column type (L288-289), not the table schema. [SOURCE]
- `src/flow/src/batching_mode/time_window.rs:431` `find_time_window_expr`. **L495-499**: `column_name` is the source table's **time-index** column (`schema.timestamp_column()`). The TWE therefore always keys on the time index. [SOURCE]
- `src/flow/src/batching_mode/engine.rs:322` `BatchingEngine::handle_inserts_inner`:
  - Groups region requests by table id.
  - Fetches `TableInfoValue` via `table_info_manager().batch_get`. The table schema, including default constraints, is already in hand here and is not used for defaults.
  - For each task whose source matches: if there is no TWE it calls `set_dirty()` (robust). Otherwise it calls `expr.handle_rows(entry)` (**L409**) and `add_lower_bounds`.
  - An empty result means nothing is marked. [SOURCE]
- `src/flow/src/batching_mode/engine.rs:185` `handle_mark_dirty_time_window`. This is the `DirtyWindowRequests` path, used by the bulk and pending-row batchers. It takes bare i64 timestamps in the table's native unit, resolved from table metadata. It is not affected by this gap. [SOURCE]
- `src/flow/src/adapter/flownode_impl.rs` `FlowDualEngine::handle_flow_inserts` (the `FlowEngine` impl) passes requests for batching sources unchanged to `batching_engine.handle_flow_inserts`, which calls `handle_inserts_inner`. `Flownode::handle_inserts` is the gRPC/standalone entry (`src/flow/src/server.rs:~100-124` converts and forwards, with no normalization). [SOURCE]
- Staleness: `src/flow/src/batching_mode/task.rs:2160-2166` returns `Ok(None)` ("no new data, hence no need to update") when the scoped filter has no dirty windows. `engine.rs:976` `flush_flow_inner` only executes the current dirty set; it does **not** mark all windows dirty (`mark_all_windows_as_dirty` has no production caller, only `task/test.rs:441`). So even `ADMIN FLUSH_FLOW` leaves the sink stale. [SOURCE]
- Contrast, the streaming engine already handles this. `src/flow/src/adapter.rs:1132` `StreamingEngine::handle_insert_request` builds a fetch order from table metadata and fills missing columns with `FetchFromRow::Default(create_default(...))` (L1156-1197). Batching has no equivalent. [SOURCE]

### Frontend/operator side (who mirrors, and what gets filled)

- `src/operator/src/statement/dml.rs:34`. `INSERT ... VALUES` with literal values (`can_extract_values()`) goes through `Inserter::handle_statement_insert`. Otherwise (`INSERT ... SELECT`, casts) it goes through the query engine. [SOURCE]
- `src/operator/src/req_convert/insert/stmt_to_region.rs:97` `StatementToRegion::prepare`. The row schema holds **only the listed columns** (`column_names`, L262). An explicit `DEFAULT` keyword is resolved in the frontend via `create_default` (L276-305). [SOURCE]
- `src/operator/src/insert.rs:653` `handle_statement_insert`, `:626` `handle_table_insert` and `:318` `handle_row_inserts` all lead, when the table batcher is off, to `do_request` (**L741**):
  - **L748** calls `fill_reqs_with_impure_default`, which adds **only** columns whose default is a `ColumnDefaultConstraint::Function`, for normal (non-instant) requests (`fill_impure_default.rs:30,41-117,119`).
  - **L777** calls `FlowMirrorTask::new(...)` and then `.detach()`, which sends the same `RegionInsertRequest` rows to every flownode peer (L1800-1905). [SOURCE]
- Datanode fill: `src/mito2/src/request.rs:286` `fill_missing_columns` / `:384` `column_default_value` fills constant defaults for omitted columns, including the time index, for Put. Impure defaults hitting the datanode are an error (`unexpected impure default value`, L413). So the stored row has the constant timestamp while the mirrored copy has no time-index column. [SOURCE]
- Sibling path that already has the right semantics: `insert.rs:463` `submit_pending_rows`:
  - L493 calls `ImpureDefaultFiller::fill_rows`.
  - **L494** calls `rows_to_record_batch`, which evaluates **all** defaults for missing columns (`row_to_batch.rs:34-41,138-145`).
  - The table batcher then extracts timestamps from the batch (`servers/src/batcher/table/flow_notifier.rs:60-77`) and sends `DirtyWindowRequests`.
  - This path is opt-in only: `BatcherOptions::default()` has `protocols: Vec::new()` and a zero flush interval (`frontend/src/service_config/pending_rows_batcher.rs:79-90`), and `table_batcher()` (insert.rs:596) requires `ctx.batching_enabled()`. [SOURCE]
- Bulk insert: `src/operator/src/bulk_insert.rs:156-158,356-410` notifies Flow via `extract_timestamps` on the raw batch (TODO at L156: impure defaults are not filled). mito's bulk path rejects a batch without the time-index column (`mito2/src/worker/handle_bulk_insert.rs:47-55`). [SOURCE]
- Constant default storage: `src/common/sql/src/default_constraint.rs:31-54`. A literal default is converted at CREATE TABLE time (with the session timezone) into a typed `ColumnDefaultConstraint::Value` of the column's data type. Existing sqlness `tests/cases/standalone/common/insert/insert_default_timezone.sql` shows that `TIMESTAMP DEFAULT '2024-01-30 00:01:01' TIME INDEX` is a supported, tested schema. [SOURCE]

## 2. Git-history search

- Blame of `time_window.rs:270-290` at HEAD: every line is from `5d688c65650` (discord9, 2025-03-31, "feat(flow): time window expr (#5785)"), then in `src/flow/src/recording_rules/time_window.rs`. Unchanged for about 18 months. [EXECUTED]
- On main, `git log -G'handle_rows|time index column is not present' origin/main -- src/flow` finds only #5785 (introduced) and #5807 (moved into batching engine). [EXECUTED]
- `git log --all -S'handle case where time index column is not present'` finds #5785, a gh-pages deploy commit, and `c4d55cbdea`. `c4d55cbdea` is a parentless fork snapshot (raphaelroshan, "fix: prevent credential leaks...") that adds the whole tree, so it is not an implementation. [EXECUTED]
- Unmerged commits across all 7287 upstream PR/branch refs (`--stdin` with `^origin/main`):
  - `-G'time index column is not present|can.t found time index column|fn handle_rows'` finds only pre-merge commits of #5785/#5807/#5903, a rebase artifact (`be0c482a37`, `7f0cdfe0dc`) and the fork snapshot. None changes the branch. [EXECUTED]
  - `-i -G'default'` on `batching_mode/{engine,time_window}.rs`: 36 commits, all unrelated (checkpoints, incremental read, execution hooks, TWE skip, units test `04935f11be`). [EXECUTED]
  - `-G'fill_reqs_with|ImpureDefaultFiller|create_default|FlowMirrorTask|pure_default|fill_default'` on operator insert/fill files: #5307 (impure fill, merged), `f6aa6adda6` (async mirror), `1f232ef3a7` (#9115 table batching), and **`a27c5acffc` = PR #8428** "fix(flow): notify flow after source writes". #8428 reorders mirroring after a successful datanode write and does not fill defaults. [EXECUTED]
  - `-G'default_values|FetchFromRow|create_default|default_constraint' -- src/flow`: streaming-only work (#5307, #5747, #8976 series). [EXECUTED]
- Blob sweep (reliable for line-replacing edits):
  - `time_window.rs` exists at 2942 of the 7287 refs, as **13 distinct blobs**. **All 13** still contain the TODO, the warn and the `continue`. [EXECUTED]
  - `engine.rs` exists at 2942 refs as 46 distinct blobs. `handle_inserts_inner` (or the #5807-era `handle_inserts`) has 5 distinct bodies. A diff against HEAD shows only task-registry, metrics and `set_dirty` refactors. **No version fills defaults or consults the time-index schema.** [EXECUTED]

## 3. Upstream PR/issue/discussion search (all states)

These searches used the GitHub public API/web, not the MCP tools. [UPSTREAM]

- `handle_rows`: 0 results.
- `flow default time index`, `flow "default value"`, `"dirty window"`, `flow "time index" missing`, `flow default timestamp batching`, `impure default`, `flow "time window" default is:pr`, `flow "DEFAULT" "time index" is:issue`: no issue or PR about defaulted time indexes in batching flows.
- Relevant neighbours inspected individually:
  - **#5307** (merged 2025-01): fills impure defaults in the frontend and in the streaming adapter. Predates batching mode, and constant defaults were left to the datanode. Added sqlness `flow_ins_default` (CURRENT_TIMESTAMP only).
  - **#5747** (merged): nullable defaults, streaming engine.
  - **#5785 / #5807 / #5903** (merged): introduced the TWE, the TODO and the batching engine. The #5785 review has no discussion of the TODO.
  - **#8544** (merged as `c8f65c7b99`): Prometheus pending-rows metric batch flush notifications. Samples always carry `greptime_timestamp`, and there is no default handling. No overlap.
  - **#8582** (merged): `time_ranges` in `DirtyWindowRequest`. No overlap.
  - **#9115 / #9186 / #9187 / #9212**, tracking issue **#9164** (open): ordinary-table batching that evaluates defaults before notifying. Opt-in, and does not touch the mirror path. It is an in-repo oracle for the expected semantics, not an implementation of this fix.
  - **#8428** (closed unmerged, stale draft) and issue **#8420** (open): "Flow mirror inserts can be detached before the source-table insert reaches a commit boundary". This contaminates the handoff's scenario 6 ("failed writes do not notify a window"), which must be excluded.
  - **#6291** "bulk support flow batch" (merged): the bulk path uses `DirtyWindowRequests`. No default handling.
- Discussions search `flow default`: none relevant.
- Release notes (v1.1.4 to v1.3.0 nightlies on the releases page): no mention of defaults with Flow dirty windows. The repo has no CHANGELOG file.
- Olympus platform-duplicate check: [PLATFORM] **UNVERIFIED** (not available to this agent).

## 4. Current-HEAD reachability per write path

"Reaches branch" means the mirrored rows arrive at `handle_rows` without the time-index column while the stored row has a (constant) default timestamp.

| Write path (default config) | Reaches skip-branch? | Evidence |
|---|---|---|
| SQL `INSERT INTO t(col, ...) VALUES ...` omitting a **constant-default** time index (MySQL, PG simple query, HTTP `/v1/sql`, gRPC SQL) | **YES** | [SOURCE] dml.rs:34 -> stmt_to_region.rs:97/262 -> insert.rs:653 -> do_request L748 (impure only) -> L777 mirror -> engine.rs:409 -> time_window.rs:284; mito fills the constant (request.rs:286). Executed reproduction pending (section 5) |
| Same, but `VALUES (..., DEFAULT)` keyword | NO (frontend fills via `create_default`) | [SOURCE] stmt_to_region.rs:276-305 |
| Same, **impure** default (`current_timestamp()`/`now()`) omitted | NO (frontend `ImpureDefaultFiller` adds ts before mirroring) | [SOURCE] fill_impure_default.rs; existing sqlness `flow_ins_default` (CURRENT_TIMESTAMP case, checked in with #5307) |
| `INSERT ... SELECT` / non-literal VALUES (query-engine DML) | NO (DataFusion insert planning projects all columns using `get_column_default`, which covers constants and now()) | [SOURCE] table.rs:109/190-220, query/src/datafusion.rs insert; the DataFusion planner internals are [INFERENCE] |
| gRPC `RowInsertRequests` / legacy column inserts omitting ts on an existing table | **YES** | [SOURCE] insert.rs:318 -> create_or_alter (no ts requirement for existing tables) -> RowToRegion -> do_request |
| `COPY FROM` a file lacking the time-index column | **YES** (source-level) | [SOURCE] copy_table_from.rs:852-873 projects only file columns -> handle_table_insert -> TableToRegion::prepare (given columns only) -> do_request |
| InfluxDB line protocol | NO (ts always written, now() if absent, renamed to the table's ts) | [SOURCE] servers/src/influxdb.rs:60,91-97; insert.rs:1439 accommodate |
| Prometheus remote write (row path and logical-table batcher, #8544) | NO (`greptime_timestamp` always present; the logical batcher also rejects tables with defaults or flows) | [SOURCE] prom_row_builder.rs; insert.rs:160-236 |
| OTLP metrics/logs/traces, OpenTSDB | NO (timestamp always emitted) | [SOURCE] otlp/metrics.rs:1006-1014; OpenTSDB [INFERENCE] |
| Log pipelines (HTTP logs/Loki/ES) | NO in normal use (the transformer always emits a time-index column) | [SOURCE] pipeline/.../greptime.rs:151,661,874 |
| Bulk insert (Arrow Flight DoPut) | NO (mito rejects a batch without the ts column) | [SOURCE] handle_bulk_insert.rs:47-55 |
| Ordinary-table pending-rows batcher (opt-in `pending_rows_batcher.protocols`) | NO, and **correct** (defaults evaluated, then `DirtyWindowRequests`) | [SOURCE] insert.rs:463-494, row_to_batch.rs:138-145, table/flow_notifier.rs:60 |
| Instant-TTL source tables | N/A (batching flows reject instant-TTL sources; streaming fills its own defaults) | [SOURCE] operator ddl.rs:271-288,917-931; flow batching engine.rs:636-643 |
| Flows whose plan has no eligible TWE | Not affected (`set_dirty()` on any insert) | [SOURCE] engine.rs:405-407 |
| DELETE | N/A (deletes are never mirrored to Flow; adjacent, separate contract) | [SOURCE] no FlowMirrorTask in delete.rs |

Other effects that bound the impact:

- Incremental-read mode (`experimental_enable_incremental_read`, default `false`) treats dirty windows as a scheduling signal only. There, a later explicit-ts write repairs the sink. [SOURCE] task.rs:2112-2136
- In the default scoped mode, only a later write that lands in the same window repairs it. With a constant default such as a fixed date, that usually never happens. [INFERENCE]

## 5. Minimal deterministic reproduction

**Status: pending, blocked on shared-disk capacity.**

- The build was started once:

  ```bash
  CARGO_TARGET_DIR=/home/user/greptimedb-target CARGO_BUILD_JOBS=2 timeout 7200 cargo test -p flow --lib repro_defaulted_time_index_dirty_window -- --nocapture
  ```

  It stayed at "Blocking waiting for file lock on build directory" behind other agents' builds and never compiled a crate. The lead then asked me to cancel it, because free disk fell to about 6 GB and `flow` pulls in operator, servers, query and catalog. I stopped it (TaskStop) and confirmed that no `cargo test -p flow` process remained. Nothing was written to or deleted from the shared target.
- No test from this candidate has been executed, so nothing in this report about runtime behavior is labelled [EXECUTED].

### Reproducer, kept for a later run

`/tmp/claude-0/-home-user-greptimedb/0a7498d9-9500-5f31-9e64-7a1e4b9bc8c6/scratchpad/candidates/candidate-4-repro.diff`

- A 178-line addition to the `#[cfg(test)] mod tests` of `src/flow/src/batching_mode/engine.rs`.
- Also saved at `scratchpad/c4/repro_test.diff`.
- `git apply --check` against base `2b596fd5` passes. [EXECUTED] The worktree has been restored to a clean base.
- Run it with the command above once there is room for disk (roughly 8-10 GB of new artifacts for the flow test binary [INFERENCE]).

### What the reproducer does

It exercises the real production functions, not copies of them, in one binary:

1. It registers source `TableInfo`s in the engine's `table_meta`. The schema is `col1 INT` (primary key) plus `ts TIMESTAMP(3) TIME INDEX DEFAULT <x>`.
2. For each table it creates a batching task with a real 5-second `date_bin` time-window expression, using the existing `new_test_task_for_source` and `test_time_window_expr` helpers.
3. **Mirror path (default config):**
   - It builds the region request exactly as `StatementToRegion::prepare` would for `INSERT INTO t (col1) VALUES (1)`, so the row schema is `[col1]`.
   - It passes that through the real frontend `operator::req_convert::insert::fill_reqs_with_impure_default`, which `Inserter::do_request` applies immediately before `FlowMirrorTask`.
   - It feeds the result to the real `BatchingEngine::handle_inserts_inner` (the function the flownode insert entry reaches for batching sources).
   - It records the mirrored column list and `dirty_time_windows.len()`.
4. **Sibling table-batcher path, same rows:**
   - It calls the real `rows_to_record_batch` and `extract_timestamps`, then `handle_mark_dirty_time_window`.
   - It records the timestamps and the window count.

Three cases:

| Case | Time-index default | Row shape | Asserted (current base behavior) |
|---|---|---|---|
| `src_const_omitted` | constant `5000 ms` | omits ts | mirrored columns = `["col1"]`; **mirror-path dirty windows = 0**; batcher timestamps = `[5000]`; batcher-path windows = 1 (window `[5s,10s)`) |
| `src_const_explicit` | constant `5000 ms` | ts = 7000 | mirror-path windows = 1 (explicit control) |
| `src_impure_omitted` | `current_timestamp()` | omits ts | filler adds `ts`; mirror-path windows = 1 (impure control) |

### What it would demonstrate

With its assertions passing on the clean base, it would show the following deterministically:

1. The mirrored request for a constant-default time index carries no `ts` column after the frontend's own default filling.
2. The batching engine then marks **no** dirty window, which means no signal. `task.rs:2160-2166` then produces no query, so the sink stays stale, including after `ADMIN FLUSH_FLOW` (engine.rs:976-1005).
3. The same logical write, when routed through the opt-in table batcher, marks the window of the stored default timestamp. This is the in-repo oracle for the expected behavior.
4. Explicit and impure-default writes are unaffected.

The reproducer does **not** run a full frontend, datanode and flownode stack. The link "SQL INSERT produces rows without ts on the mirror path" is covered by [SOURCE] (dml.rs:34, stmt_to_region.rs:97/262, insert.rs:653/741-785). A full end-to-end sqlness case would need the `greptime` binary and was never attempted.

### Stack-level scenario to reproduce later

This would give the "stale batching-flow result" observable. [INFERENCE] expected output: empty sink, or no row for window `2024-01-01T00:00:00`.

```sql
CREATE TABLE src (host STRING PRIMARY KEY, v INT,
  ts TIMESTAMP DEFAULT '2024-01-01 00:00:05' TIME INDEX);
CREATE TABLE snk (cnt BIGINT, time_window TIMESTAMP TIME INDEX);
CREATE FLOW f SINK TO snk AS
  SELECT count(v) AS cnt, date_bin(INTERVAL '1 minute', ts) AS time_window
  FROM src GROUP BY time_window;
INSERT INTO src (host, v) VALUES ('a', 1), ('b', 2);
ADMIN FLUSH_FLOW('f');
SELECT * FROM snk;   -- base: no row; expected: cnt=2 at 2024-01-01T00:00:00
```

The same script with `ts` supplied explicitly should produce the row. [INFERENCE]

## 6. Deterministic vs non-deterministic defaults; what repo semantics imply

- **Constant (pure) default**, `ColumnDefaultConstraint::Value`. The value is typed and timezone-resolved once at CREATE TABLE (`default_constraint.rs:49-54`), so it is deterministic. The datanode fills it (`mito2 request.rs:286,384`). The frontend never fills it on the mirror path. So the flownode can compute the effective timestamp exactly from table metadata with `ColumnSchema::create_default()`, in the column's unit. The table batcher (`rows_to_record_batch`) and the streaming engine (`FetchFromRow::Default`) already do this. **This is the only case that reaches the bug.**
- **Impure default**, `ColumnDefaultConstraint::Function` (`current_timestamp()`, `now()`). It is non-deterministic. The repo's contract is "evaluate once in the frontend, send the same value to datanode and Flow" (`fill_reqs_with_impure_default`). mito rejects an omitted impure column. So normal mirrored requests always carry the value, and Flow must **not** re-evaluate `now()` on the flownode, because that would give a timestamp different from the stored one.
  - Exception: instant-TTL requests are intentionally left unfilled ("filled in flownode directly"), but only streaming flows can consume them.
  - A batching fix should therefore treat an omitted impure-default time index as unexpected. It should not mark a window it cannot know. In practice this state is unreachable from the frontend.
- **No default** (non-nullable time index): mito rejects the write, so no window should appear. Because the mirror is detached **before** the datanode write (#8420), Flow may still see the request. Inventing a window for it would be wrong, and fixing the ordering is contaminated by #8428.

## 7. Proposed frozen scope and draft prompt (only if the lead overrides the REJECT)

In scope:

- A batching flow with an eligible time-window expression must mark the window of the effective stored timestamp when mirrored source rows omit a time index whose default is a constant. This applies per mirrored row set (mixed explicit and omitted shapes in one request) and for any timestamp unit.
- Explicit-timestamp behavior is unchanged.
- The same result must hold through the flownode insert entry point.

Out of scope:

- Notification ordering or failed-write suppression (#8420/#8428).
- Deletes.
- Partition routing of defaulted columns (missing partition columns route as NULL, `partition/src/splitter.rs:110-122`).
- Bulk-insert impure defaults (`bulk_insert.rs:156`).
- Incremental-read mode.
- Re-evaluating impure defaults on the flownode.
- ALTER of a default racing with in-flight notifications.

Draft prompt (about 130 words, `bugfix`):

```text
Batching flows miss updates when a source write omits the time index column and the table supplies a constant default for it. The rows are stored with the default timestamp, but the flow never marks the corresponding time window as changed, so the sink keeps returning stale aggregates even after the flow is flushed.

When mirrored source rows do not include the time index column and the source table's time index has a constant default, the batching flow must track the same time window it would track if that timestamp had been written explicitly, using the table's timestamp unit. This must work when several rows are written at once and when one request mixes rows that provide the timestamp with rows that rely on the default. Writes that provide the time index explicitly must behave exactly as before.
```

## 8. Estimated production files and effective LOC

Likely fix, honest estimate: **1 to 2 production files, about 30 to 80 effective LOC.**

- Option A (flownode): in `engine.rs::handle_inserts_inner`, pass the source `TableInfoValue`'s time-index `ColumnSchema` into `handle_rows`. In `time_window.rs::handle_rows`, when the column is absent and the default is `Value`, synthesize it with `create_default()` in the table's type (one value is enough for one window per Rows).
- Option B (frontend): fill constant time-index defaults into the mirrored copy in `do_request`/`FlowMirrorTask`.

This is far below the 200-LOC long-horizon median target. The source TODO sits exactly at the fix site, and the table batcher and streaming engine show the pattern, so strong agents will converge quickly and the pass rate would likely exceed 50%. [INFERENCE]

## 9. Proposed test architecture (fair assertions only)

- **NEW** (flow crate, engine-level, deterministic, no sleeps). Build `BatchingEngine` with the existing `new_test_engine` / `new_test_task_for_source` / `test_time_window_expr` helpers and register source `TableInfo` in `table_meta`. Oracle: **the same write with the timestamp supplied explicitly** (relative oracle, prompt-stated).
  1. Omitted constant-default ts produces the same dirty-window set as an explicit write of the default value.
  2. Several rows omitted produce that single window.
  3. One request mixing an explicit-ts `Rows` and an omitted-ts `Rows` produces the union of windows.
  4. Second/ms/us/ns time-index units give the same aligned window as explicit writes.
  5. The flownode entry point (`FlowDualEngine`/`Flownode::handle_inserts`) gives the same result.
  6. Explicit-ts regression.
  7. Optional: a flow without an eligible TWE still becomes dirty.
  - Do not assert: behavior for impure/no-default omitted ts, error texts, internal helper names, log output.
- **BASE**: existing `cargo test -p flow --lib batching_mode::` (engine, time_window, state, task tests) plus operator `fill_impure_default` / `row_to_batch` unit tests.
- Mutation kill check: "only first Rows handled" is caught by test 3. "Wrong unit / row datatype reused" is caught by test 4. "Frontend-only fix that the flownode entry test bypasses" would be unfair to Option B, so tests must go through the flownode entry with the request shape the frontend actually sends (no ts column). Both Option A and Option B would then only pass if B also changes that shape. **This makes a fair test that admits both options awkward**, which is another risk.

## 10. Contamination verdict

**CONDITIONAL PASS.**

- Git history, the blob sweep over every upstream PR and branch ref, GitHub issues/PRs/discussions and release notes show no implementation of default-aware batching dirty windows and no maintainer decision against it. [EXECUTED]/[UPSTREAM]
- Conditions:
  1. The Olympus platform-duplicate check is [PLATFORM] UNVERIFIED.
  2. The "failed writes must not notify" scenario from the handoff draft must be dropped, because it is covered by open issue #8420 and closed PR #8428.

Overall recommendation: **REJECT on size and difficulty (section 2.8)**, not on provenance.

## Commands producing [EXECUTED] evidence

All were run in the worktree or against its git object store. None of them is a build or a test run.

1. `git rev-parse HEAD origin/main` gave `2b596fd5...` for both; `git status --short` was clean before and after.
2. `git blame -L 270,290 HEAD -- src/flow/src/batching_mode/time_window.rs`: all lines from #5785 (2025-03-31).
3. `git log -G'handle_rows|time index column is not present' origin/main -- src/flow` found #5785 and #5807. `git log --all -S'handle case where time index column is not present'` found #5785, gh-pages and the fork snapshot `c4d55cbdea`.
4. `git for-each-ref refs/upstream-pr refs/upstream-heads` listed 7287 refs. `git log --stdin` over those refs plus `^origin/main` was run with:
   - `-G'time index column is not present|can.t found time index column|fn handle_rows'`
   - `-i -G'default' -- batching_mode/{engine,time_window}.rs`
   - `-G'fill_reqs_with|ImpureDefaultFiller|create_default|FlowMirrorTask|pure_default|fill_default' -- operator insert/fill files`
   - `-G'default_values|FetchFromRow|create_default|default_constraint' -- src/flow`
5. Blob sweep: `git cat-file --batch-check` on `<ref>:src/flow/src/batching_mode/time_window.rs` and `<ref>:.../engine.rs` for all refs, then `git cat-file --batch` on the distinct blobs. `time_window.rs` has 13 distinct blobs, all with the TODO and skip-branch. `engine.rs` has 46 blobs with 5 distinct `handle_inserts_inner` bodies, none filling defaults.
6. `git show a27c5acffc` (PR #8428 head) and `git show --stat c8f65c7b99` (#8544 merged): no default handling.
7. `git apply --check [-R] candidate-4-repro.diff`: the saved reproducer matches what was in the worktree and re-applies cleanly to base.
8. `pgrep -af "cargo test -p flow"` returned nothing, confirming the cancelled build left no processes. `df -h /` showed 6.4 GB free at cancellation.

Not executed: the reproducer test itself (pending, section 5) and any sqlness or integration run.
