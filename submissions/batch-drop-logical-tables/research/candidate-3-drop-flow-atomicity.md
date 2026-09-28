# Candidate 3: Failure-Atomic and Recovery-Safe DROP FLOW (research report)

Scope: research phase only (handoff sec 23). No reference solution, test.patch,
solution.patch or Dockerfile were written. One disposable reproducer was added to
this agent's worktree, executed, saved to scratchpad, and reverted.

- Worktree HEAD: `2b596fd52df31dcad779794877a296de7746f736` (= `origin/main`,
  "ci: deploy MinIO chart with Silo images (#9362)"). Clean tree before and after
  the reproducer was reverted. [EXECUTED]
- Evidence labels: [SOURCE] [EXECUTED] [UPSTREAM] [PLATFORM] [INFERENCE].

**Verdict: REFORMULATE. Originality: CONDITIONAL PASS.**

The TODO is backed by a real, deterministic, executed inconsistency. If the flownode
drop or the cache broadcast fails after `DeleteMetadata`, the procedure fails
terminally (no retry, no rollback), and its persisted state is deleted. The flow's
metadata is gone while the flownode keeps the task. No user retry or procedure
recovery can reach it again (repro A, A2, B). However, most of the handoff draft's
requirements already hold at HEAD: resume between stages, FlowNotFound idempotence,
and retry of retryable errors (repro C). The "partial multi-flownode" scenarios are
unreachable because flows have a single partition. The task must be narrowed to "a
failed DROP FLOW leaves the flow in place and droppable" (bugfix). Main risk:
the fix may be too short (under 200 LOC, pass rate over 50%).

---

## 1. Source-path map

| Concern | Path | Notes |
|---|---|---|
| DROP FLOW procedure, state machine | `src/common/meta/src/ddl/drop_flow.rs` | `DropFlowState { Prepare, DeleteMetadata, InvalidateFlowCache, DropFlows }` + `// TODO(weny): support to rollback` (line 268). No `rollback_supported`/`rollback` override, so framework default `false`. Lock key = `CatalogLock::Read` + `FlowLock::Write(flow_id)` only (no `FlowNameLock`). [SOURCE] |
| Prepare metadata fill | `src/common/meta/src/ddl/drop_flow/metadata.rs` | Reads `FlowInfoValue` by `task.flow_id` and all routes; route partition ids are discarded (`.map(\|(_, v)\| v)`). [SOURCE] |
| Existing tests | `src/common/meta/src/ddl/tests/drop_flow.rs` | 3 tests: not-found, happy path + drop-if-exists, pending flow. No failure injection. [SOURCE] |
| Flow metadata keys | `src/common/meta/src/key/flow.rs` (+ `flow_name.rs`, `flow_info.rs`, `flow_route.rs`, `flownode_flow.rs`, `table_flow.rs`) | `destroy_flow_metadata` = unconditional `batch_delete` of name, info, flownode-flow, route and table-flow keys (no compare, no tombstone). `create_flow_metadata` is a compare-and-put txn that is idempotent for identical values and fails with `FlowAlreadyExists` if the name maps to another id. [SOURCE] |
| Cache invalidation | `src/common/meta/src/cache_invalidator.rs`, `src/common/meta/src/cache/flow/table_flownode.rs`, metasrv impl `src/meta-srv/src/cache_invalidator.rs` | Drop broadcasts `FlowId`, `FlowName`, `DropFlow{source tables, part->node}`. Metasrv broadcast errors are wrapped as `External` (non-retryable). `CacheIdent::DropFlow` only touches caches; no node removes a flow task because of it. [SOURCE] |
| Flownode requester | `src/client/src/flow.rs` (`FlowRequester`) | Every flownode RPC error, including tonic `Unavailable`/`DeadlineExceeded`, becomes `common_meta::Error::External` (never `RetryLater`). Contrast `src/client/src/region.rs` `RegionRequester`, which maps `should_retry()` errors to `RetryLater`. [SOURCE] |
| FlowNotFound idempotence | `drop_flow.rs:120-124` | `StatusCode::FlowNotFound` from a flownode is treated as success. [SOURCE] |
| Error to procedure mapping | `src/common/meta/src/ddl/utils.rs` `map_to_procedure_error`, `add_peer_context_if_needed`; `src/common/meta/src/error.rs` `is_retry_later` | Only `Error::RetryLater`/`GetLatestCacheRetryExceeded` are retried; `External` with a retryable source hint is still not retried. [SOURCE] |
| Procedure runner | `src/common/procedure/src/local/runner.rs` | Non-retryable error + `rollback_supported()==false` => `Failed` immediately; retry exhaustion => `PrepareRollback` => `Failed`. When a root procedure finishes (Done/Failed/Poisoned) and the manager is running, `run()` calls `store.delete_procedure(id)`. [SOURCE] |
| Procedure recovery | `src/common/procedure/src/local.rs` `recover`, `src/common/procedure/src/store.rs` `load_messages` | Only procedures with persisted step keys are resumed; a failed root procedure has none left. [SOURCE] |
| DdlManager dispatch + enterprise hook | `src/common/meta/src/ddl_manager.rs` (`DropFlowHandler` trait, `with_drop_flow_handler`, dispatch at ~1023, `handle_drop_flow_task` ~1360) | Added by #9171 (2026-09-18). Pure extension hook; no implementation in this repository. [SOURCE] |
| Frontend DROP FLOW | `src/operator/src/statement/ddl.rs` `drop_flow` (~1303) | Resolves `flow_id` by name via `flow_name_manager().get`; if absent returns `Ok` (IF EXISTS) or `FlowNotFound` without submitting a DDL. [SOURCE] |
| Flownode drop + reconciliation | `src/flow/src/adapter/flownode_impl.rs` | `remove_flow` for an unknown flow triggers a one-off consistency check with `allow_drop=true` and comments: "this rely on drop flow ddl delete metadata first, see src/common/meta/src/ddl/drop_flow.rs". Periodic check (every 10s) runs with `(allow_create, allow_drop) = (false, false)` and only warns "Flows do not exist in metadata". Startup recovery uses `(true, false)`. [SOURCE] |
| Batching task lifetime | `src/flow/src/batching_mode/task.rs` `start_executing_loop`/`start_scheduled_loop` | Loops until `is_shutdown_signaled()`, which only `remove_flow` sets. [SOURCE] |
| Comparison procedures | `src/common/meta/src/ddl/drop_table.rs`, `drop_table/executor.rs`, `drop_view.rs` | See section 6. |

## 2. Git-history search

- `git blame` on `DropFlowState`: every line, including `// TODO(weny): support to rollback`,
  comes from `5545a8b023` "feat: implement drop flow procedure (#3877)" (2024-05-09).
  The TODO has never been touched. [EXECUTED]
- `git log --follow` of `drop_flow.rs` (15 commits: #3877, #3926 cache invalidation,
  #4179 peer lookup, #4263 `FlowRouteValue`, #4231, #5610, #5846, #6108, #6189
  poison cleanup, #6920, #7069, #8632/#8734/#8787/#8834 events). None changes
  stage order, retry classification or rollback. [EXECUTED]
- Original design (#3877): identical stage order; `on_broadcast` was a TODO no-op
  filled by #3926. Metadata-first ordering has been the design since inception. [EXECUTED]
- `-G'DropFlowState'` over all 7287 upstream PR heads and branches, excluding `origin/main`:
  only `fbed931c0d` (the original #3877 branch commit) and `c4d55cbdea` (a fork's
  whole-repo root import). [EXECUTED]
- Commit-message grep across all refs for drop-flow terms and for
  flow + rollback/atomic/orphan/leftover/idempotent/retry found related but
  non-implementing work only: #5391 "deal with flow drop leftover" (flownode
  sink write-back skip when the sink table is gone, `src/flow/src/adapter.rs`),
  #6135 cache invalidation of table-flow keys, `4a7491bf55` flownode locks,
  `e05ca924ed` replace-with-pending drop, #5987/#5600 flow retries, #8301 generic
  retry hints (on main, does not touch `FlowRequester` or `is_retry_later`),
  `f22c6fb407` (unmerged branch; flow/frontend error hints only). [EXECUTED]

## 3. All-state upstream search (PR heads, issues, discussions)

Blob comparison at each of the 7287 ref tips [EXECUTED]:

| File | Distinct blobs | Result |
|---|---:|---|
| `ddl/drop_flow.rs` | 16 (+MISSING) | Every blob still contains exactly one match for the rollback/retry/tombstone pattern: the TODO line. No `rollback_supported`, `fn rollback`, `RetryLater`, tombstone or restore. Variants differ only in events (#8734/#8787), cluster id, or #7691's `flow_rpc` indirection (abandoned "refactor: node manager"). |
| `drop_flow/metadata.rs` | 6 | No behavioral variant of interest. |
| `key/flow.rs` | 34 | `destroy_flow_metadata` is an unconditional `batch_delete` in every variant; no tombstone/restore/soft-delete for flows. |
| `client/src/flow.rs` | 10 | No variant maps flownode errors to `RetryLater` (0 matches for `RetryLater|should_retry|retry`). |
| `flow/src/adapter/flownode_impl.rs` | 58 | No variant enables periodic `allow_drop=true`; 33 variants carry the "rely on drop flow ddl delete metadata first" comment. |

GitHub (public web/API) [UPSTREAM]:
- API search `"drop flow"`: 62 hits (5 issues, 57 PRs). Issues: #7603 DDL WITH
  timeout/wait (open), #8420 flow mirror inserts detached (open), #5885, #5033,
  #5226 (closed, unrelated). No issue about failed DROP FLOW leaving a running flow.
- PR hits are feature/event/refactor PRs (#3877, #3888, #3900, #3915, #3926, #4179,
  #4263, #4280, #5001, #5391, #6108, #7793, #8124, #8632, #8787, #8834, #9171 ...).
  None implements drop-flow rollback, retry classification or orphan cleanup.
- Web searches "drop flow rollback", "flownode drop flow fail", "flow still running
  after drop", "flow orphan", `"drop flow" retry`, `is:pr DropFlowProcedure`,
  `is:pr FlowRequester retry` (0 results), `is:issue flow metadata inconsistent`:
  nothing implementing or declining the behavior. #8418 (open) is the R3 timeout
  seed, unrelated to atomicity.
- Discussions search for "drop flow": the query returned only unrelated generic
  discussions; no relevant thread found.
- Some API calls were rate-limited (HTTP 403) after the first queries; the web UI
  searches above were used instead. Release notes were not separately audited
  beyond the PR/commit searches. [UPSTREAM] partial
- Olympus platform duplicate check: [PLATFORM] UNVERIFIED.

## 4. Current-HEAD analysis of every stage boundary

Runner facts used below [SOURCE]: `Status::executing(true)` persists the dumped
data after a step returns; a `RetryLater` error is retried (default
`max_retry_times=3`, 500 ms base backoff) and then goes through
`PrepareRollback` to `Failed`; any other error with `rollback_supported()==false`
goes straight to `Failed`; a finished root procedure's persisted state is deleted,
so it is never resumed; a manager stop leaves state for `recover()`.

| Boundary | Mutation | Persisted after step | Retried? | Idempotent on replay? | Outcome of a terminal failure |
|---|---|---|---|---|---|
| `Prepare` | none (reads name, info by `task.flow_id`, routes) | `state=DeleteMetadata`, `flow_info_value`, `flow_route_values` | only `RetryLater` | yes | nothing changed; user can retry. Consistent. |
| `DeleteMetadata` | one unconditional `batch_delete` of name/info/route/flownode-flow/table-flow keys | `state=InvalidateFlowCache` | only `RetryLater` (KV errors such as `EtcdFailed` are not) | for its own keys yes; **not** with respect to a new flow reusing the name (the name key is deleted without comparing its flow id) | if the delete did not apply: consistent. If it applied but the call errored (ambiguous commit): same orphan as below. |
| `InvalidateFlowCache` | broadcast `FlowId`, `FlowName`, `DropFlow` | `state=DropFlows` | no: metasrv mailbox errors are `External` | yes | metadata gone, **no flownode was asked to drop**, caches may be partially stale. Orphan. |
| `DropFlows` | `DropRequest` to each route peer (`join_all`); `FlowNotFound` counts as success | done | only `RetryLater`; production `FlowRequester` never returns it | yes (a flownode that no longer has the flow returns Ok or FlowNotFound) | metadata gone, flow task still on the flownode. Orphan. |

What repairs an orphan today [SOURCE]:
- Not the user: frontend `drop_flow` resolves the id by name, finds nothing, and
  returns `Ok` (IF EXISTS) or `FlowNotFound` without submitting a DDL. Even a
  metasrv-level resubmission with the old id stops in `Prepare`.
- Not the procedure framework: the failed procedure's state is deleted.
- Not the flownode's periodic check: it runs with `allow_drop=false` and only logs
  "Flows do not exist in metadata".
- Only (a) a flownode restart (in-memory tasks vanish and recovery creates only
  flows present in metadata) or (b) an incidental `remove_flow` of an unknown
  flow id on that flownode, which triggers one `allow_drop=true` check.
- Until then a batching task keeps running: `start_scheduled_loop`/adaptive loop
  exit only on the shutdown signal set by `remove_flow`. With `EVAL INTERVAL` it
  keeps querying sources and writing the sink. [SOURCE] End-to-end sink writes
  after a failed drop were not executed in a cluster. [INFERENCE]

Interrupted (crash) drops resume cleanly from persisted state at every boundary,
with one exception: `DropFlowProcedure` does not take `FlowNameLock` (CreateFlow
takes only `FlowNameLock`, so the two never conflict), and a replayed
`DeleteMetadata` deletes whichever flow currently owns the name. [SOURCE]

Scenarios in the handoff draft that do **not** apply at HEAD [SOURCE]:
- "one flownode succeeds while another fails": flows have exactly one partition
  (`let partitions = 1;` in `create_flow/metadata.rs`), so one route per flow.
  That is Candidate 2's territory and must stay out of scope.
- FlowNotFound idempotence, resume after dump/restore between stages, and
  retry of `RetryLater` flownode errors already work (see repro C).

## 5. Deterministic reproduction (executed)

Reproducer: `scratchpad/c3/repro_c3.diff` (429 lines, one `mod repro_c3` appended
to `src/common/meta/src/ddl/tests/drop_flow.rs`). It uses only existing
infrastructure: `MockFlownodeManager` with a recording `MockFlownodeHandler`,
`new_ddl_context` (in-memory KV), `create_test_flow`, `DropFlowProcedure::dump`/
`from_json`, and a real `LocalManager` + `KvStateStore`. The injected flownode
error has the same shape `FlowRequester` produces for any gRPC failure
(`Error::External` over a boxed source). No sleeps are used for correctness. One
bounded poll only detects the runner's post-notification state deletion, and it
observed `polls=0`.

Command (single build, per shared-disk rules):
`CARGO_TARGET_DIR=/home/user/greptimedb-target CARGO_BUILD_JOBS=2 cargo test -p common-meta --lib repro_c3 -- --nocapture --test-threads=1`
gave `test result: ok. 5 passed; 0 failed` (only `common-meta` recompiled; 16m46s incl.
lock wait). Log: `scratchpad/c3/repro_run1.saved.log`. [EXECUTED]

| Case | Injection | Observed [EXECUTED] | Meaning |
|---|---|---|---|
| **A** procedure-level | flownode returns `External` for `DropRequest` | before: `name(my_flow)->Some(1024) info=true routes=1 flownode_flow=1 table_flow=1`; attempt: `is_retry_later=false rollback_supported=false`; after: `name->None info=false routes=0 flownode_flow=0 table_flow=0`; flownode log `[(0, 1024, false)]`. Flownode healed, then retries: frontend name lookup `None`; resubmit with `drop_if_exists=true` done with no RPC; with `false`, `Flow not found: 'greptime.my_flow'`; final flownode log still `[(0, 1024, false)]` | **Inconsistent and unrepairable.** Metadata says the flow is gone; the flownode never removed it; no retry path reaches the flownode again. |
| **A2** real `LocalManager` | same | `submit -> Err("Failed to execute procedure")`; state `Failed{external error}`; persisted procedure keys `0`; after `stop()`+`start()` (recover) `procedures after restart/recover: 0`; flownode log unchanged | The runner does not retry or roll back, deletes the procedure state, and recovery resumes nothing. |
| **B** | cache invalidator fails (`External`, as metasrv mailbox errors are wrapped) | error `is_retry_later=false`; metadata fully deleted; flownode drop log `[]` | Same orphan, and this time the flownode was never even asked. |
| **C** contrast | flownode returns `RetryLater` once | `first error is_retry_later=true`, then success; log `[(0,1024,false),(0,1024,true)]` | Retryable errors already self-heal. The gap is terminal errors, and production `FlowRequester` makes every flownode error terminal. |
| **D** crash replay | dump after Prepare, run DeleteMetadata, "crash", create a same-name flow, restore and resume | lock keys `["Share(__catalog_lock/greptime)", "Exclusive(__flow_lock/1024)"]` (no flow-name lock); new flow 1025 created; after replay `name(my_flow)->None info(1025)=true routes=1 flownode_flow=1 table_flow=1` | The replayed unconditional delete strips the **new** flow's name key: flow 1025 keeps running, and its metadata can no longer be resolved or dropped by name. It needs a crash inside the DeleteMetadata step and a same-name CREATE completing in that window, so it is rare in production. It is a design hazard for any rollback or restore. |

Additionally, the already-built test binary was run directly, with no build, using the
filter `ddl::tests::drop_flow ddl::tests::create_flow key::flow cache::flow`:
`86 passed; 0 failed` (81 existing tests plus the 5 repro tests). [EXECUTED]

The reproducer was then reverted: `git status --short` is empty at `2b596fd5`. [EXECUTED]

Externally meaningful consequence: after a DROP FLOW returns an error, SHOW FLOWS
and DROP FLOW treat the flow as gone. Its batching task keeps executing on the
flownode until restart, and a new flow of the same name can be created alongside
it. [SOURCE] + [EXECUTED] for the metadata and flownode-RPC part; the
sink-write effect in a live cluster is [INFERENCE].

## 6. Comparison with DropTable and DropView

| Failure class | DropTable (`drop_table.rs`, `drop_table/executor.rs`) | DropView (`drop_view.rs`) | DropFlow |
|---|---|---|---|
| Name serialization | `TableNameLock` + `TableLock::Write` | Catalog/Schema read + `TableLock` (no remote side effects) | `FlowLock::Write(id)` only; no `FlowNameLock` |
| Metadata delete | logical: moved to tombstone keys, restorable via `on_restore_metadata`; final `DeleteTombstone` stage after datanodes drop regions | physical delete | physical `batch_delete` up front |
| Transient node errors | `RegionRequester` maps Unavailable/Cancelled/DeadlineExceeded/retryable to `RetryLater`; addresses remapped on retry (`remap_region_routes`) | n/a | `FlowRequester` maps everything to `External`; addresses captured at Prepare |
| `*NotFound` from node | `RegionNotFound` = success | n/a | `FlowNotFound` = success |
| Rollback | only for metric physical tables (`allow_rollback`, #4525); enterprise soft-drop retries forever (`ensure_retry_later`) | none | none (`TODO(weny): support to rollback` since #3877) |
| Residual inconsistency after terminal failure | table hidden (tombstone), regions left open, but region leases stop being granted for regions without routes (`closeable_region_ids` in `handler/region_lease_handler.rs`), so the running part self-heals | stale caches only; nothing keeps running | flow hidden, task keeps running, nothing reconciles it |

So DropFlow lacks all three mitigations DropTable has (retryable transport
classification, restorable tombstone, lease-based cleanup), and its own design
comment on the flownode side makes the metadata-first order load-bearing
(`flownode_impl.rs`: "this rely on drop flow ddl delete metadata first"). A fix
cannot simply reorder the stages. [SOURCE] [INFERENCE]

The enterprise `DropFlowHandler` (`ddl_manager.rs`, #9171) replaces the whole
submission when registered. It has no implementation in this repository, so it
neither fixes nor changes the open-source path. Tests would run without the
`enterprise` feature and exercise `DropFlowProcedure` directly. [SOURCE] Whether
the private enterprise handler has the same gap is unknown. [INFERENCE]

## 7. Proposed frozen scope, category, and draft prompt

The candidate survives, but only in a **narrowed form**. Most requirements in the
handoff draft already hold at HEAD (resume between stages, FlowNotFound
idempotence, RetryLater retry), and the multi-flownode partial case is
unreachable. The real, reproducible gap is: *a DROP FLOW that fails after the
metadata delete is neither atomic nor repairable.*

Category: `bugfix` (reproducible inconsistent state, section 5).

In scope:
1. A DROP FLOW that returns an error, whether from a flownode drop failure or a
   cache-broadcast failure after the metadata was deleted, must leave the flow in
   place. It must still be visible under its name with the same id, source tables
   and route, and frontend routing caches must agree with that.
2. A later DROP FLOW of the same name must then complete: it must reach the flownode
   and delete all flow metadata keys. `FlowNotFound` from the flownode stays success.
3. The failure path must be recovery-safe. A procedure interrupted during
   rollback or between stages must converge after resume.
4. Unrelated flows, pending flows (no routes), and CREATE FLOW behavior are
   unchanged.
5. Optional, decide at freeze: DROP FLOW serializes with CREATE [OR REPLACE] FLOW
   of the same name, so a restore or replay never touches another flow owning the
   name. This is natural parity with DropTable's `TableNameLock`, but see the test
   caveat in section 9.

Out of scope: multi-partition flows; flownode-side reconciliation changes;
tombstones or soft drop for flows; transient-error classification in
`FlowRequester` (natural sibling, but not testable in `common-meta` without
dictating structure); enterprise `DropFlowHandler`; CREATE OR REPLACE vs DROP
races beyond name serialization.

Draft task prompt (about 170 words):

```text
DROP FLOW can fail after it has already removed the flow's metadata. If the
flownode rejects the drop request or cannot be reached, or the cache
invalidation broadcast fails, the statement returns an error, but the flow no
longer exists in metadata while its task keeps running on the flownode. A
retried DROP FLOW then reports that the flow does not exist, or succeeds
without doing anything under IF EXISTS, so the task keeps running until that
flownode restarts.

Make a failed DROP FLOW leave the flow in place. After the error the flow must
still be visible under its name with the same id and routing, and cached flow
routing must agree with it, so a later DROP FLOW of that name can finish the
job: it must reach the flownode and remove all of the flow's metadata. A
flownode that reports the flow is already gone still counts as a successful
drop. A drop interrupted by a metasrv restart must still converge when the
procedure resumes. Other flows, flows without routes, and CREATE FLOW behavior
must not change.
```

## 8. Estimated production files and effective LOC

[INFERENCE], for a rollback-style fix matching the TODO:
- `src/common/meta/src/ddl/drop_flow.rs`: `rollback_supported` for post-delete
  states, `rollback` restoring metadata idempotently (for example via
  `create_flow_metadata`, which is compare-and-put and idempotent for identical
  values), re-broadcast of flow caches, optional `FlowNameLock`. About 60-100 LOC.
- `src/common/meta/src/ddl/drop_flow/metadata.rs`: keep partition ids with the
  routes (today discarded), with backward-compatible serde for in-flight
  procedures persisted by older versions. About 15-30 LOC.
- Possibly `src/common/meta/src/key/flow.rs` (restore helper or compare-guarded
  delete of the name key). About 20-50 LOC.
- Total about 100-180 production LOC in 2-3 files. With tests, a successful solver
  plausibly reaches about 250-450 LOC.
- Risk: the TODO points straight at "rollback", and `create_flow_metadata` makes a
  restore short, so a strong solver may finish with a small diff. Expected pass
  rate could exceed 50%, and the median LOC could fall under 200. Depth comes
  from persisted-state compatibility, cache agreement, name serialization and
  recovery during rollback, not from volume.

## 9. Proposed test architecture

BASE (P2P, existing tests on the touched paths):
`cargo test -p common-meta --lib ddl::tests::drop_flow ddl::tests::create_flow key::flow cache::flow ddl_manager`.
The first four filters ran on HEAD plus the reproducer only: `86 passed` (section 5).
`ddl_manager` was built but not run. [EXECUTED]

NEW (F2P), in `src/common/meta/src/ddl/tests/drop_flow.rs`, using
`MockFlownodeManager` with a recording handler, `new_ddl_context`, the real
`LocalManager` + `KvStateStore` (as in `ddl_manager.rs` tests), and
`DropFlowProcedure::dump`/`from_json`. No sleeps as correctness; gates via
`tokio::sync::Notify`/oneshot in the mock handler.

| # | Requirement | Basis | Test sketch | Oracle | Base result |
|---|---|---|---|---|---|
| N1 | Flownode drop failure leaves the flow in place | prompt | manager-submitted drop, flownode returns a non-retryable error | submit returns Err; name resolves to the same id; info and route present | FAIL (metadata gone) |
| N2 | Retry completes | prompt | N1, then heal the flownode and resubmit the same `DropFlowTask` resolved by name | Ok; flownode got a Drop for the id; no flow keys remain | FAIL |
| N3 | Cache-broadcast failure leaves the flow in place | prompt | invalidator fails once | same as N1; flownode received no Drop | FAIL |
| N4 | Routing cache agrees after failure | prompt | real `TableFlownodeSetCache` over the same KV registered as the invalidator target | cache for the source table still lists the flownode after the failed drop | FAIL (expected; to verify) |
| N5 | Recovery during rollback/resume converges | prompt | dump at each step, `from_json`, continue; for failure paths, recover through manager stop/start | final state equals N1 or N2 respectively | FAIL on the failure paths |
| N6 | FlowNotFound is success | prompt + repo | flownode returns FlowNotFound | drop Ok; metadata gone | PASS (guard) |
| N7 | Unrelated flow untouched | prompt | two flows, fail the drop of one | other flow's keys intact | PASS/guard |
| N8 | Pending flow drop unchanged | repo | existing pending path | Ok | PASS (guard) |

Fairness notes:
- Assert only the name to id mapping, the presence or absence of flow keys through
  public managers, what the mock flownode received, and procedure success or
  failure. Do not assert internal states, error text, rollback-vs-tombstone
  mechanics, or cache ident lists.
- A "retry forever" alternate would hang N1/N3. The prompt says the statement
  returns an error, and the manager config bounds retries (the test can pass a
  `ManagerConfig` with small `max_retry_times`/`retry_delay`), so a timeout only
  detects a stall.
- Name serialization (optional scope item 5) is hard to test without timing: a
  lock-based fix and a compare-guarded fix behave differently only under
  interleavings the test must force. A dump/restore test that bypasses the
  manager's locks (like repro D) would be unfair to a lock-only fix. Either leave
  it out of NEW or test it through `LocalManager` with a gate. In the gated test,
  a correct fix gives a deterministic `FlowAlreadyExists` for the concurrent
  CREATE, but a wrong fix is caught only nondeterministically.

## 10. Contamination verdict

`CONDITIONAL PASS`.
- No upstream PR (any state, all 7287 heads and branches) implements DROP FLOW
  rollback, compare-guarded flow metadata deletion, flow tombstones,
  FlowRequester retry classification, or flownode orphan cleanup. The TODO is
  untouched since #3877. [EXECUTED] [UPSTREAM]
- No issue or discussion declines the behavior. [UPSTREAM] (search API partly
  rate-limited; web-UI searches used.)
- Conditions: Olympus duplicate check [PLATFORM] UNVERIFIED; release notes not
  separately audited; no overlap with Challenge A (repartition staging) or
  Challenge B (append-mode deletes); no overlap with rejected R1-R9. Candidate 2
  (multi-partition flows) is adjacent but disjoint if multi-partition behavior
  stays out of scope.

## Appendix: commands that produced [EXECUTED] evidence

1. `git rev-parse HEAD`, `git status --short`, `git rev-parse origin/main`: base = `2b596fd5...`, clean.
2. `git blame -L 257,269 src/common/meta/src/ddl/drop_flow.rs`; `git log --follow -- src/common/meta/src/ddl/drop_flow.rs` (+ metadata.rs, tests).
3. `git log -G'DropFlowState' --stdin -- src/common/meta` over all upstream refs `--not origin/main`.
4. `git log -i -E --grep=<drop-flow / flow+rollback|orphan|retry...> --stdin` over all 7287 refs.
5. Blob-at-tip scans (`scratchpad/c3_blobs.sh`, `c3_blobgrep.sh`, `c3_keyflow.sh`, `c3_flownode.sh`; map in `scratchpad/c3/blobmap.txt`).
6. `git show` of 5545a8b023 (#3877), 87c21e2baa (#5391), f22c6fb407, e520ff8300 (#8301), and the diff of the PR 7691 blob.
7. `CARGO_TARGET_DIR=/home/user/greptimedb-target CARGO_BUILD_JOBS=2 cargo test -p common-meta --lib repro_c3 -- --nocapture --test-threads=1` gave 5 passed (log `scratchpad/c3/repro_run1.saved.log`).
8. `/home/user/greptimedb-target/debug/deps/common_meta-0a96a7429e111cc0 --test-threads=2 ddl::tests::drop_flow ddl::tests::create_flow key::flow cache::flow` gave 86 passed (binary run only, no build).
9. `git checkout -- src/common/meta/src/ddl/tests/drop_flow.rs` then `git status --short`: clean.

Shared-state note: the shared `common_meta-0a96a7429e111cc0` test binary (same
hash as the lead's) was rebuilt from this worktree, including the reproducer. The
next `cargo test -p common-meta` from another worktree will recompile only
`common-meta`. Nothing under shared paths was deleted.

GitHub web and API searches were [UPSTREAM] via WebFetch. Some API calls returned 403
(rate limit) and were replaced by web-UI searches.
