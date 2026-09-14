# Building: actions, destinations, settings, and packages

Verified against Xcode 27.0 (27A5194q), Swift 6.4, iOS 27.0 SDK.

## There is no `run` action

`xcodebuild` has ten actions and none of them runs an app:

```
build   build-for-testing   analyze   archive   test   test-without-building
docbuild   install   installsrc   clean
```

`install` is a Make-style copy to `DSTROOT` on the **host**. It does not put
anything on a device. Running is always a composite — build, resolve, install,
launch, verify — and the last three belong to `simctl` and `devicectl`.

## Destinations

| Intent | Destination |
|---|---|
| A specific simulator | `platform=iOS Simulator,id=<UDID>` |
| Any simulator (CI, archive) | `generic/platform=iOS Simulator` |
| A specific device | `platform=iOS,id=<UDID>` |
| Any device (archive, compile check) | `generic/platform=iOS` |

Always prefer an explicit UDID for anything comparable across runs. A bare name
or `booted` can resolve to a different device between invocations.

`-showdestinations` is the one query flag with **no `-json` form**. Its brace
format has to be parsed, and it prints an *incompatible* section alongside the
compatible one where each entry carries an `error:` field. Consuming those as
usable targets is a real bug; `build_targets.py destinations` drops them.

## Build settings and the product path

`-showBuildSettings -json` is the contract. With `-scheme` it returns exactly one
entry; with `-target` or `-alltargets` it returns one per target — WebDriverAgent
returns 17 — and a first-match text regex then resolves the wrong product
(`WebDriverAgentLib.framework` instead of the app). Select on the `target` key.

The product is `TARGET_BUILD_DIR` + `/` + `FULL_PRODUCT_NAME`.
`TARGET_BUILD_DIR` is the target's own output directory and stays correct under a
custom `CONFIGURATION_BUILD_DIR`; `BUILT_PRODUCTS_DIR` is the shared collection
point and is only a fallback.

## Device builds need no credentials

```sh
# fails: automatic signing with no team
xcodebuild -scheme App -destination 'generic/platform=iOS' build
# error: Signing for "App" requires a development team.

# succeeds: real arm64 iOS Mach-O, no account, no profile, no certificate
xcodebuild -scheme App -destination 'generic/platform=iOS' build \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=""
```

The resulting binary carries `LC_BUILD_VERSION platform IOS`. CI can therefore
compile-verify the device slice with zero secrets. Only *installing on hardware*
needs credentials — keep the two questions apart when reporting to a user.

## Structured diagnostics

```sh
xcodebuild ... -resultBundlePath build.xcresult build
xcrun xcresulttool get build-results --path build.xcresult
```

The bundle is produced for a plain `build`, not only for `test`. A deliberate
Swift error produced 365 lines of stdout, exit 65, and one typed issue:

```json
{ "issueType": "Swift Compiler Error",
  "message": "Cannot find 'undefinedSymbol' in scope",
  "sourceURL": "file:///…/App.swift#StartingLineNumber=26&StartingColumnNumber=31" }
```

Line and column live in the **URL fragment** and must be parsed out of it. Log
parsers lose them.

`-exportArchive` is the exception: it writes no result bundle on failure, so the
same flag yields structure for `build` and nothing for export.

## Swift packages

```sh
swift build                                    # host (macOS) only
xcodebuild -scheme MyLib -destination 'generic/platform=iOS' build   # the iOS route
```

**SwiftPM cannot cross-compile to iOS.** `swift build --triple arm64-apple-ios17.0`
is accepted, exits 0, prints `Build complete!`, and produces objects identical to
a host build — `platform MACOS minos 12.0`. `swift sdk list` reports no installed
SDKs; the flag is accepted and ignored. The same package through `xcodebuild`
with an iOS destination yields `platform IOS minos 17.0`.

Nothing in the exit status reveals this. Verify the artifact:

```sh
python3 scripts/package_products.py verify-platform --binary <product> --expect ios
```

In Swift 6.4 the default SwiftPM build system is `swiftbuild` — the same engine
Xcode drives, now open source — with `native` deprecated. That is an engine swap
under existing commands, not a new interface.

## Toolchain pinning

```sh
DEVELOPER_DIR=/Applications/Xcode-16.4.app/Contents/Developer xcodebuild -version
```

Per-invocation, no sudo, no global state. Prefer it to `xcode-select -s`, which
changes machine-wide state and will surprise a concurrent build. `TOOLCHAINS=<id>`
selects a Swift toolchain for `xcrun`.

Full Xcode is required. The Command Line Tools package ships `xcodebuild` but not
`simctl`, so a check for `xcodebuild` alone passes on a machine that cannot build
or run iOS apps at all.

## Environment

Export a UTF-8 locale in CI. A non-UTF-8 `LANG`/`LC_ALL` surfaces as `US-ASCII`
build errors that look like source problems.

`timeout(1)` does not exist on macOS. Bound any streaming command with
`select()` polling in-process, `gtimeout` from coreutils, or background + kill.
