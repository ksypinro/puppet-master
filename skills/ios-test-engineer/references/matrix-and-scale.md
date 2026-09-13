# Matrices and scale

Read before running more than one scheme or destination. The commands do not
change — you run `xcodebuild` N times instead of once. Everything around them
does.

**Status:** `compare_runs.py matrix` and `compare` are exercised against real
bundles. `merge` and the multi-scheme build flow are derived from verified tool
behaviour but are **not fixture-verified end to end** — no multi-scheme fixture
exists yet. Say so when reporting matrix results.

## First: are ten schemes actually needed?

Ten schemes and ten targets are not the same requirement.

- **Platform-driven schemes are unavoidable.** A watchOS target cannot build
  against an iOS destination.
- **Organisational schemes usually are not.** Ten schemes for ten targets on one
  platform is a test-plan job. One scheme with a plan spanning many test targets
  is faster, aggregates naturally, and avoids most of what follows.

`test_doctor.py --destinations` tells you which case you are in: if every scheme
reports the same platform set, the split is organisational.

## The five problems a matrix introduces

### 1. Unshared schemes

Covered in [running-tests.md](running-tests.md), and it gets worse with scale: on
a ten-scheme project, one unshared scheme means CI tests nine and reports green.
`test_doctor.py` warns; act on the warning before building any matrix.

### 2. Per-scheme destination validity

Not every scheme builds for every destination. The naive cross product is mostly
invalid cells, and each invalid cell costs a failed build to discover.

```sh
python3 scripts/test_doctor.py --path /abs/project --destinations --json
```

Build the matrix from each scheme's own `-showdestinations` output, per scheme.
The tool warns when schemes support different platform sets, which means there is
no full cross product to build.

### 3. Build amplification

Ten schemes built independently recompile shared dependencies ten times. Build
once per scheme into **one shared derived-data path**, then run
`test-without-building` per destination:

```sh
for scheme in "${SCHEMES[@]}"; do
  python3 scripts/run_tests.py build --workspace /abs/App.xcworkspace \
      --scheme "$scheme" --destination-id "$UDID" \
      --derived-data /abs/run/DerivedData --out "/abs/run/build-$scheme"
done
```

Each `build` emits one `.xctestrun` per test plan. Reuse them across
destinations; do not rebuild per cell.

### 4. Result aggregation

N cells produce N bundles and N verdicts. Merge them:

```sh
python3 scripts/compare_runs.py matrix /abs/run/*/Run.xcresult
python3 scripts/compare_runs.py merge  /abs/run/*/Run.xcresult --out /abs/run/all.xcresult
python3 scripts/test_results.py triage /abs/run/all.xcresult
```

`matrix` reports per-cell verdicts and then attributes the failures, which is
what a raw count cannot do — see below.

Merging is cheap — the bundle format is content-addressed, so identical objects
across bundles dedupe by hash.

**Keep the per-cell bundles.** The merged bundle answers "did the suite pass";
only the individual ones answer "which cell failed", and that distinction is the
whole point of a matrix. Run `triage` on both.

### 5. Device and simulator contention

`xcodebuild` shuts the Simulator down after a run, so a following command fails
with `Unable to lookup in current state: Shutdown`. Run cells concurrently
against overlapping devices and this becomes intermittent install and teardown
failure — which `triage` will correctly classify as *infrastructure*, but which
you should prevent rather than retry around.

Rules that hold:

- **One consumer per device at a time.** Lease it; do not share.
- A physical device needs an exclusive lease more than a simulator does.
- `xcrun simctl bootstatus <UDID> -b` before a run that follows another.
- Never erase a simulator or re-pair a device automatically to recover.

## Failure attribution across cells

"4 of 40 failed" is not actionable. Three situations look identical in a naive
count and need different responses:

| Pattern | Means | Response |
|---|---|---|
| 4 different tests, 4 different cells | four independent failures | triage each |
| 1 test failing on 4 platforms | one bug with platform reach | fix once |
| 4 tests failing on 1 destination | that device or simulator is unhealthy | fix the cell, do not touch the tests |

`compare_runs.py matrix` does this grouping and names the pattern it found. If
one destination accounts for most failures, suspect the destination first — and
check its diagnostics (`test_results.py diagnostics`) before concluding anything
about the product.

## Sharding

`-parallelize-tests-among-destinations` distributes test classes across
destinations rather than cloning the suite, and is explicitly **not a stable
sharding contract**. For deterministic ownership, retries, or duration-balanced
shards, compute them yourself:

1. `-enumerate-tests` to get the full list without running.
2. Split by historical duration if you have it, otherwise round-robin.
3. Pass explicit `-only-testing` lists per shard.

This is the only way a shard's contents are reproducible between runs, which is
a precondition for correlating a flake to a shard.

## Parallelism within one destination

`-parallel-testing-enabled YES` clones the device. Results are attributed to
`Clone 1 of iPhone 17 Pro`, and each worker starts a fresh process.

A test that depends on state left by an earlier test in the same process will
fail on a clone and pass serially. **That is a real bug the clone exposed**, not
a parallelism artefact — the same distinction `--repetition relaunch` makes in
[failure-triage.md](failure-triage.md).

One clone per worker costs real RAM, disk and boot time. More workers is not
monotonically faster.

## Reporting a matrix run

State:

1. The cells that **ran**, and the cells that were **skipped as invalid** — a
   matrix with unstated gaps reads as more coverage than it is.
2. The aggregate verdict from the merged bundle, and the per-cell verdicts.
3. Failure attribution: independent failures, one bug across platforms, or one
   unhealthy cell.
4. Hidden flakes, per cell. A retry flag applied matrix-wide hides more.
5. Which destinations were **not** covered, especially any physical device.
