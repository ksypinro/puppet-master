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

`gaps` splits the difference into two lists:

- **`deadLines`** — code that genuinely never ran. This is the real gap, and the
  only number that belongs in a gate.
- **`neverEvaluatedRegions`** — sub-expressions on lines that did run, each with
  an explanation of what it is and what would reach it.

```
0 genuinely uncovered  ·  4 sub-expression(s) that never evaluated

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

The function layer is the one that makes gaps correct. It is also where
`executionCount` lives.

## Exclude test targets from the headline

A test bundle appearing in coverage is normal — it measures tests testing
themselves, at or near 100%, and inflates any aggregate that includes it.
`coverage_report.py report` excludes them by default and reports **product
coverage** separately. Pass `--include-tests` only when you specifically want
them.

## Gate on changed lines, not the repository

```sh
python3 scripts/coverage_report.py changed /abs/pr.xcresult --base /abs/main.xcresult
```

A repository-wide percentage is gamed by unrelated files: add a well-covered
module and the number rises while the PR's own code stays untested. Coverage of
what the change touched cannot be gamed that way.

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
2. **Real gaps** — the `deadLines` count, not the arithmetic difference.
3. **What the remaining difference is**, briefly: "the other 4 are `??`
   fallbacks and assertion messages, which are not reachable by writing tests."
4. **The limits** — coverage measures execution, not correctness. A line
   executed by a test with no assertion counts as covered.
