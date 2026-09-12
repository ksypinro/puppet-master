# Recovery and safety

Use this guide after an inconclusive action, unhealthy observation, target loss, or before a sensitive/destructive operation.

## Preserve evidence first

Before recovery, retain:

- target UDID and boot identity if available;
- foreground bundle and app process state;
- pre-action snapshot/screenshot;
- intended action and postcondition;
- raw driver receipt, exit status, stdout/stderr;
- fresh post-action snapshot/screenshot;
- bounded log delta.

Do not recover in a way that destroys the evidence needed to determine whether the action committed.

## Failure classes and responses

### `STALE_SNAPSHOT`

The screen, orientation, boot identity, or driver session changed after the target was selected.

Response: do not dispatch. Observe again and re-resolve the target. Never reuse old refs.

### `AMBIGUOUS_SELECTOR`

More than one element matches.

Response: narrow by identifier, role/type, ancestor/scope, label/value, or current frame. Return compact candidates when human choice is needed. Do not choose the first match.

### `NOT_ACTIONABLE`

The target is disabled, hidden, clipped, covered, off-screen, or has no compatible action.

Response: inspect screenshot; dismiss a transient overlay if within scope; scroll the relevant container; wait for enablement; or target the child control. Do not tap its stale frame.

### `FOCUS_OR_KEYBOARD`

Typed text went nowhere, appended unexpectedly, used the wrong keyboard, or the field is secure.

Response: observe focus, tap the field, clear using a verified fill/set-value operation when possible, then enter text. Verify the exact value for ordinary fields. For secure fields, verify masked state or the next enabled action without extracting the secret. Switch from AXe when non-ASCII input is required.

### `AX_UNREADY_OR_SPARSE`

The accessibility tree is empty, zero-sized, incomplete, or contradicts the screenshot.

Response order:

1. Poll a bounded readiness predicate.
2. Refresh the snapshot and foreground app.
3. Relaunch the app if evidence shows the action cannot have committed or the app is not frontmost.
4. Restart the driver session.
5. Use a screenshot-guarded coordinate action only for an unambiguous, safe target.
6. Reboot the Simulator only if ordinary recovery failed and doing so will not destroy required state.

Do not toggle undocumented accessibility defaults as blind recovery.

### `POSTCONDITION_FAILED`

The event was dispatched, but the intended state did not appear.

Response: compare pre/post state and logs. If unchanged and the action is idempotent, one bounded retry with a fresh target may be reasonable. If state changed unexpectedly, re-plan. Do not repeatedly tap.

### `DISPATCH_UNCERTAIN`

The driver timed out or disconnected after the event may have been delivered.

Response: observe only. Never automatically replay a potentially consequential action. Ask for direction if evidence cannot establish the state.

### `APP_CRASHED`

Response: save screenshot/log/crash evidence, identify the crash, and relaunch only if continuing is within scope. Do not hide the crash by repeatedly relaunching.

### `DRIVER_UNHEALTHY`

Response: perform a read-only health probe, restart only that adapter/session, then re-observe. Fall back to the next viable driver when a version compatibility probe fails. Do not mix coordinate systems or refs across adapters.

### `TARGET_LOST`

The Simulator shut down, rebooted, was deleted, or changed boot identity.

Response: invalidate the session, refs, screen hashes, and pending actions. Rediscover the exact UDID. Reboot only if within scope, then re-establish the app and driver state.

## Recovery escalation

Use the least disruptive effective step:

1. Fresh semantic observation and screenshot.
2. Wait for a precise predicate.
3. Dismiss an in-scope transient keyboard/alert/overlay.
4. Re-resolve the element and retry one proven-idempotent action.
5. Relaunch the app.
6. Restart the driver.
7. Reboot the Simulator.
8. Erase/recreate only with explicit authority and after preserving artifacts.

Fixed sleeps may help an animation finish but never prove readiness. Prefer bounded predicate polling.

## Consequence rules

Ordinary Simulator interactions are not automatically harmless. Treat these as consequential unless the user clearly placed them in scope:

- submitting forms to a real service;
- sending messages, notifications, posts, emails, or invitations;
- purchases, subscriptions, transfers, or Apple Pay flows;
- creating/deleting accounts or data;
- permission decisions with lasting test consequences;
- destructive in-app actions;
- uninstalling an app, resetting its container, or erasing a Simulator.

Before a consequential action, make the target account/environment and expected effect explicit. Prefer test fixtures, mock services, and debug launch arguments. A request to navigate or test does not automatically authorize a real external side effect.

Never retry a consequential action merely because the UI did not visibly advance. First determine whether it committed through semantic state, logs, app/backend state, or user direction.

## Sensitive data

- Minimize screenshots and logs that contain credentials, tokens, personal data, customer content, or payment details.
- Do not echo secrets in command lines. Use a protected input channel supported by the selected driver.
- Keep raw evidence in a task-owned directory with appropriate access; return redacted summaries when possible.
- Do not infer or expose secure-field contents from screenshots, accessibility state, logs, or memory.
- Remove or retain artifacts according to the user's policy; do not silently delete evidence needed for the task.

## Stop conditions

Stop and report a blocker when:

- no UI-input driver is available and installation was not authorized;
- multiple Simulators remain plausible and mutation would risk the wrong target;
- the target is only visually guessable and the action is consequential;
- AX and pixels materially disagree after bounded recovery;
- the same safe recovery path fails repeatedly;
- continuation requires signing, credentials, code changes, Simulator erase, or external side-effect authority not already granted.
