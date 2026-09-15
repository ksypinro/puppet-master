#!/usr/bin/env python3
"""Read code-signing state, and classify a signing or export failure.

Read-only. This script never changes signing configuration, never contacts the
Developer Portal, and never passes -allowProvisioningUpdates: those mutate
shared team state and belong to a person, not to an agent.

    python3 signing_doctor.py identities
    python3 signing_doctor.py profiles
    python3 signing_doctor.py inspect --app /abs/App.app
    python3 signing_doctor.py classify --message "No signing certificate ..."
"""

from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
from pathlib import Path

from build_util import BuildError, emit, run

IDENTITY = re.compile(r'^\s*\d+\)\s+([0-9A-F]{40})\s+"(.+?)"(?:\s+\((.+?)\))?\s*$', re.M)
PARENTHETICAL = re.compile(r"\(([^)]+)\)\s*$")
OU = re.compile(r"organizationalUnitName\s*=\s*(\S+)")
UID = re.compile(r"userId\s*=\s*(\S+)")

PROFILE_DIRS = [
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
]


# ---------------------------------------------------------------- identities

def certificate_subject(common_name):
    """Pull the certificate subject so the real Team ID can be read.

    The parenthetical inside the common name is NOT the Team ID; the Team ID is
    the organizationalUnitName. A single certificate can carry three different
    ten-character identifiers, and picking the wrong one produces signing
    configuration that looks right and is not.
    """
    pem = run(["security", "find-certificate", "-c", common_name, "-p"])
    if pem.returncode != 0 or not pem.stdout.strip():
        return {}
    try:
        subject = subprocess.run(
            ["openssl", "x509", "-noout", "-subject", "-nameopt", "multiline"],
            input=pem.stdout, capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    team = OU.search(subject)
    uid = UID.search(subject)
    return {
        "teamId": team.group(1) if team else None,
        "userId": uid.group(1) if uid else None,
    }


def cmd_identities(args):
    proc = run(["security", "find-identity", "-v", "-p", "codesigning"])
    identities = []
    for sha1, name, note in IDENTITY.findall(proc.stdout):
        paren = PARENTHETICAL.search(name)
        entry = {
            "sha1": sha1,
            "commonName": name,
            "status": note or "valid",
            "usable": not note,
            "commonNameParenthetical": paren.group(1) if paren else None,
        }
        entry.update(certificate_subject(name))
        identities.append(entry)

    by_name = {}
    for entry in identities:
        by_name.setdefault(entry["commonName"], []).append(entry["sha1"])
    ambiguous = {k: v for k, v in by_name.items() if len(v) > 1}
    usable = [e for e in identities if e["usable"]]

    emit({
        "ok": True,
        "identities": identities,
        "usableCount": len(usable),
        "unusableCount": len(identities) - len(usable),
        "ambiguousCommonNames": ambiguous,
        "rules": [
            "Select an identity by SHA-1. Common names are not unique, so "
            "CODE_SIGN_IDENTITY=\"Apple Development\" cannot disambiguate them.",
            "The Team ID is the certificate's organizationalUnitName, not the "
            "parenthetical in the common name.",
            "Reject any identity whose status is not 'valid' — revoked certificates "
            "are listed alongside working ones.",
        ],
    })


# ---------------------------------------------------------------- profiles

def read_profile(path):
    """A .mobileprovision is CMS-wrapped; security cms -D unwraps the plist."""
    proc = run(["security", "cms", "-D", "-i", str(path)], timeout=60)
    if proc.returncode != 0 or not proc.stdout:
        return {"path": str(path), "readable": False}
    try:
        data = plistlib.loads(proc.stdout.encode("utf-8", "replace"))
    except Exception:
        return {"path": str(path), "readable": False}
    entitlements = data.get("Entitlements", {}) or {}
    return {
        "path": str(path),
        "readable": True,
        "name": data.get("Name"),
        "uuid": data.get("UUID"),
        "teamIdentifier": (data.get("TeamIdentifier") or [None])[0],
        "appIdName": data.get("AppIDName"),
        "applicationIdentifier": entitlements.get("application-identifier"),
        "getTaskAllow": entitlements.get("get-task-allow"),
        "expirationDate": data.get("ExpirationDate"),
        "provisionedDeviceCount": len(data.get("ProvisionedDevices") or []),
        "provisionsAllDevices": bool(data.get("ProvisionsAllDevices")),
        "platforms": data.get("Platform"),
    }


def cmd_profiles(args):
    profiles = []
    for folder in PROFILE_DIRS:
        if folder.is_dir():
            for path in sorted(folder.glob("*.mobileprovision")):
                profiles.append(read_profile(path))
    emit({
        "ok": True,
        "searched": [str(p) for p in PROFILE_DIRS],
        "count": len(profiles),
        "profiles": profiles,
        "note": ("a device install needs a profile whose application-identifier matches "
                 "the app's bundle id and whose ProvisionedDevices includes the target "
                 "UDID; get-task-allow must be true to attach a debugger"),
    })


# ---------------------------------------------------------------- inspect

def cmd_inspect(args):
    app = Path(args.app).resolve()
    if not app.exists():
        raise BuildError("not found: %s" % app)

    signature = run(["codesign", "-dv", "--verbose=4", str(app)], timeout=120)
    blob = signature.stderr or signature.stdout
    fields = {}
    for line in blob.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields.setdefault(key.strip(), value.strip())

    verify = run(["codesign", "--verify", "--deep", "--strict", str(app)], timeout=300)
    entitlements = run(
        ["codesign", "-d", "--entitlements", ":-", str(app)], timeout=120
    )
    parsed_entitlements = None
    if entitlements.returncode == 0 and entitlements.stdout.strip():
        try:
            parsed_entitlements = plistlib.loads(
                entitlements.stdout.encode("utf-8", "replace")
            )
        except Exception:
            parsed_entitlements = {"raw": entitlements.stdout[:2000]}

    embedded = app / "embedded.mobileprovision"
    emit({
        "ok": True,
        "app": str(app),
        "signed": "Signature size" in blob or fields.get("Signature") is not None,
        "identifier": fields.get("Identifier"),
        "teamIdentifier": fields.get("TeamIdentifier"),
        "authority": [l.split("=", 1)[1] for l in blob.splitlines()
                      if l.startswith("Authority=")],
        "format": fields.get("Format"),
        "verifyPassed": verify.returncode == 0,
        "verifyOutput": (verify.stderr or verify.stdout).strip()[-1200:] or None,
        "entitlements": parsed_entitlements,
        "embeddedProfile": read_profile(embedded) if embedded.exists() else None,
        "note": ("TeamIdentifier here comes from the certificate OU and is the value to "
                 "compare against a profile's TeamIdentifier"),
    })


# ---------------------------------------------------------------- classify

# Signatures observed in real build and export output. The export lane is the
# reason this table exists: exportArchive writes no result bundle on failure, so
# its text is the only diagnosis available.
TAXONOMY = [
    ("stale-profile-uuid",
     r"build settings specify a provisioning profile with the UUID",
     "The project pins a profile UUID that is not installed.",
     "Remove the hard-coded PROVISIONING_PROFILE/UUID or install that exact profile."),
    ("profile-bundle-id-mismatch",
     r"Provisioning profile .*does not match|doesn't match the bundle identifier",
     "The profile's application-identifier does not match the app's bundle id.",
     "Compare signing_doctor.py profiles against PRODUCT_BUNDLE_IDENTIFIER."),
    ("profile-not-installed",
     r"provisioning profiles matching the bundle identifier|matching the bundle identifier .* were found",
     "No locally installed profile covers this bundle id.",
     "Install the profile, or build for Simulator, which needs none."),
    ("no-development-team",
     r"requires a development team",
     "Automatic signing is on and DEVELOPMENT_TEAM is unset.",
     "Set DEVELOPMENT_TEAM, or build unsigned with CODE_SIGNING_ALLOWED=NO."),
    ("no-matching-identity",
     r"No signing certificate .* found|no signing identity matches",
     "No usable certificate for the requested distribution method. The quoted "
     "name can be a legacy spelling such as \"iOS Development\" that appears "
     "nowhere in the export options, so do not map it back to the method.",
     "signing_doctor.py identities — check for revoked certificates."),
    ("identity-profile-mismatch",
     r"mismatch between specified provisioning profile and signing identity",
     "The chosen certificate is not the one the profile was issued against.",
     "Match the identity's Team ID (certificate OU) to the profile's TeamIdentifier."),
    ("profile-required",
     r"requires a provisioning profile|Code signing is required for product",
     "A device build or export needs a profile and none was supplied.",
     "Supply provisioningProfiles in the export options, or disable signing for a "
     "compile-only check."),
    ("codesign-verification-failed",
     r"Codesign check fails|code object is not signed at all|invalid signature",
     "The produced bundle failed signature verification.",
     "Re-sign with CODESIGN_ALLOCATE set; check nested frameworks are signed too."),
    ("non-utf8-locale",
     r"US-ASCII|ASCII_CONVERSION",
     "A non-UTF-8 LANG/LC_ALL is corrupting build input.",
     "export LANG=en_US.UTF-8 and rebuild."),
    ("device-unavailable",
     r"Unable to find a destination|does not support|Developer Mode disabled|device is locked",
     "The destination cannot currently accept the build or install.",
     "Check pairing, Developer Mode, and that the device is unlocked."),
]


def classify(message):
    hits = []
    for name, pattern, meaning, remedy in TAXONOMY:
        if re.search(pattern, message, re.I):
            hits.append({"category": name, "meaning": meaning, "remedy": remedy})
    return hits


def cmd_classify(args):
    text = args.message
    if args.file:
        text = Path(args.file).read_text(errors="replace")
    if not text:
        raise BuildError("pass --message or --file")
    hits = classify(text)
    emit({
        "ok": True,
        "matches": hits,
        "unclassified": not hits,
        "guidance": ("no match means the text is outside the observed taxonomy — report "
                     "the raw message rather than forcing it into a category")
                    if not hits else None,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("identities").set_defaults(func=cmd_identities)
    sub.add_parser("profiles").set_defaults(func=cmd_profiles)
    p = sub.add_parser("inspect"); p.add_argument("--app", required=True)
    p.set_defaults(func=cmd_inspect)
    p = sub.add_parser("classify")
    p.add_argument("--message", default="")
    p.add_argument("--file", help="read the message text from a file")
    p.set_defaults(func=cmd_classify)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2)
