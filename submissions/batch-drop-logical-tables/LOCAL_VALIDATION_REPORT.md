# Local Validation Report: Support batch DDL drop for Metric Engine logical tables

Revision 2. This revision fixes submission-layer defects only:
- the `test.sh` interface;
- the Dockerfile base image and build steps;
- two prompt wording edits;
- the canonical `Dockerfile` file name.

The Rust solution and the eight tests are unchanged:
- `solution.patch` has the same SHA-256 as revision 1 (`03d2aa5d…`).
- In the new `test.patch`, the hunks for `src/common/meta/src/ddl/tests.rs` and `src/common/meta/src/ddl/tests/batch_drop_logical_tables.rs` are byte-identical to revision 1. Only the `test.sh` hunk changed.

**Environment**
- Pinned commit `2b596fd52df31dcad779794877a296de7746f736`.
- Rust 1.96.1 (from `rust-toolchain.toml`), cargo-nextest 0.9.146, protoc 3.21.12.
- Debug `test` profile, 4 CPUs.

## Runner interface

```
./test.sh --output_path <junit-xml-path> base
./test.sh --output_path <junit-xml-path> new
```

**Modes**
- `base`: every existing `common-meta` lib unit test (602 tests; the new module is excluded).
- `new`: the 8 tests in `ddl::tests::batch_drop_logical_tables`.

**Output path**
- `--output_path` is parsed as an option (`--output_path=<path>` also works), and the JUnit report is written to exactly that path.
- A relative path is resolved against the caller's working directory.
- There is no positional-path or environment-variable fallback.

**Run behaviour**
- Retries are disabled (profile `retries = 0` and `--retries 0`), with no fail-fast (profile `fail-fast = false` and `--no-fail-fast`).
- Real nextest JUnit is copied to the output path. A diagnostic fallback report is written only if the build, discovery or run produced no report.
- The exit code is nextest's: 0 means pass, 100 means test failures.

**CLI checks [EXECUTED]**
- `bash -n test.sh` passes.
- These invocations all exit 2 and create no output file:
  - `./test.sh`
  - `base`, `new`
  - `--output_path`
  - `--output_path /tmp/x.xml`
  - `--output_path /tmp/x.xml foo`
  - `--output_path /tmp/x.xml base new`
  - the old positional forms `/tmp/x.xml base` and `base /tmp/x.xml`
  - `--output /tmp/x.xml base`
- A relative `--output_path results.xml` works from the repo root and from another directory.

## Four-state matrix [EXECUTED]

Commands used, exactly:
- `./test.sh --output_path /tmp/base.xml base`
- `./test.sh --output_path /tmp/new.xml new`

The checkout was verified clean before each subject.

| Subject | BASE | NEW |
|---|---|---|
| A: clean base + `test.patch` | **602/602 pass** (exit 0) | **0/8 pass**, 8 fail (exit 100) |
| B: clean base + `test.patch` + `solution.patch` | **602/602 pass** (exit 0) | **8/8 pass** (exit 0) |

**JUnit reconciliation (`validation/reconcile_junit.py` against nextest's own `Summary` line)**

| Report | testcases | failures | nextest summary | fallback used |
|---|---|---|---|---|
| A base | 602 | 0 | 602 run, 602 passed | no |
| A new | 8 | 8 | 8 run, 0 passed, 8 failed | no |
| B base | 602 | 0 | 602 run, 602 passed | no |
| B new | 8 | 0 | 8 run, 8 passed | no |

All four reconcile, and the XML files are in `validation/junit/`.

**Subject A failure causes (from the JUnit failure text)**
- 7 tests: `panicked at src/common/meta/src/ddl_manager.rs:1004:41: not yet implemented`.
- The recovery test: `the batch finished before any region is dropped: Err(JoinError::Panic(.., "not yet implemented", ..))`.
- All eight fail on the intended gap. There were no build, discovery, or harness failures.

**Patch application [EXECUTED]**
- On a pristine worktree at the pinned commit, `git apply` succeeds in both orders: solution then test, and test then solution.
- `test.sh` is created with mode 755.

## Offline execution [EXECUTED, partial]

- `cargo fetch --locked` succeeds with the pinned lockfile. This is the step the Dockerfile runs.
- With the HTTP(S) proxy variables removed and `CARGO_NET_OFFLINE=true`:
  - `cargo metadata --offline --locked` resolves every dependency (exit 0).
  - Subject B `./test.sh --output_path /tmp/base.xml base` gives 602/602, and `... new` gives 8/8.
  - Caveat: compilation was cached locally, so build scripts did not re-run under these conditions.
- [SOURCE] A static scan of the build scripts of all 643 crates in the `common-meta` dependency tree (normal, build and dev edges) found no HTTP client, curl or socket use; the only matches were URLs in comments.
  - The workspace `common-version` build script reads git metadata locally through `git2`, with no network.
  - `.dockerignore` does not exclude `.git`, and the Dockerfile marks `/app` as a git safe directory.

## Docker validation: NOT PERFORMED

The Docker CLI (29.3.1) is present, but no daemon is running (`/var/run/docker.sock` does not exist). **The image was not built locally, and the container runs with `--network none` were not executed.** Free disk (about 3.8 GB) would not fit a cold in-container build either.

**What was verified without a daemon**
- The base image `public.ecr.aws/d3j8x8q7/olympus-base-rust:latest` was inspected through the registry API (gallery metadata, manifest and config); see `validation/base-image.txt`:
  - `latest` equals tag `1.95.0`, index digest `sha256:211a2e3a…`;
  - user root, `WORKDIR /app`, `CMD ["/bin/bash"]`;
  - rustup with Rust 1.95.0 at `CARGO_HOME=/opt/cargo`, `RUSTUP_HOME=/opt/rustup`, plus build-essential, gcc/g++, git and curl.
- The Dockerfile therefore:
  - installs the toolchain pinned by `rust-toolchain.toml` (1.96.1, minimal profile);
  - installs protoc 29.3 and cargo-nextest 0.9.146, both checksum-pinned;
  - installs `pkg-config` and `libssl-dev` defensively;
  - runs `cargo fetch --locked`;
  - sets `CARGO_NET_OFFLINE=true`.
- It keeps the base image's user, `WORKDIR /app`, and `CMD ["/bin/bash"]`.
- No `RUN` step invokes `cargo test`, nextest, or `test.sh`.
- It builds from the pristine pinned repository; the patches are applied afterwards.

**Operational note.** Nothing is compiled at image build time, so the first `./test.sh` run in a container compiles the `common-meta` test dependencies from source, offline. That took about 12 minutes on 4 CPUs locally.

## Static checks (carried over; the solution and Rust test bytes are unchanged)

These results come from revision 1 and still apply, because the solution and the Rust test bytes are identical:
- `cargo fmt -p common-meta -- --check`: clean.
- `cargo clippy -p common-meta --all-targets -- -D warnings`: clean.
- `cargo clippy -p common-meta --all-targets --features enterprise -- -D warnings`: clean.
- The full `common-meta` lib suite passes 610/610.

## Mutation checks (revision 1 results; not re-executed)

These were executed in revision 1 with the previous runner. The Rust tests are byte-identical, and the test-selection filters are unchanged. `validation/run_mutants.sh` now uses the new CLI; it was syntax-checked but not re-run.

| Mutant | Incomplete implementation | Result |
|---|---|---|
| m01 | no same-physical-table check | killed |
| m02 | missing targets always skipped | killed |
| m03 | non-logical targets silently skipped | killed |
| m04 | procedure loader not registered | killed |
| m05 | no cache invalidation | killed |
| m06 | physical regions registered per target | killed (all 8 fail, `RegionOperatingRace`) |
| m07 | handler loops ordinary single-table drops | killed |
| m08 | state not persisted between steps | killed (recovery test) |
| m09 | drops the physical table's regions | killed |
| m10 | drops regions of the first target only | killed |
| m11 | mutates metadata before validating | killed |
| m12 | no deduplication of duplicate targets | survives, as intended (only duplicate safety is required) |

## Flakiness (retries disabled)

| Run | Revision | Result |
|---|---|---|
| NEW via `./test.sh --output_path /tmp/new.xml new` | 2 [EXECUTED] | **10/10**, 8/8 each |
| BASE via `./test.sh --output_path /tmp/base.xml base` | 2 [EXECUTED] | **3/3**, 602/602 each |
| NEW via previous runner | 1 | 10/10 |
| Recovery test alone, `--exact` | 1 (Rust test unchanged) | 20/20 |
| All 8 NEW tests in one process with 8 threads | 1 (Rust test unchanged) | 20/20 |
| BASE via previous runner | 1 | 3/3 |

## Local quality audits

**Test Quality**: unfairTestCount = 0. The analysis is unchanged, and `REQUIREMENT_TEST_MATRIX.md` gains an R13 wording update plus a note on the restart model.

**Solution Quality**: unchanged.

**Description Quality**
- 184 words, plain ASCII, no URLs, file paths, test names, or internal component names.
- The success effects are enumerated directly; the "as if dropped on its own" wording is gone.
- The recovery requirement is stated as "if metasrv restarts".
- Category: `feature_request`.

## Not run locally

- Docker image build and container execution (no daemon; see above).
- The enterprise-feature test binary; the `pg_kvbackend`/`mysql_kvbackend` builds; `make test` (the full workspace).
- A cold offline compile, i.e. build scripts executed without network (see the offline caveat above).
