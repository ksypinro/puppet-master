# Reusable controller contract

Use this when implementing an MCP server, CLI facade, service, or AXe-like stack for LLM-driven Simulator control.

## Architecture

Own the contract and state machine; treat Apple CLIs, XCTest, AXe, idb, WDA, and future transports as replaceable adapters.

1. **Capability discovery** — Xcode/macOS/runtime versions, available targets, installed drivers, feature probes, and schema/help fingerprints.
2. **Target lease** — exclusive mutation ownership, heartbeat, boot identity, cancellation, and orphan recovery.
3. **Lifecycle adapter** — boot/readiness, install, launch, terminate, URL/environment/test state.
4. **Observer** — accessibility snapshot, screenshot, orientation, foreground app, logs, and health.
5. **UI driver** — tap/fill/type/swipe/scroll/long-press/drag/slider/button with dispatch receipts.
6. **Synchronizer** — predicate waits, monotonic deadlines, settled-layout detection, and cancellation.
7. **Verifier** — compare fresh state to the declared postcondition; dispatch alone is provisional.
8. **Artifact plane** — immutable raw/normalized evidence, hashes, timestamps, redaction, and retention metadata.
9. **Recovery engine** — failure classification plus bounded escalation; no unsafe automatic replay.
10. **LLM facade** — a small structured tool catalog, compact snapshot refs, typed errors, and safe next-action hints.

## Target state machine

```text
unavailable -> discovered -> leased -> booting -> ready
ready -> app-installed -> app-running -> driver-ready
driver-ready -> observed -> action-dispatched -> verifying -> observed
any -> collecting-evidence -> recovering -> observed | quarantined
leased -> released
```

Invariants:

- Only the lease owner mutates a target.
- Every action names its pre-snapshot and postcondition.
- A boot/session/orientation change invalidates snapshot refs.
- An ambiguous timeout never triggers automatic replay.
- Raw adapter output is retained when normalization fails.

## Snapshot envelope

```json
{
  "schema": "ios.control.screen-snapshot",
  "schemaVersion": 1,
  "target": {
    "kind": "simulator",
    "udid": "<UUID>",
    "runtime": "<runtime-id>",
    "bootIdentity": "<opaque>",
    "orientation": "portrait",
    "viewportPoints": {"width": 402, "height": 874}
  },
  "screen": {
    "sequence": 42,
    "hash": "sha256:<digest>",
    "foregroundBundle": "com.example.App"
  },
  "elements": [
    {
      "ref": "e12",
      "role": "button",
      "id": "login.submit",
      "label": "Sign In",
      "value": null,
      "frame": {"x": 24, "y": 620, "width": 354, "height": 50},
      "state": {"enabled": true, "visible": true, "focused": false},
      "actions": ["tap"]
    }
  ],
  "artifacts": {
    "rawAccessibility": "/absolute/path/ax-42.json",
    "screenshot": "/absolute/path/screen-42.png",
    "logCursor": "<opaque>"
  }
}
```

Default snapshots should return visible interactive elements plus compact context. Allow explicit full-tree expansion. When a prior screen hash is provided, return a diff or a small `notModified` response. Refs are valid only within one target, boot identity, driver session, and snapshot generation.

## Action request

```json
{
  "schema": "ios.control.action-request",
  "schemaVersion": 1,
  "actionId": "a91",
  "leaseId": "lease-7",
  "target": {"udid": "<UUID>", "bootIdentity": "<opaque>"},
  "precondition": {"screenHash": "sha256:<digest>", "refExists": "e12"},
  "action": {"kind": "tap", "ref": "e12"},
  "postcondition": {
    "all": [
      {"exists": {"id": "home.title"}},
      {"notExists": {"id": "login.submit"}}
    ],
    "timeoutMs": 5000
  }
}
```

All actions should support an idempotency/consequence classification. Coordinate actions additionally require current orientation, viewport, screen hash, coordinate space, and a semantic/visual guard.

## Action result

```json
{
  "schema": "ios.control.action-result",
  "schemaVersion": 1,
  "actionId": "a91",
  "dispatch": "accepted",
  "verified": true,
  "attempts": 1,
  "postSnapshotSequence": 43,
  "artifacts": {
    "pre": "/absolute/path/screen-42.json",
    "post": "/absolute/path/screen-43.json",
    "screenshot": "/absolute/path/screen-43.png",
    "logDelta": "/absolute/path/logs-a91.ndjson"
  }
}
```

Keep `dispatch` and `verified` separate. Include the last observation and a safe next action when verification fails.

## Structured errors

- `STALE_SNAPSHOT` — screen/session/boot state changed; refresh, do not dispatch.
- `AMBIGUOUS_SELECTOR` — multiple candidates; return compact candidates.
- `NOT_ACTIONABLE` — hidden, disabled, clipped, covered, or unsupported action.
- `AX_UNREADY` — semantic service returned an unusable hierarchy.
- `DISPATCH_UNCERTAIN` — event may have committed; observe, never auto-replay.
- `POSTCONDITION_FAILED` — dispatch succeeded but intended state is absent.
- `DRIVER_UNHEALTHY` — adapter/XPC/XCTest/WDA/HID path unavailable.
- `TARGET_LOST` — disconnect, reboot, deletion, or boot identity change.
- `POLICY_DENIED` — destructive/sensitive operation lacks authority.
- `CAPABILITY_UNAVAILABLE` — no qualified adapter implements the requested action.

Each error should include whether the action may have committed, evidence paths, retry safety, and concrete recovery choices.

## Qualification suite

Gate every supported macOS/Xcode/iOS/driver combination with tests for:

- discovery, boot readiness, lease conflict, launch, and foreground detection;
- populated/sparse AX snapshots, duplicate selectors, and ref invalidation;
- tap, fill, non-ASCII input, secure fields, swipe/scroll, long press, drag, slider, rotation, and hardware buttons;
- UIKit, SwiftUI, React Native, Flutter, WebView, custom drawing, system alerts, keyboards/IME, sheets, menus, long lists, Dynamic Type, and localization;
- screenshot dimensions/coordinate mapping and post-action visual evidence;
- animation/non-idling behavior, app crash, driver restart, Simulator reboot, and cancellation;
- ambiguous destructive-action timeout with proof that no replay occurs;
- redaction, retention, schema migration, and malformed raw adapter output.

Track action latency, snapshot size, verification success, retries, false positives, driver restarts, and failures by pinned environment fingerprint.

## Build-versus-reuse decision

Reuse AXe/idb when the need is a fast private Simulator bridge. Reuse XCTest/agent-device/WDA when device parity or supported semantics matter. Build the controller layers above them first. Reimplement CoreSimulator accessibility/HID internals only when measured requirements cannot be met by an isolated adapter and the maintenance cost across Xcode releases is accepted.
