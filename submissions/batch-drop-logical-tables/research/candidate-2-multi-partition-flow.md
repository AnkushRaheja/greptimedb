# Candidate 2: Multi-Partition Flow Placement and Mirrored-Write Routing (research report)

Title under review: "Support multi-partition flows across multiple flownodes"
Pinned base: `2b596fd52df31dcad779794877a296de7746f736` (worktree HEAD verified, clean)

## Verdict

**REJECT.** Originality label: **REJECT - REPO MISFIT**

The provenance audit itself is clean. No upstream PR, branch, or issue implements multi-partition flow allocation or split mirror routing. The candidate still fails the handoff's gating semantic test:

1. The repository never defines how source rows map to flow partitions.
2. The flownode wire protocol and both flow engines have no notion of a partition.
3. Nothing lets anyone ask for more than one partition.
4. Much of the proposed scope (metadata, cache, drop, and create fan-out for N partitions) already works at HEAD. I ran this.

The only novel work left is a sharding rule and a partition-count input, and both would have to be invented. The handoff forbids inventing them ("Do not invent a hash/sharding rule"). Broadcast replication is not a sound fallback either (see 5.4). No reformulation I found is fair, deterministic, and non-trivial at the same time.

---

## 1. Source-path map

| Concern | Path | What is there at HEAD |
|---|---|---|
| Partition count | `src/common/meta/src/ddl/create_flow/metadata.rs:22-28` | `// TODO(weny, ruihang): We don't support the partitions. It's always be 1, now.` then `let partitions = 1;` then `flow_metadata_allocator.create(partitions)` [SOURCE] |
| Flow id + peer allocation | `src/common/meta/src/ddl/flow_meta.rs` (`FlowMetadataAllocator::create(partitions)`) | Allocates the flow id, then `peer_allocator.alloc(partitions, ..)` [SOURCE] |
| Metasrv peer allocator | `src/meta-srv/src/peer.rs` (`MetasrvPeerAllocator`), wired in `src/meta-srv/src/metasrv/builder.rs:304-325` | Round-robin flownode selector with `allow_duplication: true`, so N partitions may land on the same flownode [SOURCE] |
| Standalone/test allocator | `src/common/meta/src/peer.rs` (`NoopPeerAllocator`) | Returns `vec![Peer::default(); num]` [SOURCE] |
| Create procedure | `src/common/meta/src/ddl/create_flow.rs` | `on_prepare` allocates; `on_flownode_create_flows` sends the **same** `CreateRequest` to every peer, with no partition id; `on_create_metadata` persists `flownode_ids`/routes by enumerating `peers` (partition = index); `on_broadcast` emits `CacheIdent::CreateFlow{partition_to_peer_mapping}`. OR REPLACE reuses all existing routes' peers. Pending flows clear `peers` [SOURCE] |
| Flow info | `src/common/meta/src/key/flow/flow_info.rs:231` | `flownode_ids: BTreeMap<FlowPartitionId, FlownodeId>` [SOURCE] |
| Flow route | `src/common/meta/src/key/flow/flow_route.rs` | `__flow/route/{flow_id}/{partition_id}` -> `FlowRouteValue{peer}` [SOURCE] |
| Flownode->flow | `src/common/meta/src/key/flow/flownode_flow.rs` | `__flow/flownode/{flownode_id}/{flow_id}/{partition_id}` [SOURCE] |
| Table->flow | `src/common/meta/src/key/flow/table_flow.rs` | `__flow/source_table/{table_id}/{flownode_id}/{flow_id}/{partition_id}` -> `TableFlowValue{peer}` [SOURCE] |
| Multi-key txn | `src/common/meta/src/key/flow.rs` (`create_flow_metadata`, `update_flow_metadata`, `destroy_flow_metadata`) | Already writes/deletes every partition's keys [SOURCE] |
| Cache | `src/common/meta/src/cache/flow/table_flownode.rs` | `TableId -> HashMap<FlowIdent{flow_id,partition_id}, Peer>`; create/drop invalidation handles every partition [SOURCE] |
| Mirror writes (row path) | `src/operator/src/insert.rs:1795-1908` (`FlowMirrorTask`) | Collects the **distinct** peers for the source table (`// dedup peers`, `HashSet`). With one peer: fast path. With more than one: `// TODO(discord9): need to split requests to multiple flownodes` and clones the full request to **every** peer. `detach()` spawns fire-and-forget tasks and only logs errors [SOURCE] |
| Mirror writes (bulk path) | `src/operator/src/bulk_insert.rs:356-414` (`maybe_update_flow_dirty_window`) | Sends dirty-window timestamps to every distinct peer; no TODO; detached, errors logged [SOURCE] |
| Flush | `src/operator/src/flow.rs:66-130` | Flushes every route's peer; overwrites (does not sum) `affected_rows` [SOURCE] |
| Drop | `src/common/meta/src/ddl/drop_flow.rs`, `drop_flow/metadata.rs` | `fill_flow_metadata` reads all routes; `on_flownode_drop_flows` drops on every route peer; `FlowNotFound` tolerated [SOURCE] |
| Flownode recovery | `src/flow/src/adapter/flownode_impl.rs:275-295`, `src/flow/src/server.rs:458-470` | `flownode_flow_manager().flows(nodeid)` then `.map(|(id, _)| id)`, which **discards the partition id** [SOURCE] |
| Flownode insert dispatch | `src/flow/src/adapter/flownode_impl.rs:748-800` | Routes rows by **source table id** to every flow on the node (`src_table2flow`); flows keyed by `FlowId` only [SOURCE] |
| Flownode wire protocol | greptime-proto `9533078` `proto/greptime/v1/flow/server.proto` | `CreateRequest`, `DropRequest`, `FlushFlow`, `InsertRequest{region_id, rows, partition_expr_version}`, `DirtyWindowRequest{table_id,..}`: **no flow id or partition id on the data plane, no partition id on the control plane** [SOURCE] |
| Flow state | `src/common/meta/src/key/flow/flow_state.rs:194` | Stats keyed by `FlowId` only [SOURCE] |
| User-visible surface | `src/catalog/src/system_schema/information_schema/flows.rs:371` | `information_schema.flows.flownode_ids` = JSON of the partition->node map [SOURCE] |
| Partition-count input | `CreateFlowExpr` (proto), `CreateFlowTask`, `validate_flow_options` | No partition field; unknown `WITH` options are rejected; no config key [SOURCE] |

## 2. Git-history search

- Blame [EXECUTED]:
  - `let partitions = 1;` comes from `b493ea1b38` (2024-04-29, "feat: implement the `CreateFlowProcedure` (#3810)"); only the comment wording changed later (`fea8bc5ee7`, #6496).
  - The mirror TODO came in with `26f35fbade` / `8b6596faa0` (#4068, 2024-05) and was moved by `7c5ead90ac` (2025-01-24).
  - `// dedup peers` and the `FlowIdent` cache key came from `038acda7cd` (#6108, 2025-05-19).
  - The bulk dirty-window broadcast came from `9d997d593c` (#6291, 2025-06-16).
- `git log -S` for both TODO phrases across `--all` [EXECUTED]: only the introducing, refactor, and typo commits, plus two whole-repo root imports (PR ref 8486 `c4d55cbdea` and the gh-pages deploy). No removal or replacement.
- `git log -G'let partitions|split requests to multiple flownodes|flow_metadata_allocator\s*\.create|\.create\(partitions\)' --stdin` over all 7287 `refs/upstream-pr/*` and `refs/upstream-heads/*` with `^origin/main` [EXECUTED]:
  - 42 hits. All are table-partition work, the root import, or flow foundations.
  - The only flow-allocation change is PR #4179 (`6c590cfb49`): it adds a `cluster_id` argument and the round-robin `FlowPeerAllocator`. Partitions stay 1.
- `git log -G'partition_id|FlowPartitionId|flow_partition|FlowIdent'` over all unmerged refs restricted to `src/flow src/operator` and the flow cache/create paths [EXECUTED]: only #6108, #4263, the edition bump (#6920), COMMENT ON (#7060), and the root import. None consume partition ids.
- Commit-message grep over `--all` for flow+partition, multiple flownodes, shard, and distributed flow [EXECUTED]: nothing implements partitioned flows.
- **Blob-level sweep at every ref tip** (`git cat-file --batch-check`/`--batch`, deduped, then grep) [EXECUTED]:
  - `create_flow/metadata.rs`: 4473 refs, 6 unique blobs. Every blob has `let partitions = 1`.
  - `flow_meta.rs`: 6 blobs, `create(partitions)` only.
  - `create_flow.rs`: 48 blobs. None computes a partition count.
  - `insert.rs`: 142 blobs, 82 contain `FlowMirrorTask`. **All 82 still carry the split TODO.**
  - `bulk_insert.rs`: 29 blobs. None is partition-aware.
  - `table_flownode.rs`: 20 blobs. They differ only in keying.
  - `flow/src/adapter/flownode_impl.rs`: 58 blobs. **None uses a partition id.**

## 3. Upstream PR / issue / discussion search

Searches used the public search API and PR pages.

| Item | State | Relevance |
|---|---|---|
| #4179 "heartbeat task & peer lookup in proc" | merged 2024-06 | Round-robin flownode allocation. No discussion of row routing across flownodes [UPSTREAM] |
| #4263 "introduce `FlowRouteValue`" | merged 2024-07 | Adds the `__flow/route/{flow_id}/{partition_id}` layout. Review question on `partition_id` in `DropRequest` spawned #4268 [UPSTREAM] |
| #4268 "Add `partition_id` to CreateFlowRequest & DropFlowRequest" | closed "completed" 2025-05-06, 0 comments | Closed in a triage sweep: 12 old issues were closed that day, 4 of them (#3189, #4006, #4039, #4268) between 09:09 and 09:20 UTC. The pinned proto still lacks the field, so this was **not implemented** [UPSTREAM][SOURCE] |
| #4280 "store peer info in `TableFlowValue`" | merged 2024-07 | Keeps the mirror broadcast; lookup optimization only [UPSTREAM][EXECUTED diff] |
| #4256, #4226, #4254 | merged | Distributed flownode plumbing. No partition discussion [UPSTREAM] |
| #5315 "more than one flow workers" | merged | Worker threads **inside one flownode**, not partitions [UPSTREAM] |
| #6108 "flow update use proper update" | merged 2025-05 | Cache key becomes `(flow_id, partition_id)`; dedups mirror peers. Does not split rows [UPSTREAM][SOURCE] |
| #6291 "bulk support flow batch" | merged | Bulk dirty-window broadcast [SOURCE] |
| #7992 "expose flownode addrs in information_schema flows" | merged 2026-04 | PR text: "flownode_ids still represents `partition_id -> flownode_id`". Metadata-only meaning [UPSTREAM] |
| #8420 "Flow mirror inserts can be detached before the source-table insert reaches a commit boundary" | **open**, no PR | Confirms mirror delivery is fire-and-forget. Any task that changes mirror delivery guarantees is adjacent to this open issue [UPSTREAM] |
| Roadmaps #3412, #5446, #7685 | | No partitioned or distributed-flow item [UPSTREAM] |
| Searches: "flow partition", "multiple flownodes", "flownode partitions", "partition_id flow", "partition_id CreateFlowRequest", "flow load balancing", "flow scale out", "flow high availability" | | No implementing PR or issue [UPSTREAM] |
| Discussions ("flow partition", "flownode") | | The rendered result list did not appear filtered. No relevant thread seen. **PARTIAL / UNVERIFIED** |
| Olympus platform duplicate check | | **[PLATFORM] UNVERIFIED** |

RFCs:
- `docs/rfcs/2024-01-17-dataflow-framework.md:84-85,95`: "Greptime Flow can handle partitioning, if and only if the input query can be transformed to a fully partitioned plan according to the existing commutative rules. Otherwise the corresponding flow job has to be calculated in a single node. ... Greptime Flow has to see all the data belongs to one partition." Cross-partition merge is listed as future work. [SOURCE]
- `docs/rfcs/2025-09-08-laminar-flow.md:370`: "Phase 3 ... Load Balancing: Implement intelligent resource allocation for partitioned flow (Flow distributed executed on multiple flownodes)". Future work with no design. [SOURCE]

## 4. Current-HEAD proof of the gap

Reproduction: disposable integration test, archived at `scratchpad/c2/flow_partitions_repro.rs` and removed from the worktree. Run with `cargo test -p common-meta --features testing --test flow_partitions_repro`, shared target dir, 2 jobs. Result: 3 passed [EXECUTED].

- **A** (the gap):
  - Setup: an allocator that could hand out several flownodes, then a real `CreateFlowProcedure` run.
  - Output: `requested_partitions=[1] routes=1 flownode_ids={0: 1} create_sent_to={1}`
- **B** (already works):
  - Setup: run Prepare, rewrite the procedure's own dump JSON to 3 peers, then `from_json` and run to done.
  - Output: `routes=[(0,1),(1,2),(2,3)] flownode_ids={0:1,1:2,2:3} create_sent_to={1,2,3}`
- **C** (already works):
  - Setup: 3-partition metadata.
  - Output: `table_flownode_cache=[(4096,0,1),(4096,1,2),(4096,2,3)]` and `drop_sent_to={1,2,3} routes_left=0`

So the gap at HEAD is exactly two things:

1. A literal constant with no input that could make it anything other than 1.
2. A mirror path that broadcasts to every distinct peer.

The metadata, cache, drop, create fan-out, and OR REPLACE mapping preservation the draft prompt asks for **already exist**.

The mirror broadcast was not executed. The operator crate is too heavy for the shared machine (see section 6). It is proven by [SOURCE] at `insert.rs:1843-1868` and `bulk_insert.rs:373-414`.

## 5. Gating semantic question: what would "multiple flow partitions" mean?

### 5.1 What the repository encodes

- [SOURCE] A partition is a **metadata placement slot**: `partition_id -> flownode` in four key families and the cache. #7992 says the same thing explicitly [UPSTREAM].
- [SOURCE] A flownode has **no partition identity**:
  - `CreateRequest` is identical for every peer.
  - Recovery drops `partition_id`.
  - Engines and flow state are keyed by `FlowId`.
  - Two partitions on one flownode collapse into one task (`create_if_not_exists: true`, and mirror peer dedup).
- [SOURCE] The mirror data plane has **no flow addressing**. `InsertRequest` carries only `region_id` and rows, and the flownode fans rows out to *all* flows on that node that read the table. The frontend therefore cannot send different row subsets to different flows on the same node without a protocol change. greptime-proto is an external pinned crate (architecture invariant 1).
- [SOURCE] Current multi-peer behavior is **node-level broadcast** on both the row path (with the split TODO) and the bulk path (without a TODO).

### 5.2 Intended meaning

The TODO says "split", and the 2024 RFC describes partitioned consumption. That intent is conditional on a query-plan analysis ("fully partitioned plan according to commutative rules") that does not exist. It was written for the old stateful dataflow engine, which was since replaced by stateless streaming plus batching. The 2025 RFC defers "partitioned flow" to an undesigned Phase 3. [SOURCE][INFERENCE]

### 5.3 Why partitioned consumption cannot be stated fairly

A solver would have to invent all of the following:

- (a) The **partition-count input**. There is no SQL, option, or config for it. The draft prompt forbids new SQL, and `validate_flow_options` rejects unknown options.
- (b) The **row-to-partition rule**: hash, source region, time window, or round-robin.
- (c) How a flownode **learns its partition**. That needs either a proto field (#4268, never done) or a transient `flow_options` key; `INTERNAL_EVAL_SCHEDULE_KEY` is a precedent for such a key, but choosing it is still an invention.
- (d) **Per-flow addressing** on the mirror plane.
- (e) **Batching-mode semantics**. Batching uses mirrored rows only as dirty-window hints and re-queries the whole source table per window (`batching_mode/task.rs`). Splitting rows by anything other than time window lets two partitions recompute the same window concurrently and race on the sink. Incremental-read checkpoints are per-instance region watermarks (`checkpoint.rs`).
- (f) **Repartition** interaction, if the rule is region-based.

Hidden tests would have to encode those choices, which breaks the handoff's fairness rule (PROMPT-STATED or REPO-DISCOVERABLE only).

### 5.4 Why broadcast replication is not a fallback

Replicating a flow to N flownodes would duplicate sink writes: N identical streaming outputs, or N concurrent batching recomputations that could overwrite newer window results with stale ones. It also contradicts the "split" TODO and the RFC. Nothing in the repo (no leader or fencing among flow replicas) supports it as a feature. [INFERENCE from SOURCE]

### 5.5 Other conflicts with the draft prompt

- "Fail or retry according to the existing Flow error model rather than silently omitting that partition": the existing mirror model *is* detached and log-only (#8420 is open on exactly that boundary). Tests would be requiring a new delivery guarantee.
- "Creation, lookup, cache refresh, recovery and drop must preserve the complete mapping": already true (4.B, 4.C). An F2P test on those points would pass on the clean base.

Conclusion: the architecture only defines metadata placement and node-level broadcast. Per the handoff's instruction, this candidate must be rewritten or rejected. No rewrite that avoids invention keeps enough depth (section 7).

## 6. Minimal deterministic reproduction

Done for the common-meta layer (section 4, [EXECUTED]).

The operator mirror path was not executed. `cargo test -p operator` would compile query, catalog, partition, DataFusion, and more from a cold cache on a shared 4-CPU / 2-job budget. The TODO line and the loop at `insert.rs:1860-1867` already prove the broadcast unambiguously, so running it would add no discriminating evidence.

Build hygiene:
- `df` showed at least 19 GB free.
- No lib sources were modified. The integration-test target was built with `--features testing` as a separate unit.
- I confirmed first, read-only, that the lead's `src/common/meta`, `src/common/procedure-test` and `Cargo.lock` are byte-identical to mine, so shared artifacts could not mix code.

## 7. Proposed frozen scope

**Not frozen: REJECT.**

For the record, any future freeze would first need maintainer-defined answers to 5.3 (a) through (f).

Reformulations I tried and discarded:

| Reformulation | Why discarded |
|---|---|
| "Honor a partition count" | Needs an invented input |
| "Region-affine routing for streaming flows only" | Invented rule plus repartition interplay |
| "Replicate flows for HA" | Unsound sink semantics (5.4) |
| "Dedup peers for co-located partitions" | Already done in #6108 |
| "Bulk path parity with the row path" | Both already broadcast |
| "Sum affected_rows in FLUSH FLOW across partitions" | Real but tiny, and unreachable with 1 partition |

No draft task prompt is offered.

## 8. Estimated size (hypothetical, if a maintainer defined the semantics)

Roughly 6 to 10 production files across `common-meta` (option/allocation/transient partition identity), `operator` (per-flow split in `FlowMirrorTask` and bulk dirty windows), `flow` (partition-aware recovery, filtering, batching window ownership), and possibly `greptime-proto`. That is about 400 to 700 effective LOC. The difficulty would come from design invention, not from repository reasoning.

## 9. Test architecture (for reference only)

- **BASE:**
  - common-meta: `ddl::tests::create_flow`, `ddl::tests::drop_flow`, `cache::flow::table_flownode`, `key::flow::*`
  - operator: `insert::tests` (mirror cases)
  - flow: `adapter::flownode_impl`
- **NEW:**
  - A common-meta integration test with `MockFlownodeManager`, a recording `PeerAllocator` and `MemoryKvBackend` (the pattern in section 4).
  - An operator `FlowMirrorTask` test with `new_table_flownode_set_cache` and a recording `NodeManager`.
- **Fairness:** assertions on the row-to-partition assignment cannot be made fair under current repo semantics. That alone blocks Test Quality.

## 10. Contamination / originality verdict

**REJECT - REPO MISFIT.**

- Provenance: no implementing PR, branch, or issue exists; the unresolved #4268 was closed in a triage sweep without implementation. This would otherwise have been a CONDITIONAL PASS on originality.
- Rejection reason: the semantic contract is undefined, parts of the proposed scope are already implemented, and the remainder needs an invented sharding rule and input surface.
- No overlap with sealed challenge A (repartition staging) or challenge B (append-mode deletes).
- Mild adjacency: the DROP FLOW fan-out overlaps Candidate 3's area, and the mirror-delivery semantics are adjacent to open issue #8420.
- [PLATFORM] duplicate check: UNVERIFIED.

## Commands that produced [EXECUTED] evidence

All git commands ran from the worktree. Scratch files are under `scratchpad/c2/`.

1. `git rev-parse HEAD`, then `git status --short`, then `df -h /`
2. `git blame -L 20,30 src/common/meta/src/ddl/create_flow/metadata.rs`; `git blame -L 1855,1872 src/operator/src/insert.rs`; `git blame -L 1815,1830 src/operator/src/insert.rs`
3. `git log -S"We don't support the partitions" --all -- src/`; `git log -S'need to split requests to multiple flownodes' --all`
4. `git log -S'FlowIdent' origin/main -- src/common/meta/src/cache/flow/table_flownode.rs`; `git log -S'dedup peers' origin/main -- src/operator/src/insert.rs`; `git log -S'fn maybe_update_flow_dirty_window' origin/main -- src/operator/src/bulk_insert.rs`
5. `git for-each-ref --format='%(refname)' refs/upstream-pr refs/upstream-heads > refs.txt` (7287 refs); `git cat-file --batch-check < q_<file>.txt` and `git cat-file --batch < ub_<file>.txt` for metadata.rs, create_flow.rs, flow_meta.rs, insert.rs, table_flownode.rs, bulk_insert.rs, flownode_impl.rs; `python3 analyze.py <mode>`
6. `git log -G'let partitions|split requests to multiple flownodes|flow_metadata_allocator\s*\.create|\.create\(partitions\)' --stdin -- src/common/meta src/operator src/meta-srv src/flow < revs.txt` (revs = all refs plus `^origin/main`)
7. `git log -G'partition_id|FlowPartitionId|flow_partition|FlowIdent' --stdin -- src/flow src/operator src/common/meta/src/cache/flow src/common/meta/src/ddl/create_flow.rs src/common/meta/src/ddl/create_flow < revs.txt`
8. `git log -i -E --grep='flow.*partition|partition.*flow|multi(ple)?[ -]flownode|...' --all`
9. `git show 6c590cfb49 -- ...flow_meta...` (PR #4179); `git show baa23aa6ad -- ...` (PR #4280); `git show --stat 9a230eaab0` (#4263); `git for-each-ref --contains <sha>` for 6c590cfb49, f6aa6adda6, 78211e4721, 10046fb9ed, c4d55cbdea
10. `diff -rq` of the lead's vs my `src/common/meta`, `src/common/procedure-test`, `Cargo.lock` (read-only)
11. `CARGO_TARGET_DIR=/home/user/greptimedb-target CARGO_BUILD_JOBS=2 cargo test -p common-meta --features testing --test flow_partitions_repro -- --nocapture --test-threads=1` gave 3 passed, EXIT=0 (log at `scratchpad/c2/repro_run.log`)

[UPSTREAM] evidence came from WebFetch of the GitHub search API and PR/issue pages: #4179, #4256, #4263, #4268, #4280, #5315, #6108, #6920, #7060, #7992, #8420, #5446, #7685, the `closed:2025-05-06` sweep, and the discussions pages.
