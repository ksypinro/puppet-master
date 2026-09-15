#!/usr/bin/env python3
"""Offline self-test for the parsing and classification logic.

Runs without Xcode, without a simulator and without network: every case uses
captured output. Exercises the parts that silently produce a wrong answer when
they regress — destination parsing, product resolution, diagnostic extraction,
platform verification and the signing taxonomy.

    python3 build_selftest.py
"""

from __future__ import annotations

import sys

import build_util
from build_targets import parse_destinations
from build_util import _source_location, resolve_product, text_fallback_errors
from signing_doctor import classify

FAILURES = []


def check(name, actual, expected):
    if actual == expected:
        print("  ok    %s" % name)
    else:
        print("  FAIL  %s\n          expected: %r\n          actual:   %r"
              % (name, expected, actual))
        FAILURES.append(name)


def check_true(name, value):
    check(name, bool(value), True)


# ---- destinations -------------------------------------------------------
# Captured from `xcodebuild -showdestinations`. The incompatible section must be
# dropped: those entries carry an error: field and are not usable targets.
SHOWDESTINATIONS = """
\tDestinations compatible with the "DemoApp" scheme:
\t\t{ platform:macOS, arch:arm64, variant:Designed for [iPad,iPhone], id:00008103-000C, name:My Mac }
\t\t{ platform:iOS, id:dvtdevice-DVTiPhonePlaceholder-iphoneos:placeholder, name:Any iOS Device }
\t\t{ platform:iOS Simulator, arch:arm64, id:AB21889A-A9DD, OS:27.0, name:iPhone 17 Pro }

\tDestinations incompatible with the "DemoApp" scheme:
\t\t{ platform:macOS, arch:arm64e, id:00008103-000C, name:My Mac, error:My Mac's macOS platform doesn't match. }
"""


def test_destinations():
    print("destination parsing")
    parsed = parse_destinations(SHOWDESTINATIONS)
    check("keeps only compatible destinations", len(parsed), 3)
    check("parses a simulator row", parsed[2]["name"], "iPhone 17 Pro")
    check("parses the udid", parsed[2]["id"], "AB21889A-A9DD")
    check("drops incompatible rows",
          [d for d in parsed if "error" in d], [])
    check("empty input is empty, not an exception", parse_destinations(""), [])


# ---- product resolution -------------------------------------------------

def test_product():
    print("product resolution")
    settings = {
        "TARGET_BUILD_DIR": "/dd/Build/Products/Debug-iphonesimulator",
        "BUILT_PRODUCTS_DIR": "/dd/Build/Products/Debug-iphonesimulator",
        "FULL_PRODUCT_NAME": "DemoApp.app",
        "PRODUCT_BUNDLE_IDENTIFIER": "com.example.demo",
    }
    check("joins TARGET_BUILD_DIR and FULL_PRODUCT_NAME",
          resolve_product(settings)["appPath"],
          "/dd/Build/Products/Debug-iphonesimulator/DemoApp.app")

    # A custom CONFIGURATION_BUILD_DIR moves TARGET_BUILD_DIR away from the
    # shared collection point; the target's own directory is the correct one.
    moved = dict(settings, TARGET_BUILD_DIR="/custom/out")
    check("prefers TARGET_BUILD_DIR over BUILT_PRODUCTS_DIR",
          resolve_product(moved)["appPath"], "/custom/out/DemoApp.app")

    fallback = {k: v for k, v in settings.items() if k != "TARGET_BUILD_DIR"}
    check("falls back to BUILT_PRODUCTS_DIR",
          resolve_product(fallback)["appPath"],
          "/dd/Build/Products/Debug-iphonesimulator/DemoApp.app")

    try:
        resolve_product({"FULL_PRODUCT_NAME": "X.app"})
        check("raises when no build dir", "no exception", "BuildError")
    except build_util.BuildError:
        check("raises when no build dir", "BuildError", "BuildError")


# ---- diagnostics --------------------------------------------------------

def test_source_location():
    print("diagnostic source locations")
    url = ("file:///p/App.swift#EndingColumnNumber=31&EndingLineNumber=26"
           "&StartingColumnNumber=31&StartingLineNumber=26&Timestamp=811048236.3")
    loc = _source_location(url)
    # Line and column live in the URL fragment, not in any JSON field.
    check("extracts the file", loc["file"], "/p/App.swift")
    check("extracts the line", loc["line"], "26")
    check("extracts the column", loc["column"], "31")
    check("tolerates a missing url", _source_location(None), None)
    check("tolerates a url with no fragment",
          _source_location("file:///p/App.swift")["line"], None)


def test_text_fallback():
    print("text fallback extraction")
    stdout = ("Build settings from command line:\n"
              "    SDKROOT = iphoneos\n"
              "error: exportArchive No signing certificate \"iOS Development\" found\n"
              "** EXPORT FAILED **\n")
    found = text_fallback_errors(stdout)
    check("pulls the error line", found,
          ['exportArchive No signing certificate "iOS Development" found'])
    check("deduplicates repeats",
          text_fallback_errors("error: same\nerror: same\n"), ["same"])
    check_true("falls back to trailing lines when no error: marker",
               text_fallback_errors("no marker here\nlast line\n"))


# ---- signing taxonomy ---------------------------------------------------

def test_classify():
    print("signing failure classification")
    cases = [
        ('error: exportArchive No signing certificate "iOS Development" found',
         "no-matching-identity"),
        ('Signing for "DemoApp" requires a development team.', "no-development-team"),
        ("Your build settings specify a provisioning profile with the UUID "
         "\"ABC\", however, no such provisioning profile was found.",
         "stale-profile-uuid"),
        ("error: No profiles for 'com.x.y' were found: Xcode couldn't find any "
         "iOS App Development provisioning profiles matching the bundle identifier",
         "profile-not-installed"),
        ("mismatch between specified provisioning profile and signing identity",
         "identity-profile-mismatch"),
        ("The file couldn't be opened because it isn't in the correct US-ASCII format",
         "non-utf8-locale"),
    ]
    for message, expected in cases:
        hits = [h["category"] for h in classify(message)]
        check("classifies %-24s" % expected, expected in hits, True)

    check("unknown text classifies to nothing",
          classify("something entirely unrelated happened"), [])


# ---- platform expectations ---------------------------------------------

def test_platform_expectations():
    print("platform expectation table")
    from package_products import EXPECTED
    # The trap this guards: a SwiftPM build that accepted an iOS triple, exited
    # 0 and emitted MACOS. "MACOS" must never satisfy an ios expectation.
    check("ios is not satisfied by MACOS", "MACOS" in EXPECTED["ios"], False)
    check("ios is satisfied by IOS", "IOS" in EXPECTED["ios"], True)
    check("ios-simulator accepts IOSSIMULATOR",
          "IOSSIMULATOR" in EXPECTED["ios-simulator"], True)


def main():
    print("ios-build-engineer self-test (offline)\n")
    for test in (test_destinations, test_product, test_source_location,
                 test_text_fallback, test_classify, test_platform_expectations):
        test()
        print()
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
