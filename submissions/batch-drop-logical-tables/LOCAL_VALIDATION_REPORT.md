# Local Validation Report: Support batch DDL drop for Metric Engine logical tables

**Environment**
- Pinned commit `2b596fd52df31dcad779794877a296de7746f736`.
- Rust 1.96.1 (from `rust-toolchain.toml`), cargo-nextest 0.9.146, protoc 3.21.12.
- Debug `test` profile, shared `CARGO_TARGET_DIR`, 4 CPUs.

All subjects were run in the same checkout, one after another. Between subjects the checkout was reset to the pinned commit and verified clean (`git status --porcelain` empty), and the patches were applied with `git apply`.

**Runner**: `./test.sh <base|new> <junit>`.
- BASE: every existing `common-meta` lib unit test, i.e. 602 tests, excluding the new module.
- NEW: the 8 tests in `ddl::tests::batch_drop_logical_tables`.

## Validation matrix

| Subject | BASE | NEW |
|---|---|---|
| A: clean base + `test.patch` | **602/602 pass** (exit 0) | **0/8 pass**, 8 fail (exit 100) |
| B: clean base + `test.patch` + `solution.patch` | **602/602 pass** (exit 0) | **8/8 pass** (exit 0) |

**Subject A failure reason.**
- All 8 NEW tests fail with `panicked at src/common/meta/src/ddl_manager.rs:1004:41: not yet implemented`, which is the gap itself.
- The recovery test reports it as `the batch finished before any region is dropped: Err(JoinError::Panic(..))`.
- There were no build, discovery, or harness failures.
- The JUnit report came from the real run (8 tests, 8 failures), not from the fallback.

**Patch application**
- `git apply --check` succeeds on a pristine checkout in both orders: solution then test, and test then solution.
- `test.sh` is added with mode 100755.

## Static checks (reference solution + tests)

- `cargo fmt -p common-meta -- --check`: clean. Stable rustfmt warns about two nightly-only options; those warnings are pre-existing and unrelated.
- `cargo clippy -p common-meta --all-targets -- -D warnings`: clean.
- `cargo clippy -p common-meta --all-targets --features enterprise -- -D warnings`: clean.
- The full `common-meta` lib suite with the reference solution passes 610/610: 602 existing + 8 new.
- Not run locally, because of disk (about 4.6 GB free on a shared 38 GB allowance):
  - the enterprise-feature test binary;
  - the `pg_kvbackend`/`mysql_kvbackend` feature builds;
  - `make test` (the full workspace);
  - a local `docker build` of the Dockerfile.

## Mutation checks

Each mutant was applied to the reference solution in the working tree, compiled, and run under
`./test.sh new`. A mutant is killed when at least one NEW test fails. Afterwards the tree was
restored from `solution.patch` and verified byte-identical: the SHA-256 of the regenerated diffs
equals both frozen patches.

| Mutant | Incomplete implementation | Result | Killing tests |
|---|---|---|---|
| m01 | no same-physical-table check | killed (7/8 pass) | rejects_different_physical_tables |
| m02 | missing targets always skipped | killed (7/8) | rejects_absent_table |
| m03 | non-logical targets silently skipped | killed (7/8) | rejects_non_logical_tables |
| m04 | procedure loader not registered | killed (7/8) | recovers_after_restart |
| m05 | no cache invalidation | killed (4/8) | invalidates_caches, recovers_after_restart, skips_absent_table_if_exists, with_duplicate_targets |
| m06 | physical regions registered per target (reusing single-drop logic) | killed (0/8) | all (`RegionOperatingRace` on the second target) |
| m07 | handler loops ordinary single-table drop procedures | killed (4/8) | recovers_after_restart, rejects_absent_table, rejects_different_physical_tables, rejects_non_logical_tables |
| m08 | state not persisted between steps (in-memory only) | killed (7/8) | recovers_after_restart |
| m09 | drops the physical table's regions | killed (1/8) | 7 tests |
| m10 | drops regions of the first target only | killed (1/8) | 7 tests |
| m11 | mutates metadata before validating | killed (0/8) | all |
| m12 | no deduplication of duplicate targets | **survives (8/8)**, as intended | the contract requires only that duplicates are safe, not a particular deduplication strategy |

11 of the 11 disallowed mutants are killed. Artifacts: `mutants.py` and `run_mutants.sh` (scratchpad).

## Flakiness (retries disabled everywhere)

| Run | Result |
|---|---|
| NEW via `./test.sh new`, nextest one process per test | **10/10** runs, 8/8 each |
| Recovery test alone, `--exact` | **20/20** |
| All 8 NEW tests in one process with 8 threads (contention stress) | **20/20** |
| BASE via `./test.sh base` | **3/3** runs, 602/602 each |

No outcome variance was observed. Synchronization is by channel only: the first destructive region request is held until the manager stops, with no sleeps. Timeouts (60 s) are stall detectors only.

## Local quality audits

**Test Quality**: unfairTestCount = 0.
- Every assertion maps to a prompt sentence; see `REQUIREMENT_TEST_MATRIX.md`.
- Assertions cover only public DDL / procedure-manager / metadata behaviour and two repo-precedented test doubles.
- The tests do not assert:
  - procedure type or state names, data layout, or lock keys;
  - transactions, or the metadata KV store as a whole;
  - error text, or error codes other than table-not-found (whose expected value is measured from a single-table drop);
  - exact request counts, or a deduplication strategy.
- Alternative valid designs stay green: batched `Drops` requests, per-table requests, re-sent drops after recovery, sub-procedures, validation in the handler or the procedure, and invalidation before or after region drops.
- Residual alternate-implementation risk: a design that invalidates caches under different identifiers than `TableId`/`TableName` would fail R6. The prompt names both, and single-table drop uses exactly those.

**Solution Quality**
- It follows the batch create/alter logical-table precedent: validation first, locks fixed at submission, and loader registration.
- It reuses the single-drop executor for region drops, and adds tombstone helpers next to the single-table ones.
- There is no rollback, the same as single logical drop.
- No test-only hooks, no unrelated cleanup, and no change to single-table drop.
- fmt and clippy are clean on default and `enterprise` features.

**Description Quality**
- 199 words, plain ASCII, no URLs, file paths, test names or internal type names.
- `drop_if_exists` is the public task field.
- Category is `feature_request`, because it implements an existing but unimplemented DDL task.
