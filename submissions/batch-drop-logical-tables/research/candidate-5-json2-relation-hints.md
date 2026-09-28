# Candidate 5: Relation-Aware JSON2 Type-Hint Concretization Across Joins

Research-phase report (handoff sec 23 items 1-10). No reference solution, test.patch, solution.patch or Dockerfile was written.

## Verdict

**REJECT: the gap cannot be observed through any supported surface at HEAD.** Originality label: **CONDITIONAL PASS** (no implementing PR exists; the Olympus platform-duplicate check is UNVERIFIED).

The FIXME is real, but only as a latent, rule-level quirk. In every production query path (standalone and distributed frontends both run the dist planner), each JSON2 table scan reaches `JsonTypeConcretizeRule` in its own single-table remote plan. The name-keyed map therefore never mixes relations. Joined JSON2 columns do fall back to Variant, but the cause is the MergeScan/join boundary. The whole root has to cross the boundary, and a relation-aware hint fix would not change that. No fair F2P test is possible on query results, EXPLAIN output or scan hints produced by a real query.

## Stage A: base

- [EXECUTED] `git rev-parse HEAD` = `2b596fd52df31dcad779794877a296de7746f736`. `git status --short` is clean (checked before editing and again after reverting the disposable probe).
- [UPSTREAM] Repo gate (github.com page via WebFetch): about 6.7k stars, Apache-2.0 core (enterprise features under a separate license), Rust, actively maintained. The base commit is dated 2026-09-27.

## 1. Source-path map (all [SOURCE] at HEAD)

| Concern | Location |
| --- | --- |
| Rule | `src/query/src/optimizer/json_type_concretize.rs` L37-69 (`JsonTypeConcretizeRule::rewrite`: `deduce_json_types(&plan)`, then `transform_down` over `TableScan`s) |
| FIXME | same file L71-73 (added in commit 46b993bfb0, "fix(query): note JSON2 hint scope limitation", squashed into #8833) |
| Provider application | same file L77-108 `apply_json_type_hint`: filters the global map to the provider's JSON2 field names, then `DummyTableProvider::with_json_type_hint` (`src/query/src/dummy_catalog.rs` L286-288) or `DfTableProviderAdapter::with_json_type_hint` (`src/table/src/table/adapter.rs` L64-66) |
| Hint collection | same file L110-144 `deduce_json_types` (whole plan, `HashMap<String, JsonNativeType>` keyed by `Column.name`, qualifier discarded), L146-154 `is_same_name_column_projection`, L156-216 `deduce_json_type` |
| Merge semantics | `src/datatypes/src/types/json_type.rs` L88-121 `JsonNativeType::merge`: objects union, conflicts become `Variant`, `Null` yields to the other side |
| Cast folding | `src/common/function/src/scalars/json/json_get_rewriter.rs` (`json_get(..)::T` becomes `json_get(.., T)`) |
| MergeScan boundary | `src/query/src/optimizer/json_schema_concretize.rs` L60-108 (`deduce_json_types(merge_scan.input())` per MergeScan) and L110-159 `concretize_json2_schema` (also name-keyed, but applied to one remote input at a time) |
| Rule registration | `src/query/src/query_engine/state.rs` L211-214 (analyzer: `DistPlannerAnalyzer` + `JsonSchemaConcretizeRule`, only when `with_dist_planner`) and L226-227 (optimizer: `ScanHintRule`, `JsonTypeConcretizeRule`, always) |
| Dist planning | `src/query/src/dist_plan/analyzer.rs` L996-1047 (`f_up` wraps each TableScan-rooted subtree) and L746-800 (`expand`, MergeScan creation); `src/query/src/dist_plan/commutativity.rs` L169 `Join => NonCommutative`, L174 `Union => Unimplemented` |
| MergeScan hides its input | `src/query/src/dist_plan/merge_scan.rs` L390-392 `inputs() -> vec![]`, L399-401 `expressions() -> vec![]` |
| Remote/local execution | `src/query/src/dist_plan/planner.rs` L170-235 (the MergeScanExec input plan goes to regions; the fallback optimizes that single input locally, L446-463) |
| Engines | frontend `src/frontend/src/instance/builder.rs` L294-303 (`with_dist_planner = true`), used by standalone too (`src/cmd/src/standalone.rs` L675); datanode `src/datanode/src/datanode.rs` L452-462 (`false`, `DummyCatalogManager`, region-scoped plans); flownode `src/flow/src/server.rs` L320 (`false`, plan translation only) |
| Storage consumer | `ScanRequest.json_type_hint` in `src/store-api/src/storage/requests.rs` L93 (Display L194-203; this text does not appear in any sqlness EXPLAIN result); `src/mito2/src/read/scan_region.rs` L713-757 `build_read_columns` (an unhinted JSON2 column reads as Variant; a hint on a non-JSON2 column is rejected); `src/mito2/src/sst/parquet/json_align.rs` L216-246 then `src/datatypes/src/vectors/json/array.rs` L227-271 `project_to` (lossy: missing fields become null, incompatible values become NULL) |
| SQLness | `tests/cases/standalone/common/types/json/json2_join.sql` L29 ("Conflicting hints ... preserve both values as Variant") plus `.result`; `tests/cases/distributed/common` is a symlink to the same file |
| Existing split-join evidence | `src/query/src/dist_plan/analyzer/test.rs` L2452 `test_join_side_local_filter_pushdown_into_merge_scan` (one MergeScan per join side) |

## 2. Git-history search

- [EXECUTED] `git log -S'keyed only by unqualified' origin/main -- src/query` returns only 6538db6d61 (#8833).
- [EXECUTED] `git blame` on L71-108: FIXME and `apply_json_type_hint` come from 6538db6d61 (#8833, fys, 2026-08-14); the downcasts were touched by 94d7e2c7fc (DF55 upgrade, #8555); `deduce_json_types` is from #8081, #8940 and #9016.
- [EXECUTED] `git log -G'json_types|FIXME|originating relation' origin/main -- src/query/src/optimizer/` returns #8081, #8833, #8940 and #9016. None changes the keying.
- [EXECUTED] File history for `json_type_concretize.rs` and `json_schema_concretize.rs`: #8081, #8661, #8683, #8745, #8833, #8940, #8979, #9013, #9016, #8555, #9192, #9222. None implements relation scoping.
- [EXECUTED] Unmerged-commit search: `git log --all --not origin/main -G'json_type_hint|json_types|JsonTypeConcretize|deduce_json_type'` and `-G'originating|relation-aware|per-scan|qualified.*json|json.*qualif' -- src/query`. The hits are pre-squash commits of #8833, #8940, #9013, #9016 and #9222, backports on release branches, and open #9349. None scopes hints per relation.

## 3. Upstream search (all PR heads and all states)

- [EXECUTED] Blob comparison of `json_type_concretize.rs` across all 7050+ `refs/upstream-pr/*` and `refs/upstream-heads/*` tips found 15 distinct blobs. Every blob that postdates the FIXME still carries it verbatim. The only blobs without it predate #8833 (PRs 8399, 8521, 8646-8756). No blob contains relation or qualifier logic beyond `Column::new_unqualified` in tests and PR 8944's `qualified_field(idx)` call, which reads the schema, not the relation.
- [EXECUTED] The same comparison for `json_schema_concretize.rs` gives one blob across all refs. For `json2_join.sql` there are two blobs, before and after #9016. No PR changes the join expectations.
- [UPSTREAM] #8833 description: "JSON2 hints are still matched by unqualified column name, so same-name JSON2 columns in joins can still be ambiguous." This is a known limitation, not a maintainer rejection.
- [UPSTREAM] #8940 added `json2_join.sql` ("both sides' values are preserved under conflicting hints"). #9016 added the join/MergeScan boundary schema coverage and is behaviour-preserving.
- [UPSTREAM] #8944 (closed; "collect root-aware JSON type hints"): root-read Variant upgrade only, still name-keyed.
- [UPSTREAM] #9222 (merged; "respect type hints during JSON2 type concretization"): declared type hints in planning, not relation scoping.
- [UPSTREAM] #9349 (OPEN; "json_get respect type hints"): resolves declared hints through qualified column lookup (`schema.field_from_column`, JOIN USING, outer references) in `json_expr_planner.rs`. This is conceptual adjacency only. It does not scope scan hints and does not touch `json_type_concretize.rs`.
- [UPSTREAM] #9316 (merged): restricts the allowed hint types. Unrelated.
- [UPSTREAM] Issue and PR searches for "json2 join", "json2 hint", "json_type_hint", "concretize" and "same-named OR unqualified column OR originating relation" found no issue or PR implementing relation-aware hint scoping. The discussions search returned only unrelated threads (the query filter did not appear to apply).
- [UPSTREAM] Limits: the GitHub REST API returned 403 in this session (repo not attached), so review-comment threads could not be read. github.com web pages and search via WebFetch worked.
- [PLATFORM] Olympus duplicate check: UNVERIFIED.

## 4. Current-HEAD proof

Reproduced with a disposable unit probe in the `query` crate. The probe was reverted afterwards; the diff is saved at `candidates/candidate-5-disposable-probe.diff` and the output at `candidates/candidate-5-probe-output.log`.

[EXECUTED] Synthetic plan: both JSON2 scans are visible to one rule invocation (two `DummyTableProvider`s, `l JOIN r ON ts`, then `JsonTypeConcretizeRule`). This confirms the FIXME mechanism.

| Case | l hint | r hint |
| --- | --- | --- |
| l.a:Int64, r.a:String (conflict) | `{a: Variant}` | `{a: Variant}` |
| l.a:Int64, r.b:Bool (disjoint) | `{a: I64, b: Bool}` | `{a: I64, b: Bool}` |
| only l.a:Int64 (one-sided) | `{a: I64}` | `{a: I64}` (r never asked for it) |
| l.j whole, r.a:Int64 | `Variant` | `Variant` |
| single-table baseline | `{a: I64}` | (none) |

[EXECUTED] Production-shaped path: the same joins with two Base `DfTableProviderAdapter` tables go through `DistPlannerAnalyzer` and `JsonSchemaConcretizeRule`, as the frontend does. Then the frontend `JsonTypeConcretizeRule` runs, and finally the rule is re-run on each MergeScan remote input, as the datanode does.

- The frontend plan is `Projection(json_get..) -> Join -> [MergeScan(TableScan l), MergeScan(TableScan r)]`.
- The frontend rule's `transformed` is false, and both adapters have empty hints. The rule cannot see the scans.
- Each remote input has exactly 1 TableScan. The MergeScan output schema is `(k, ts, j: Binary)`. `deduce_json_types(remote)` gives `{j: Variant}` on both sides, in both the conflict and the disjoint case.
- Single table: the remote input is `Projection(json_get(l.j,'a',Int64)) -> TableScan l`. The output is `la: Int64` and the hint is `{j: {a: I64}}`.

## 5. Classification of the observable effect

- **Wrong results: NO.** [SOURCE + EXECUTED] `merge` only widens (union of paths; conflicts become Variant), and `project_to` coerces only paths the scan's own expressions do not consume. Even the synthetic contamination is value-preserving. The sqlness `json2_join` output is correct (`right`, `1`).
- **Invalid casts or errors: NO.** [SOURCE] `apply_json_type_hint` filters hints to JSON2 fields of each provider, so mito's non-JSON2 hint rejection is never triggered.
- **Lost native concretization: YES in joins, but not caused by the FIXME.** [EXECUTED] The join is NonCommutative, so the `json_get` projection stays on the frontend above the join and each side must ship the whole root as Variant. A relation-aware map changes nothing here.
- **Performance-only: only on a synthetic plan shape** (extra paths read, or forced Variant) that no production engine builds today. [SOURCE + EXECUTED] The frontend hides scans in MergeScan, the datanode receives single-region plans, and the flownode only translates plans.
- Supported surfaces:
  - Query results: identical.
  - EXPLAIN: `json_type_hint` is never rendered in the sqlness EXPLAIN outputs (no `.result` contains it) [SOURCE].
  - Scan-request hints through normal hooks: the only difference appears at rule level on synthetic plans.

Side note [INFERENCE + EXECUTED]: the json2_join.sql L29 comment attributes the Variant outcome to "conflicting hints". The executed emulation shows the Variant comes from the boundary transfer.

## 6. Category

There is no viable category. If this were forced, it would be `refactor` (latent correctness hygiene with no user-observable change). `bugfix` is not supported (nothing wrong or failing is reproducible). `feature_request` is not supported (nothing a user gains).

## 7. Frozen scope / draft prompt

Not produced: the candidate does not survive. A prompt stating "hints must not cross relations" would describe only internal rule behaviour on plan shapes the product never builds.

Possible separate seed, flagged for the lead at [INFERENCE] level and not audited: JSON2 path reads above non-commutative nodes (joins) force whole-root Variant transfer and full Variant scans, while the single-table query concretizes natively. Pushing per-side `json_get` path extraction below the join into each MergeScan would be a perf `feature_request`. Its observability is still weak (results are identical; only plan shape and scan cost change), and it is a different candidate needing its own provenance audit.

## 8. Estimated size of a relation-aware fix

About 1-2 production files (`json_type_concretize.rs`, possibly a small helper in `json_schema_concretize.rs` or `dist_plan`), roughly 100-180 effective LOC: per-TableScan deduction that tracks qualifiers through `SubqueryAlias` and aliasing projections. This is below the long-horizon target (>= 200 LOC, multi-file).

## 9. Test architecture (why no fair F2P exists)

- BASE: the existing unit tests in `json_type_concretize.rs` and `json_schema_concretize.rs`, the `dist_plan/analyzer/test.rs` join tests, and `json2_join` / `json2_query_respect_type_hint` sqlness.
- NEW: the only discriminating tests would be in-crate unit tests. `JsonTypeConcretizeRule` and `deduce_json_types` are `pub(crate)`, so these tests would have to live in the same file the solution edits, which risks patch collisions. They would build synthetic multi-scan plans and assert exact `scan_request().json_type_hint` maps. That is precisely the internal hint-map assertion to avoid, and on a plan shape unreachable from SQL.
- The expected values are also not unique. In the one-sided case "no hint" and an explicit `Variant` are storage-equivalent (`build_read_columns` defaults to Variant), and alias/subquery lineage is implementation-defined. A valid alternate implementation could fail such tests (hard stop, sec 22).
- Query-result tests (sqlness or integration) pass on both base and fix, so they cannot discriminate.

## 10. Contamination verdict

**CONDITIONAL PASS.** No upstream PR in any state implements relation-scoped JSON2 hint deduction. The limitation is acknowledged in #8833 and not declined. The Olympus platform duplicate check is UNVERIFIED, and review-comment threads were not readable because the API returned 403.

The candidate is nonetheless **REJECTED on observability** (sec 22: "the bug cannot be reproduced", "fair deterministic tests cannot be written"). No overlap with the two occupied challenges.

## Commands that produced [EXECUTED] evidence

- `git rev-parse HEAD`; `git status --short`
- `git log -S'keyed only by unqualified' ...`; `git log -G'json_types|FIXME|originating relation' ...`; `git blame -L 60,125 src/query/src/optimizer/json_type_concretize.rs`; `git log --format=... -- <json files>`
- `git log --all --not origin/main -G'json_type_hint|json_types|JsonTypeConcretize|deduce_json_type' -- src/query src/table src/store-api` and `-G'originating|relation-aware|per-scan|...' -- src/query`
- `git for-each-ref --format='%(refname):<path>' refs/upstream-pr refs/upstream-heads` piped into `git cat-file --batch-check` / `--batch` for `json_type_concretize.rs`, `json_schema_concretize.rs` and `json2_join.sql` (blob dedupe and grep)
- `git for-each-ref --contains <sha>` for ecaa547e94, b4aad5d59d, 5c84de3f10, 46b993bfb0 and 6600031b48; `git merge-base` / `git diff` for refs/upstream-pr/8944 and 9349; `git show 46b993bfb0`, `git show e82cb0af74`
- `CARGO_TARGET_DIR=/home/user/greptimedb-target CARGO_BUILD_JOBS=2 cargo test -p query --lib c5_probe -- --nocapture`: 2 disposable tests passed (16m24s build). The probe was reverted with `git checkout -- <2 files>`, and the worktree is clean at the base commit.
