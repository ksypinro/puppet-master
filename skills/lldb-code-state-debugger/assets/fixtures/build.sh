#!/bin/bash
# Builds only artificial fixtures. Never installs, boots, launches, or attaches.
set -euo pipefail

usage() {
    printf 'Usage: bash %s --output-dir /absolute/empty/directory [--mode native|simulator|all] [--arch arm64|x86_64]\n' "$0"
}

build_out=''
build_mode='all'
build_arch=$(uname -m)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir|--mode|--arch)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            case "$1" in
                --output-dir) build_out=$2 ;;
                --mode) build_mode=$2 ;;
                --arch) build_arch=$2 ;;
            esac
            shift 2
            ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

[[ "$build_out" = /* && "$build_out" != / ]] || { printf 'An explicit absolute output directory is required.\n' >&2; exit 2; }
case "$build_mode" in native|simulator|all) ;; *) usage >&2; exit 2 ;; esac
case "$build_arch" in arm64|x86_64) ;; *) printf 'Unsupported architecture.\n' >&2; exit 2 ;; esac
[[ "$(uname -s)" = Darwin ]] || { printf 'These fixtures require macOS and the selected Xcode toolchain.\n' >&2; exit 2; }

fixture_root=$(cd "$(dirname "$0")" && pwd -P)
mkdir -p "$build_out"
build_out=$(cd "$build_out" && pwd -P)
shopt -s nullglob dotglob
existing_entries=("$build_out"/*)
[[ ${#existing_entries[@]} -eq 0 ]] || { printf 'Refusing a nonempty output directory: %s\n' "$build_out" >&2; exit 2; }
mkdir "$build_out/module-cache" "$build_out/objects"

if [[ "$build_mode" = native || "$build_mode" = all ]]; then
    xcrun --sdk macosx clang -arch "$build_arch" -std=c11 -g -O0 -fno-omit-frame-pointer -Wall -Wextra -Werror \
        -c "$fixture_root/native/code_state.c" -o "$build_out/objects/code-state-c.o"
    xcrun --sdk macosx clang -arch "$build_arch" "$build_out/objects/code-state-c.o" -o "$build_out/code-state-c"
    xcrun --sdk macosx swiftc -target "$build_arch-apple-macosx13.0" -swift-version 5 -g -Onone \
        -module-name CodeStateSwiftFixture -module-cache-path "$build_out/module-cache" \
        -emit-object -emit-module -emit-module-path "$build_out/objects/CodeStateSwiftFixture.swiftmodule" \
        "$fixture_root/native/code_state.swift" -o "$build_out/objects/code-state-swift.o"
    xcrun --sdk macosx swiftc -target "$build_arch-apple-macosx13.0" \
        -Xlinker -add_ast_path -Xlinker "$build_out/objects/CodeStateSwiftFixture.swiftmodule" \
        "$build_out/objects/code-state-swift.o" -o "$build_out/code-state-swift"
    xcrun dsymutil "$build_out/code-state-c" -o "$build_out/code-state-c.dSYM"
    xcrun dsymutil "$build_out/code-state-swift" -o "$build_out/code-state-swift.dSYM"
    printf 'Built native fixtures: %s/code-state-{c,swift}\n' "$build_out"
fi

if [[ "$build_mode" = simulator || "$build_mode" = all ]]; then
    sim_sdk=$(xcrun --sdk iphonesimulator --show-sdk-path)
    fixture_app="$build_out/CodeStateUIFixture.app"
    mkdir "$fixture_app"
    cp "$fixture_root/simulator/Info.plist" "$fixture_app/Info.plist"
    xcrun --sdk iphonesimulator swiftc -parse-as-library -target "$build_arch-apple-ios16.0-simulator" \
        -sdk "$sim_sdk" -swift-version 5 -g -Onone -module-name CodeStateUIFixture \
        -module-cache-path "$build_out/module-cache" -framework UIKit -framework Foundation \
        -emit-object -emit-module -emit-module-path "$build_out/objects/CodeStateUIFixture.swiftmodule" \
        "$fixture_root/simulator/CodeStateUIFixture.swift" -o "$build_out/objects/code-state-ui.o"
    xcrun --sdk iphonesimulator swiftc -target "$build_arch-apple-ios16.0-simulator" -sdk "$sim_sdk" \
        -Xlinker -add_ast_path -Xlinker "$build_out/objects/CodeStateUIFixture.swiftmodule" \
        -framework UIKit -framework Foundation "$build_out/objects/code-state-ui.o" -o "$fixture_app/CodeStateUIFixture"
    xcrun dsymutil "$fixture_app/CodeStateUIFixture" -o "$build_out/CodeStateUIFixture.app.dSYM"
    /usr/bin/codesign --sign - --timestamp=none --entitlements "$fixture_root/simulator/Debug.entitlements" "$fixture_app"
    /usr/bin/codesign --verify --strict "$fixture_app"
    printf 'Built Simulator fixture: %s\nBundle ID: dev.local.lldb-code-state-fixture\n' "$fixture_app"
fi

printf 'Build complete. No fixture has been installed, launched, or attached.\n'
