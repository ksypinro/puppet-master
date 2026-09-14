# Signing, provisioning, and export

This skill reads signing state and classifies failures. It does not change
signing configuration and never contacts the Developer Portal.

## Authority

`-allowProvisioningUpdates` lets `xcodebuild` **create and modify** certificates,
App IDs and provisioning profiles on the Developer Portal.
`-allowProvisioningDeviceRegistration` registers the destination device. Both
mutate state shared by everyone on the team, from a command that looks like a
build. Never pass either implicitly. If a user's problem genuinely needs one,
say so, name the change it would make, and let them run it.

Reading is unrestricted: identities, profiles, entitlements and a built bundle's
signature are all safe to inspect.

## Which lane actually needs signing

| Lane | Identity | Profile |
|---|---|---|
| Build and run on Simulator | no | no |
| Compile / link for device | no | no |
| Install on physical hardware | **yes** | **yes** |
| Export an `.ipa` | **yes** | **yes** |

Do not report a signing problem to a user whose task is Simulator-only.
`build_doctor.py` reports these three lanes separately for this reason.

## Reading identities correctly

```sh
security find-identity -v -p codesigning
```

Two traps, both observed on a real keychain that held five identities sharing a
single common name with four of them revoked.

**Names are not unique.** `CODE_SIGN_IDENTITY="Apple Development"` cannot
disambiguate five certificates with that name. Select by SHA-1. Revoked
certificates are listed inline with `(CSSMERR_TP_CERT_REVOKED)` — parse and
reject them rather than letting the build pick one.

**The parenthetical is not the Team ID.** One certificate carried three
different ten-character identifiers:

| Field | Example | What it is |
|---|---|---|
| common-name parenthetical | `3ZL9H34Z69` | *not* the team — the value most scripts grep |
| `organizationalUnitName` (OU) | `J8UL7XJ533` | **the Team ID**, matching `codesign`'s `TeamIdentifier` |
| `userId` (UID) | `Z7SV45R6A5` | certificate subject id |

```sh
security find-certificate -c "<common name>" -p \
  | openssl x509 -noout -subject -nameopt multiline | grep organizationalUnitName
```

`signing_doctor.py identities` reports all three plus revocation and ambiguity.

## Profiles

A `.mobileprovision` is CMS-wrapped; `security cms -D -i <file>` unwraps the
plist. What matters for an install:

- `application-identifier` must match the app's bundle id (allowing a wildcard).
- `ProvisionedDevices` must contain the target UDID, unless
  `ProvisionsAllDevices` is set.
- `TeamIdentifier` must match the signing certificate's OU.
- `get-task-allow` must be true to attach a debugger.
- `ExpirationDate` must be in the future.

`signing_doctor.py profiles` reports each of these.

## Export has no structured diagnostics

```sh
xcodebuild -exportArchive -archivePath App.xcarchive -exportPath out \
  -exportOptionsPlist export.plist -resultBundlePath exp.xcresult
```

On failure this exits 70 and creates **no result bundle at all**, even though
`-resultBundlePath` was supplied. The same flag produces full structure for
`build`. Text classification is the only option, and it must be labelled as
weaker evidence.

The text is also actively misleading. With the Xcode 27 spelling
`method = debugging`, the failure reads:

```
error: exportArchive No signing certificate "iOS Development" found
```

`"iOS Development"` is the pre-Xcode-11 identity name and appears nowhere in the
export plist. Read it as "no usable certificate and profile pair for this
method"; do not map it back to the requested distribution method.

## The failure taxonomy

`signing_doctor.py classify` maps observed text to these categories. An
unmatched message is reported as unclassified rather than forced into one.

| Category | Meaning |
|---|---|
| `stale-profile-uuid` | The project pins a profile UUID that is not installed |
| `profile-bundle-id-mismatch` | Profile's App ID does not match the bundle id |
| `profile-not-installed` | No local profile covers this bundle id |
| `no-development-team` | Automatic signing on, `DEVELOPMENT_TEAM` unset |
| `no-matching-identity` | No usable certificate for the requested method |
| `identity-profile-mismatch` | Certificate was not issued against that profile |
| `profile-required` | Device build or export needs a profile, none supplied |
| `codesign-verification-failed` | The produced bundle failed verification |
| `non-utf8-locale` | `LANG`/`LC_ALL` is not UTF-8, surfacing as `US-ASCII` |
| `device-unavailable` | Pairing, Developer Mode, or lock state blocks the target |

## Signing without xcodebuild

```sh
CODESIGN_ALLOCATE=$(xcrun --find codesign_allocate) \
  codesign -v --sign <SHA1> [--entitlements ent.plist] [--force] [--timestamp=none] <bundle>
```

Setting `CODESIGN_ALLOCATE` explicitly is the step hand-rolled scripts usually
omit. Nested frameworks must be signed before the enclosing bundle. Verify with
`codesign --verify --deep --strict`, which `signing_doctor.py inspect` runs.

## Unsigned archives are still useful

`xcodebuild archive` with signing disabled produces a complete `.xcarchive`
including dSYMs and `Info.plist/ApplicationProperties`. That is enough for
artifact manifests, binary and dSYM UUID capture, and symbol archival — with no
credentials at all.
