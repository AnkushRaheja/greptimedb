# Upstream Contamination Audit: Support batch DDL drop for Metric Engine logical tables

Pinned commit: `2b596fd52df31dcad779794877a296de7746f736` (upstream `GreptimeTeam/greptimedb` main tip, verified with `git ls-remote` on 2026-09-28).

Evidence labels: [EXECUTED] command run in this session, [UPSTREAM] GitHub/upstream-git evidence, [SOURCE] repository source, [PLATFORM] Olympus evidence.

## Verdict

**ORIGINALITY PASS.** [PLATFORM] The Olympus duplicate/similarity check is **UNVERIFIED**; it cannot be reached from this environment.

## Method

GitHub API tools could not attach upstream in this session because the fork has the same repo name. The audit therefore used anonymous git over the full upstream ref set plus the public GitHub REST and web search.

1. [EXECUTED] Unshallowed history: 6231 commits on main.
2. [EXECUTED][UPSTREAM] Fetched **all 7050 upstream PR heads** (`refs/pull/*/head`: open, closed, merged and draft) and all 237 upstream branches.
3. [EXECUTED] `git log -S` and `-G` for `DropLogicalTables`, `DropTableTasks`, `drop_logical_tables`, `DropLogicalTablesProcedure`, `DropLogicalTablesData` and `drop_logical_table`, over main and over every PR/branch ref (excluding main).
4. [EXECUTED] **Blob check at every ref tip.**
   - 5623 tips contain `src/common/meta/src/ddl_manager.rs`, giving 117 distinct blobs.
   - 87 of those mention `DropLogicalTables`, and **all 87 contain `DropLogicalTables(_) => todo!()`**.
   - So no PR ever replaced the arm. This check is needed because `-S` cannot see a same-count replacement.
5. [UPSTREAM] GitHub search (issues and PRs, all states):
   - `DropLogicalTables`: 0 results. `DropTableTasks`: 0 results.
   - `"drop logical tables"`: 9 results, all soft-drop/lifecycle PRs or unrelated.
   - `"batch drop"` and `drop table logical batch`: nothing relevant.
   - `"drop multiple tables"`: #4020 and #4085.
   - Discussions search: nothing relevant.
6. [EXECUTED] Commit-message grep for the same terms: no hits.

## Findings

- [EXECUTED] The variant, the proto mapping, and the `todo!()` arm were introduced together in `1fab7ab75` ("feat: batch create ddl", #3194, 2024-01-26). Every later commit that touches the line only reflows the dispatch match: #3541, #3807, #3810, #3900, #5035, #6625, #7060. The current blame is #6625, a refactor that kept `todo!()`.
- [UPSTREAM] The #3194 review thread never discusses batch drop: no plan, TODO, or decision not to implement it.
- [UPSTREAM] **PR #4085 is related but not equivalent.**
  - It added generic SQL multiple-table `DROP TABLE` by invoking ordinary single-table drop operations one after another.
  - It explicitly left the gRPC path unsupported: its description says it supports SQL requests but is not ready for gRPC.
  - This task targets the pre-existing `DropTableTasks` / `DropLogicalTables` Metric Engine logical-table DDL path. That path still panics at the pinned commit and needs batch-safe logical-table semantics: the whole batch validated up front, one shared physical table, and recovery of the whole batch.
  - #4085 touched only operator/sql/sqlness (`98c19ed0fa`) and never common-meta.
- [UPSTREAM] Soft-drop PRs #8061, #8458 and #8554 deliberately keep metric logical **soft-drop/undrop/purge** unsupported (rejected seed R4). This task is a **hard** drop, which single-table drop already performs for logical tables (soft drop falls back to hard drop). No maintainer decision against batch hard drop exists.
- [UPSTREAM] #7691 (unmerged node-manager refactor): its ref keeps the `todo!()`.
- [SOURCE] `docs/style-guide.md:21` reserves `unimplemented!()` for "things that aren't likely to be implemented". The arm uses `todo!()`, which signals intent to implement.
- No overlap with the sealed repartition-staging challenge, or with the append-mode delete-visibility challenge.

## Hard-stop checklist

| Condition | Status |
|---|---|
| Substantially equivalent PR (any state) | None |
| Upstream fix landed | No (pin is the current tip, still `todo!()`) |
| Closed/unmerged PR with the solution | None (blob check) |
| Maintainer declined | No |
| Current source implements it | No |
| Old commit used to resurrect a fix | No |
| Overlap with existing challenges | No |
