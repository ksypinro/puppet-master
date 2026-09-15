# Packaging: frameworks, XCFrameworks, and artifact manifests

## `xcodebuild archive` does not work for SwiftPM library products

The widely-circulated "archive each platform, then `-create-xcframework`" recipe
assumes an Xcode framework target. For a plain Swift package library:

```sh
xcodebuild archive -scheme Greeter -destination 'generic/platform=iOS' \
  -archivePath ios.xcarchive SKIP_INSTALL=NO BUILD_LIBRARY_FOR_DISTRIBUTION=YES
# ** ARCHIVE SUCCEEDED **
```

…and the archive contains a bare `Greeter.o` at
`Products/Users/<user>/Objects/` — an absolute-path-derived location, with no
`.a` and no `.framework`. The static library has to be produced by hand.

## The recipe that works

Verified end to end, and implemented by `package_products.py xcframework`:

```sh
for dest in 'generic/platform=iOS' 'generic/platform=iOS Simulator'; do
  xcodebuild -scheme Greeter -destination "$dest" -derivedDataPath "dd-$tag" \
    build BUILD_LIBRARY_FOR_DISTRIBUTION=YES

  libtool -static -o "$tag/libGreeter.a" "dd-$tag/Build/Products/<Config>-<sdk>/Greeter.o"
  cp -R "dd-$tag/Build/Products/<Config>-<sdk>/Greeter.swiftmodule" "$tag/"
done

xcodebuild -create-xcframework \
  -library ios/libGreeter.a -library simulator/libGreeter.a \
  -output Greeter.xcframework
```

Two details decide whether the result is usable:

**The `.swiftmodule` must be a sibling of the `.a`.** `-create-xcframework`
finds it there by itself and places it at the slice root.

**Do not pass `-headers` for a pure-Swift library.** It additionally creates a
redundant `Headers/` copy — doubling the size and, worse, leading consumers to
`-I <slice>/Headers`, which fails with *"no such module"*. The correct
consumption is the slice **root**:

```sh
swiftc -target arm64-apple-ios17.0 -sdk "$(xcrun --sdk iphoneos --show-sdk-path)" \
  -I Greeter.xcframework/ios-arm64 -L Greeter.xcframework/ios-arm64 -lGreeter app.swift
```

Both the failure and the fix were verified by compiling and linking against the
output. A structurally valid XCFramework is not necessarily a consumable one —
check by building against it, not by reading `Info.plist`.

`BUILD_LIBRARY_FOR_DISTRIBUTION=YES` is what emits the `.swiftinterface` files
(public, private and package) that make the module usable from a different
compiler version.

## Verify the platform of anything you ship

```sh
python3 scripts/package_products.py verify-platform --binary <product> --expect ios
```

A build can report success and target the wrong operating system — SwiftPM
accepts `--triple arm64-apple-ios17.0`, exits 0 and emits macOS objects. It is
equally easy to ship a simulator slice as a device slice. `vtool -show-build`
reads the Mach-O `LC_BUILD_VERSION` load command, which is the only thing that
actually settles it:

```
platform IOS            → device
platform IOSSIMULATOR   → simulator
platform MACOS          → wrong for any iOS artifact
```

## Artifact manifests

```sh
python3 scripts/package_products.py manifest --app App.app --dsym App.app.dSYM
```

Records bundle id, versions, minimum OS, architectures, platform, size, signing
team, and the **binary and dSYM UUIDs**. The UUID pair is what a later crash
triage needs: `dsymMatches: false` means that dSYM cannot symbolicate that
binary, which is otherwise discovered only when symbolication silently produces
addresses instead of names.

Write a manifest at the moment of the build. Reconstructing one later requires
the exact binary, which is usually the thing that has been lost.

## Frameworks inside an app

Embedded frameworks are signed before the app that contains them, and re-signing
an app does **not** re-sign its nested code. When a bundle fails verification
after a manual signing step, check the frameworks in
`App.app/Frameworks/` individually with `codesign --verify` before assuming the
outer signature is at fault.
