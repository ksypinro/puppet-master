---
paths:
  - "**/*.swift"
  - "**/*.m"
  - "**/*.mm"
  - "**/*.h"
  - "**/*.xcodeproj/**"
  - "**/*.xcworkspace/**"
  - "**/Package.swift"
---

# Use ios-build-engineer to build, sign, package and run

Compiling, archiving, exporting, diagnosing a signing failure, or getting an app
installed and actually running goes through `ios-build-engineer`.

**A zero exit status is the weakest evidence this toolchain emits.** It survives
a package built for the wrong operating system, an app that crashed during
launch, and an export that wrote nothing. Do not report a build as good because
`xcodebuild` returned 0.

**Launching is not running.** `simctl launch` and `devicectl process launch`
both exit 0 and print a process id for an app that has already crashed. Never
report an app as running without a liveness probe — `build_run.py run` and
`build_run.py verify` do this.

**SwiftPM cannot cross-compile to iOS.** `swift build --triple
arm64-apple-ios17.0` is accepted, prints `Build complete!`, and emits **macOS**
objects. Route packages through `xcodebuild` with an iOS destination and confirm
with `package_products.py verify-platform`.

Never reconstruct a product path from `DerivedData/.../Build/Products/`. Read
`TARGET_BUILD_DIR` and `FULL_PRODUCT_NAME` from `-showBuildSettings -json`; a
custom `CONFIGURATION_BUILD_DIR` or `SYMROOT` makes the guessed path resolve to
a stale bundle without saying so.

Never pass `-allowProvisioningUpdates` or
`-allowProvisioningDeviceRegistration` on your own initiative. They create and
modify certificates, App IDs, profiles and device registrations — shared team
state. Read signing freely; change it only when the user asked for that change.

Select a signing identity by SHA-1, never by name. One keychain can hold several
identities sharing a common name with all but one revoked. The Team ID is the
certificate's `organizationalUnitName`, not the parenthetical in the name.

`-exportArchive` writes **no result bundle at all** on failure. Diagnosis there
is text classification via `signing_doctor.py classify` — report it as
unstructured, not with the confidence of bundle-derived diagnostics.

Physical-device install and launch are unverified by this skill. Report them as
dispatched, not as running, and say liveness was not established.

Do not run test suites here — that is `ios-test-engineer`. Do not drive app UI
here — that is `ios-simulator-driver`.

<!-- installed by puppet-master · github.com/ksypinro/puppet-master · edit freely; ./uninstall.sh only removes files still carrying this line -->
