---
name: ios-build-engineer
description: Build, sign, package and run iOS apps and Swift packages from the command line, and prove the result rather than trusting an exit code. Use to discover schemes and destinations, resolve build settings and the product path, build for Simulator or device, read build errors as structured diagnostics, archive and export, diagnose code-signing and provisioning failures, produce XCFrameworks and artifact manifests, and install, launch and verify an app is actually running. Also use when a build "succeeded" but the result is wrong or missing. Do not use for running test suites or reading .xcresult test verdicts, which belong to ios-test-engineer, or for driving app UI, which belongs to ios-simulator-driver.
license: MIT
compatibility: Requires macOS, full Xcode (the Command Line Tools package cannot build or run iOS apps), and Python 3.9+. Simulator build, install, launch and liveness verification are the qualified lane. Device compilation is verified; physical-device install and launch require a usable signing identity, a matching provisioning profile, pairing and Developer Mode, and remain unverified by this skill's fixtures.
metadata:
  author: Kazi Samin Yeaser
  version: "1.4.0"
  repository: https://github.com/ksypinro/puppet-master
  short-description: Build, sign and run iOS apps from the CLI, and verify the result
---

# iOS Build Engineer

Produce a build the user can rely on, and say what was actually established. A
zero exit status is the weakest evidence this toolchain emits: it survives a
package built for the wrong operating system, an app that crashed during launch,
and an export that wrote nothing. Report what was observed separately from what
it implies.

Requires macOS, full Xcode, and Python 3.9+. Simulator work needs no signing
material of any kind. Device **compilation** needs no credentials either. Only
installing on physical hardware needs an identity and a profile.

## Non-negotiable boundaries

- **Launching is not running.** `simctl launch` and `devicectl process launch`
  both exit 0 and print a process id for an app that has already crashed. Never
  report an app as running without a liveness probe — `build_run.py run` and
  `build_run.py verify` do this, and treat a dead app as a failed run.
- **A zero exit status does not mean the right platform was built.**
  `swift build --triple arm64-apple-ios17.0` is accepted, prints
  `Build complete!`, and emits **macOS** objects. SwiftPM cannot cross-compile
  to iOS. Route packages through `xcodebuild` with an iOS destination, and
  confirm with `package_products.py verify-platform` before shipping or
  publishing any package artifact.
- **Never guess the product path.** Read `TARGET_BUILD_DIR` +
  `FULL_PRODUCT_NAME` from `-showBuildSettings -json`. A reconstructed
  `DerivedData/.../Build/Products/<Config>-<sdk>/` path breaks under a custom
  `CONFIGURATION_BUILD_DIR` or `SYMROOT` and silently resolves to a stale bundle.
- **Do not change signing configuration, and never mutate Developer Portal
  state.** `-allowProvisioningUpdates` creates and modifies certificates, App
  IDs and profiles; `-allowProvisioningDeviceRegistration` registers devices.
  Both change shared team state. Read signing freely; change it only when the
  user asked for that specific change, and never pass those flags implicitly.
- **Export failures have no structured channel.** `-exportArchive` writes **no
  result bundle at all** on failure, unlike `build`. Diagnosis there is text
  classification via `signing_doctor.py classify`, and it must be reported as
  unstructured rather than with the confidence of bundle-derived diagnostics.
- **Select a signing identity by SHA-1, never by name.** Common names are not
  unique — a keychain can hold several identities sharing one name with all but
  one revoked. The Team ID is the certificate's `organizationalUnitName`, **not**
  the parenthetical inside the common name.
- **Use an explicit device UDID.** `booted` and bare device names can resolve to
  a different simulator between invocations, which invalidates any comparison.
- **Physical-device install and launch are unverified here.** Report them as
  dispatched, not as running, and say that liveness was not established.
- **Do not edit project files, change schemes, or erase a simulator** unless the
  user asked for that action. Diagnosing a build is not permission to alter it.

## Bundled scripts

All are read-only except `build_run.py` and `package_products.py xcframework`,
which run builds. Python 3.9+, standard library only. Resolve `SKILL_DIR` to
this file's directory; paths below are relative to it. Every script emits JSON.

| Script | Role |
|---|---|
| `scripts/build_doctor.py` | Toolchain, SDKs, simulators, locale, and the three signing lanes reported separately |
| `scripts/build_targets.py` | `containers` `schemes` (with **shared** state) `destinations` `settings` `product` |
| `scripts/build_run.py` | `plan` `build` `archive` `export` `install` `launch` `verify` `stop` **`run`** |
| `scripts/signing_doctor.py` | `identities` `profiles` `inspect` **`classify`** — real Team ID, revocation, failure taxonomy |
| `scripts/package_products.py` | `verify-platform` `manifest` `xcframework` |
| `scripts/build_util.py` | Shared container resolution, settings, diagnostics, error type |
| `scripts/build_selftest.py` | Offline self-test of the parsing and classification logic; no Xcode needed |

## The loop

### 1. Establish what this machine can do

```sh
python3 "$SKILL_DIR/scripts/build_doctor.py" --path /abs/project
```

The three lanes fail separately and are reported separately: `buildForSimulator`
needs nothing, `buildForDevice` compiles with no credentials, `installOnDevice`
needs a usable identity **and** a matching profile. Do not tell a user their
signing is broken when their actual task only needs the Simulator.

It also reports whether this is full Xcode. The Command Line Tools package
provides `xcodebuild` but not `simctl`, so checking for `xcodebuild` alone passes
on a machine that cannot do any of this work.

### 2. Discover before building anything

```sh
python3 "$SKILL_DIR/scripts/build_targets.py" schemes      --path /abs/project
python3 "$SKILL_DIR/scripts/build_targets.py" destinations --path /abs/project --scheme App
```

Never guess a scheme or a destination. Act on the **unshared scheme** warning: a
scheme under `xcuserdata/` is not in version control, so CI and teammates cannot
see it. There is no command that shares a scheme — it is a file move into
`xcshareddata/xcschemes/`.

`destinations` separates `physicalDevices` from `simulatorsViaDevicectl`. Xcode
27 surfaces simulators through CoreDevice as well, so treating every `devicectl`
row as hardware is a live bug.

### 3. Resolve the product before you need it

```sh
python3 "$SKILL_DIR/scripts/build_targets.py" product --path /abs/project --scheme App --simulator
```

Returns the app path, bundle id, platform and whether it exists yet. This is the
only supported way to locate a build product.

### 4. Build, and read the diagnostics rather than the log

```sh
python3 "$SKILL_DIR/scripts/build_run.py" build --path /abs/project --scheme App \
    --device-id <UDID> --result-bundle /abs/out
```

Use `plan` instead of `build` to print the exact command without running it.

A failing build emits hundreds of log lines and one typed issue. The script
reports the issue: `type`, `message`, and an exact `file`, `line` and `column`.
Prefer that to any text scraping — line and column live in the result bundle's
URL fragment and are lost by log parsers.

When no result bundle is produced, the output says
`"source": "text fallback"`. That is a weaker claim; pass it on as one.

### 5. Run it, and prove it is alive

```sh
python3 "$SKILL_DIR/scripts/build_run.py" run --path /abs/project --scheme App --device-id <UDID>
```

This is the action `xcodebuild` does not have: build → resolve → install →
launch → **verify**. The verdict is `running`, or
`launched then exited — a FAILURE, even though the launcher exited 0`.

- `--console` streams the app's stdout. It also **terminates the app when the
  console closes**, because `--console-pty` owns the app's lifetime. Use a plain
  run when the app must stay up for UI driving.
- `--env KEY=VALUE` and `--arg=--flag` pass environment and arguments.
  Any value starting with a dash must use the `=` form — `--arg=--flag`,
  `--xcarg=-quiet` — or argparse consumes it as a flag of this script.
- `--setting KEY=VALUE` forwards a build setting override; it reaches
  `xcodebuild` for `plan`, `build`, `archive` and `run`.
- `--no-build` launches what is already built.

To check an app launched elsewhere:

```sh
python3 "$SKILL_DIR/scripts/build_run.py" verify --device-id <UDID> --bundle-id com.example.app
```

Read [references/run-and-verify.md](references/run-and-verify.md) before
composing any launch beyond the above: it carries the console-lifetime rules,
the first-launch failure modes, and the device lane's real prerequisites.

### 6. Archive, export, and diagnose signing

```sh
python3 "$SKILL_DIR/scripts/build_run.py" archive --path /abs/project --scheme App \
    --archive-path /abs/App.xcarchive
python3 "$SKILL_DIR/scripts/build_run.py" export --archive-path /abs/App.xcarchive \
    --export-path /abs/out --options-plist /abs/export.plist
```

Archiving works **unsigned** and still produces dSYMs, which is enough for
artifact manifests and symbol capture with no credentials at all.

When an export or signing step fails:

```sh
python3 "$SKILL_DIR/scripts/signing_doctor.py" identities
python3 "$SKILL_DIR/scripts/signing_doctor.py" classify --message '<the error text>'
```

`classify` maps observed text to a category and a remedy. An unmatched message
is reported as unclassified rather than forced into a category. Note that the
identity name in an export error can be a legacy spelling — `"iOS Development"`
appears nowhere in a modern export plist — so never map the message back to the
requested distribution method.

Read [references/signing-and-export.md](references/signing-and-export.md) before
touching any signing setting or interpreting a provisioning failure.

### 7. Package and verify artifacts

```sh
python3 "$SKILL_DIR/scripts/package_products.py" verify-platform --app /abs/App.app --expect ios
python3 "$SKILL_DIR/scripts/package_products.py" manifest --app /abs/App.app --dsym /abs/App.app.dSYM
python3 "$SKILL_DIR/scripts/package_products.py" xcframework --package /abs/pkg \
    --scheme Lib --output /abs/Lib.xcframework
```

`verify-platform` is the guard against the SwiftPM triple trap and against a
simulator binary shipped as a device binary. `manifest` records binary and dSYM
UUIDs and reports `dsymMatches: false` when a dSYM cannot symbolicate its binary.

Read [references/packaging.md](references/packaging.md) for the XCFramework
recipe and why `xcodebuild archive` cannot be used for SwiftPM library products.

### 8. Report

State, in this order:

1. **What was built** — scheme, configuration, destination, and the resolved
   product path.
2. **The verdict**, and for a run, whether liveness was *verified* or only
   *dispatched*. Always say which.
3. **Each error**, with its real source location. Say when a diagnostic came
   from the text fallback rather than a result bundle.
4. **Signing**, only if it is relevant to the lane the user is in.
5. **What was not established** — an unverified device lane, a platform not
   checked, an export whose success path this skill did not exercise.

Keep raw artifacts. Link the result bundle, archive and manifest rather than
pasting them.

## Four ways a build lies

Each is reproduced by this skill's own checks rather than asserted.

1. **A package built for the wrong OS reports success.**
   `swift build --triple arm64-apple-ios17.0` exits 0 with `Build complete!` and
   produces `platform MACOS`. `verify-platform` is the only thing that catches it.
2. **A crashed app reports a process id.** Both launchers exit 0. Only the
   liveness probe separates dispatch from execution.
3. **An export failure produces no diagnostics.** `build` writes a result bundle;
   `-exportArchive` writes none, so the same `-resultBundlePath` flag yields
   structure in one case and nothing in the other.
4. **A revoked certificate looks like a working one.** Several identities can
   share one common name, and name-based selection cannot tell them apart.

## Route by symptom

These skills are one toolkit. Route on the symptom, not on the surface:

- Producing a build, signing it, packaging it, or getting it running — **this skill**.
- Running a suite, reading a result bundle, or judging whether a failure is real — `ios-test-engineer`.
- Reaching a screen, dispatching taps, text, or gestures, or verifying a UI flow — `ios-simulator-driver`.
- A view is misplaced, clipped, overlapping, mis-styled, or untappable — `ios-view-hierarchy-debugger`.
- A value, branch, or model state is wrong, or you need the code path that produced it — `lldb-code-state-debugger`.
- Launch time, CPU, hangs, jank, memory growth, leaks, I/O, or power — `ios-instruments-profiler`.
- Why an object is still alive, or where the bytes went at a checkpoint — `ios-memory-debugger`.

This skill is the precondition the others assume. Hand off once an installed,
running build exists and the question becomes why it behaves wrongly. Preserve
the established target — UDID, bundle id, app path, configuration and derived
data path — across the handoff, and state whether liveness was verified.
