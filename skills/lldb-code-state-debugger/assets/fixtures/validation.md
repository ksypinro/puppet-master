# Source-owned debugger fixture contract

These are intentionally faulty, deterministic programs for validating code-state debugging. All amounts, strings, and bytes are artificial. No fixture reads user files, persists data, accesses a network, uses location, or touches another application. Do not correct the deliberate sign defect: its first divergent state transition is the test oracle.

Qualification note (2026-09-12): native C, Swift and the separately compiled `native/code_exception.cpp` have live debugger evidence. The bare Simulator app built and installed, but macOS refused execution with OS_REASON_EXEC code 8. Do not treat this fixture's UI contract below as a passed test or weaken host protections to run it. Prefer a separately authorized, ordinarily built development app when that prerequisite is resolved. The C++ fixture can be compiled with `xcrun clang++ -g -O0 /absolute/code_exception.cpp -o /absolute/new-code-exception`; it throws integer 17 and catches it normally.

Building does not authorize installing or running a fixture. The provided script only compiles, emits dSYMs, and ad-hoc signs the Simulator bundle. A separate harness must explicitly own any fixture launch, attachment, installation, debugger stop, and cleanup. Never substitute Sparrow or another existing application for a fixture.

## Build and artifact checks

Use an explicit, empty output directory outside the skill source:

```bash
fixture_out=$(mktemp -d /private/tmp/lldb-code-state-fixtures.XXXXXX)
bash skills/lldb-code-state-debugger/assets/fixtures/build.sh --output-dir "$fixture_out" --mode all
```

`--arch arm64` or `--arch x86_64` controls the target architecture; the default is the host architecture. Native fixtures require macOS 13 or newer. The UI fixture targets iOS Simulator 16 or newer, not a physical device. There is no Xcode project or third-party package dependency. The selected full Xcode must provide macOS and iOS Simulator SDKs. Never claim a cross-architecture binary ran just because it compiled.

The script refuses any nonempty output directory instead of deleting or overwriting its contents. If a build fails, retain the partial outputs and retry in a fresh explicit directory. Compilation, plist lint, signing verification, and UUID equality are build-level checks only; they do not establish attachment, Swift evaluation, or UI automation success.

Expected outputs:

- `code-state-c` and `code-state-c.dSYM`
- `code-state-swift` and `code-state-swift.dSYM`
- `CodeStateUIFixture.app` and `CodeStateUIFixture.app.dSYM`
- `module-cache/` used only for compilation
- `objects/` retained object files and Swift modules used to produce complete dSYMs

Check each binary and its dSYM with `xcrun dwarfdump --uuid`, then compare UUIDs per architecture. Discover exact breakpoint lines from the source instead of hard-coding numbers:

```bash
rg -n 'FIXTURE:' skills/lldb-code-state-debugger/assets/fixtures
```

Every executable breakpoint marker is on its target statement. `UI_MODEL_RETURN` is on a closing brace and is intentionally only a stepping landmark: do not demand that a compiler emit a unique line-table location for it. A breakpoint set at a source line executes before that statement; inspect initialized locals only at or after the appropriate assignment. Record requested and resolved locations, not just breakpoint IDs.

## Native C invariants

The three debits are 120, 75, and 40. Starting balance is 1000. The actual balances after applying each are **880, 805, 845**; the correct final balance would be **765**. The program exits successfully after printing a mismatch so the harness does not confuse an intentional logic defect with a crash.

| Observation point | Required semantic evidence |
|---|---|
| `C_READY`, before assignment | Global `fixture_balance == 1000`; do not require `actual` to be initialized yet. |
| `C_CALL` with `index == 2` | `debit.amount == 40`, `debit.name == "fruit"`, `actual == 805`. |
| `C_BEFORE_WRITE` with `index == 2` | `before == 805`, `signed_amount == 40`, global balance still 805. This is the first wrong decision before the write. |
| `C_AFTER_WRITE` on third call | Global balance is 845; `after` is not initialized until stepping over this statement. |
| `C_RETURN` on third call | `after == 845`. |
| `C_FINAL` | `actual == 845`, `expected == 765`, `actual != expected`. |

Proposed transport tests:

1. Set a source breakpoint at `C_BEFORE_WRITE` with condition `index == 2`. Require at least one resolved location and exactly the third call as the matching stop. A pending breakpoint is not a successful hit.
2. Start at `C_CALL` on the first iteration; step into `apply_debit`; verify parameter values and that the stack contains both `apply_debit` and `main`. Step over the write, and step out back to the caller. Allow compiler line-table granularity; do not require one exact intermediate line for every step.
3. While stopped at `C_READY`, request a write watchpoint on `fixture_balance`. It is explicitly a four-byte `int32_t` volatile global. Record watchpoint resolution and hardware availability; an unavailable slot is **unsupported**, not a failing app invariant. On the first observed write, expect transition 1000 → 880; on the defect write expect 805 → 845. Hardware watchpoints normally stop after the instruction: capture the stop reason and actual PC, not an assumed before-write source line. Disable a separate breakpoint at the same instruction to avoid confusing stop reasons.
4. Read exactly eight bytes at `&fixture_bytes[0]`: `00 11 22 33 44 55 66 77`. These are one-byte elements, so this expected sequence is independent of host endianness. Validate memory-read length and address provenance. Do not read adjacent unrelated memory.
5. Verify variable references obtained in one stop are rejected or refreshed after continue/step. Numeric handle equality alone is not evidence that a value belongs to the same stop generation.

Representative LLDB expressions are `index == 2`, `&fixture_balance`, and `&fixture_bytes[0]`. Prefer structured variable/memory APIs or `frame variable` for inspection; address evaluation may require a bounded expression. Exact API syntax belongs to the harness, not this fixture.

## Native Swift invariants

The Swift program uses the same debit inputs, balances, and intentional third-debit defect. Its source provides a class, struct, optional, array, Swift method, and caller frame for testing the matching Apple Swift debugger. A successful C test does not establish Swift expression support.

- At `SWIFT_CALL` on iteration 2: `ledger.balance == 805`; `ledger.appliedCount == 2`; `debit.amount == 40`; `debit.name == "fruit"`; `ledger.coupon` is genuinely `nil`.
- At `SWIFT_BEFORE_WRITE` with `index == 2`: `before == 805`, `signedAmount == 40`, `self.balance == 805`.
- At `SWIFT_RETURN` on the third call: `self.balance == 845`, `self.appliedCount == 3`.
- At `SWIFT_FINAL`: `actual == 845`, `expected == 765`, `ledger.balance == 845`.
- Step into the `ledger.apply` call, inspect `debit` and `index`, then step out. Distinguish a Swift runtime/generated frame from the intended user-source frame.

`FixtureLedger.description` intentionally increments `descriptionReadCount`. To test evaluation side effects, stop at `SWIFT_FINAL`, use raw stored-property inspection to obtain the baseline, explicitly evaluate `ledger.description`, and inspect the counter again. Require a delta of one for that single explicit property evaluation. A separately authorized `po ledger` should expose the object description; record the observed counter change rather than asserting exactly one call, since formatter/debugger versions can invoke descriptions differently. Do not run either during the read-only baseline. This demonstrates why a pretty-print is not automatically observationally pure.

If the debugger reports a value unavailable, optimized out, or fails to import a Swift module, preserve that status. Do not turn it into `nil`, zero, or an application defect. These fixtures compile with `-Onone -g`, but toolchain, module, target, and permission mismatches can still prevent inspection.

## UIKit Simulator invariants

Bundle identifier: `dev.local.lldb-code-state-fixture`. Executable: `CodeStateUIFixture`. All model/UI activity is main-actor local. The app uses UIKit and explicit accessibility identifiers, and requires no permissions or onboarding. The dedicated Reset Fixture button resets only in-process artificial state.

| UI action completed | Visible balance | Visible status |
|---|---|---|
| Fresh launch or Reset Fixture | Balance: $1000 | Taps: 0 · Delta: 0 |
| First Debit $40 | Balance: $960 | Taps: 1 · Delta: -40 |
| Second Debit $40 | Balance: $920 | Taps: 2 · Delta: -40 |
| Third Debit $40 | Balance: $960 | Taps: 3 · Delta: 40 |

Control targets are `fixture.debit` and `fixture.reset`. Observe `fixture.balance` and `fixture.status`; their accessibility values also expose exact numeric state. Labels and accessibility are two representations of the same app state, not independent proof of the model.

The meaningful UI-to-debugger test is:

1. With explicit fixture runtime authority, install/launch only this dedicated bundle on one chosen Simulator. Record UDID, bundle, executable UUID, PID, debugger session, and source hash.
2. Capture the initial UI and perform two taps with the simulator-driver. Wait for each expected state change while the process is running; log the action and observation IDs.
3. Install a source breakpoint at `UI_BEFORE_WRITE` conditioned on `tapNumber == 3`. Verify the resolved source location. Continue if necessary, then tap Debit $40 once.
4. Wait for the actual debugger stopped event, not just success of the tap command. The stop must belong to the owned PID and report the intended breakpoint. At the stop require `amount == 40`, `tapNumber == 3`, `before == 920`, `delta == 40`, `self.balance == 920`, `self.lastDelta == 40`, and `self.tapCount == 3`.
5. Capture the user-source stack. It should connect `FixtureModel.debit(amount:)` to `FixtureViewController.didTapDebit()` plus UIKit delivery frames. This ties the driver action to the model mutation; a random paused stack does not.
6. Step over the assignment or continue to `UI_RENDER_AFTER_ACTION`. At that line the model balance is 960 but `render()` has not yet updated the labels. The previous UI showing 920 while paused here is expected and is not a stale-view defect.
7. Continue; only now wait for the rendered third-tap UI and capture its screenshot/accessibility. The erroneous +40 delta, not rendering, explains the wrong final balance. The correct business expectation after three debits is 880.
8. Detach or terminate only the owned fixture according to the test contract; prove debugger/session cleanup. Uninstall only this test bundle if the harness installed it and cleanup was authorized. Never erase/reset a Simulator as fixture cleanup.

Screenshots while paused can be stale or unavailable because the UI thread cannot run. Do not send another state-dependent tap until the target is running. If stop delivery or UI observation fails, report the exact unproved stage, preserve artifacts, and do not claim an end-to-end pass from compilation alone.
