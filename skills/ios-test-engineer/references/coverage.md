# Coverage

Read before building any coverage gate or reporting a percentage to a user.

## The mistake this reference exists to prevent

Subtracting `coveredLines` from `executableLines` and calling the difference
"untested lines" is wrong on Swift, and confidently so.

Verified on a real project reporting 98.11% line coverage with "2 uncovered
lines". Neither was untested code:

```
line 47   index[key] = Array(Set(index[key] ?? [])).sorted()
          region    implicit closure #2 in NoteIndex.init(notes:)
          executed  0×  —  but the LINE ran 336×

line 27   XCTAssertNotEqual(count.label, before, "the count did not change")
          region    implicit closure #5 in testSearchFiltersTheList()
          executed  0×  —  but the LINE ran 1×
```

Line 47 is a `?? []` fallback that never fired because the lookup never returned
nil. Line 27 is an **assertion's failure message**, which only evaluates when the
assertion fails — it is uncovered *because the test passed*. Telling a developer
to "cover line 27" asks them to break their own assertion.

On healthy Swift, a line-count gate fires mostly on passing assertions and unused
nil-coalescing defaults. **Report the region and its enclosing line's hit count,
or do not report lines at all.**

## Use the tool

```sh
python3 scripts/coverage_report.py report /abs/Run.xcresult
python3 scripts/coverage_report.py gaps   /abs/Run.xcresult
```

`gaps` reports two different evidence classes:

- **`uncoveredLines`** — executable source lines whose coverage archive hit
  count is directly zero. These can support a coverage gate, but do not prove
  that the source is dead or unreachable. `deadLines` remains only as a
  compatibility alias.
- **`neverEvaluatedRegions`** — partial function/region observations on an entry
  line that did run. These are advisory because a function entry does not map
  every uncovered branch or column range.

```
0 zero-hit executable lines  ·  4 advisory region observations

NoteIndex.swift:47   [DemoApp.app]
  index[key] = Array(Set(index[key] ?? [])).sorted()
  region   implicit closure #2 in NoteIndex.init(notes:)
  executed 0x, enclosing line ran 336x
  → A `??` fallback that never fired — the enclosing line ran 336x, but the
    left-hand side was never nil. To reach it, add a case where the value is
    absent.
```

Recognised shapes: `??` fallbacks, assertion messages, short-circuited `||` and
`&&` operands, and other compiler-synthesised regions (autoclosures, default
arguments, thunks, protocol witnesses).

## Three resolutions

| Resolution | Source | Good for |
|---|---|---|
| Target | `xccov --report` | the headline number |
| File | `xccov --report` | ownership, review targeting |
| Function | `functions[]` per file | **the truthful gap analysis**, plus `executionCount` |
| Line | `xccov --archive --file` | per-line hit counts and column-range regions |

The archive line layer supplies the gateable zero-hit evidence. The function
layer adds names and `executionCount`, but a function's covered entry line does
not establish coverage of later branches.

## Exclude test targets from the headline

A test bundle appearing in coverage is normal — it measures tests testing
themselves, at or near 100%, and inflates any aggregate that includes it.
`coverage_report.py report` excludes them by default and reports **product
coverage** separately. Pass `--include-tests` only when you specifically want
them.

## Compare file coverage between runs

```sh
python3 scripts/coverage_report.py changed /abs/pr.xcresult --base /abs/main.xcresult
```

This command compares whole-file percentages between two bundles. It does not
intersect coverage with Git diff hunks and must not be described as changed-line
coverage. For a changed-line gate, obtain the changed line ranges from source
control and intersect them with the archive's per-line hit counts.

`xcrun xccov diff --json before.xcresult after.xcresult` is the native
equivalent.

### Path equivalence will bite you

The same source under a different checkout root does not match between CI and a
laptop. Files show as `removed` + `added` rather than `unchanged`, and fully
covered code silently reports 0%. Normalise paths to a repository-relative form
before comparing bundles produced on different machines. The tool's output notes
this; do not report a regression without checking it first.

## `executionCount` is a free hot-path map

```sh
python3 scripts/coverage_report.py hot /abs/Run.xcresult
```

Functions ranked by how many times the suite executed them. Useful for choosing
what to profile, what to fuzz, and what is worth optimising — and for noticing
that something you believed was hot is never called.

## Enabling coverage

Coverage must be requested at run time and **cannot be added to a bundle
afterwards**:

- `run_tests.py … --coverage`
- or `-enableCodeCoverage YES`
- or the test plan's `codeCoverage` option, which `test_doctor.py` reports per
  plan

`test_results.py availability` tells you whether an existing bundle has any.

For SwiftPM there is no `.xcresult`; use `swift test --enable-code-coverage` and
report with `xcrun llvm-cov report` against the profdata — see
[running-tests.md](running-tests.md).

## Reporting coverage to a user

Say four things:

1. **Product coverage**, with test targets excluded, and say that you excluded
   them.
2. **Direct zero-hit gaps** — the `uncoveredLines` count, not an arithmetic
   difference and not a claim that the code is dead.
3. **Advisory region observations**, briefly. A `??` fallback is reachable with
   a nil input; an assertion-message autoclosure usually runs only on failure.
4. **The limits** — coverage measures execution, not correctness. A line
   executed by a test with no assertion counts as covered.
