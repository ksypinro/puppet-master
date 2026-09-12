# Driver guide

Read the general rules, then only the section for the selected adapter. Installed CLI help is authoritative when it differs from examples here.

## General rules

- Pass arguments as an argument vector when the host supports it. Do not construct commands by interpolating untrusted labels, paths, URLs, or text into shell source.
- Prefer JSON/structured output. Retain raw output when normalizing it.
- Use one explicit Simulator UDID throughout a run.
- A selector/ref action proves dispatch only unless the driver returns and satisfies a declared postcondition.
- Accessibility coordinates use logical screen points. Screenshot PNG dimensions may be physical pixels. Do not feed screenshot pixels directly to a point-based driver without confirming the scale.
- Capture screenshots to an absolute task-owned path. The bundled `scripts/capture_screenshot.py` refuses to overwrite unless `--force` is supplied and reports dimensions plus SHA-256.

## Apple lifecycle and evidence (`simctl`)

Use `simctl` even when another driver supplies UI input:

```bash
xcrun simctl list devices available -j
xcrun simctl boot <UDID>
xcrun simctl bootstatus <UDID> -b
xcrun simctl install <UDID> /absolute/path/App.app
xcrun simctl launch --terminate-running-process <UDID> com.example.App
xcrun simctl terminate <UDID> com.example.App
xcrun simctl io <UDID> screenshot /absolute/path/screen.png
```

Useful deterministic setup includes `openurl`, `push`, `location`, `privacy`, `addmedia`, `ui`, `status_bar`, `keychain`, pasteboard commands, and `spawn log`. Run `xcrun simctl help <subcommand>` before using a version-sensitive option.

Do not parse human `list` output when `-j` exists. Do not treat `boot` completion as UI readiness.

## Structured agent runtimes

### agent-device

Use a long-lived session. The installed help is the source of truth.

```bash
agent-device open com.example.App --platform ios --session <SESSION> --foreground
agent-device snapshot -i --session <SESSION> --json
agent-device press @e12 --session <SESSION> --settle --json
agent-device fill @e17 'user@example.test' --session <SESSION> --settle --json
agent-device longpress @e20 --session <SESSION> --settle --json
agent-device scroll down --session <SESSION> --settle --json
agent-device screenshot /absolute/path/final.png --session <SESSION>
agent-device close --session <SESSION>
```

- Start with `open`; it normally returns the initial interactive snapshot.
- Copy refs byte-for-byte, including `@` and any snapshot suffix.
- Use current refs only. Snapshot again when a diff lacks the next target.
- Prefer `fill` over manual clear/type and use `--settle` for mutating actions.
- If the snapshot says accessibility is unavailable or sparse, ignore its refs, inspect a screenshot, use a guarded coordinate only if supported, then retry semantic observation.
- Run `agent-device help <topic>` when a specialized gesture or exact flag is unclear.

### XcodeBuildMCP

Prefer its MCP tools when already connected. In CLI mode, use `--output json` and discover the shipped surface rather than guessing:

```bash
xcodebuildmcp tools
xcodebuildmcp simulator --help
xcodebuildmcp ui-automation --help
```

A current CLI flow has this shape:

```bash
xcodebuildmcp simulator build-and-run \
  --project-path ./App.xcodeproj --scheme App \
  --simulator-id <UDID> --output json
xcodebuildmcp ui-automation snapshot-ui \
  --simulator-id <UDID> --output json
xcodebuildmcp ui-automation tap \
  --simulator-id <UDID> --element-ref e12 --output json
```

- Set session defaults once when the connected tool surface supports them.
- Prefer build-and-run over separate build/install/launch unless artifacts must be controlled separately.
- Carry the screen hash/ref precondition returned by the runtime.
- Use `wait_for_ui`/its CLI equivalent for semantic predicates.
- Use the post-action compact snapshot and structured next steps rather than immediately repeating a full capture.
- A snapshot with only a zero-size application root is AX-unready even if the wrapper reports success. Poll readiness; if it persists, relaunch the app, restart the adapter, or fall back.
- Confirm exact names and flags with the installed `tools`/`--help`; XcodeBuildMCP evolves quickly.

## AXe

AXe is Simulator-only and uses private accessibility/HID integration. It is fast and does not require an XCTest session, but most actions are fire-and-forget.

Discover and observe:

```bash
axe list-simulators
axe describe-ui --udid <UDID>
axe describe-ui --point 120,240 --udid <UDID>
axe screenshot --output /absolute/path/screen.png --udid <UDID>
```

Prefer identifier, then a unique label narrowed by element type:

```bash
axe tap --id login.submit --wait-timeout 5 --udid <UDID>
axe tap --label 'Continue' --element-type Button --wait-timeout 5 --udid <UDID>
```

Text entry requires focus. AXe HID text uses the US keyboard layout and rejects unsupported non-ASCII characters:

```bash
axe tap --id login.email --udid <UDID>
axe type 'user@example.test' --udid <UDID>
```

Use `--stdin` or `--file` for complex/shell-sensitive text. Never print or stage secrets in a world-readable file.

Coordinate gestures use logical coordinates reported by `describe-ui`; AXe handles supported rotation/letterboxing conversion:

```bash
axe swipe --start-x 200 --start-y 700 --end-x 200 --end-y 250 \
  --duration 0.6 --udid <UDID>
axe touch -x 180 -y 420 --down --up --delay 1.2 --udid <UDID>
axe drag --start-x 80 --start-y 500 --end-x 310 --end-y 500 \
  --duration 0.8 --steps 60 --udid <UDID>
axe slider --id volume --value 75 --udid <UDID>
```

- `touch --down --up --delay` is a coordinate long press.
- `slider` re-reads its value; other action success means dispatch, not outcome.
- Selector waits are preferable to sleeps. Coordinate actions cannot wait for an element.
- A first `describe-ui` call can fail while the remote automation channel is starting. Preserve the error and allow one bounded read-only retry; continued failure is `DRIVER_UNHEALTHY`, not an empty screen.
- Use `axe batch` only for safe flows whose later selectors are freshly resolved. Set `--wait-timeout`; use `--ax-cache perStep` when the UI changes and no wait is active. Do not batch when the next action depends on screenshot/semantic analysis.
- If the current Xcode/iOS combination fails its AX/HID smoke test, disable AXe for that run and use the XCTest path.

## idb

idb exposes lower-level Simulator accessibility and HID primitives. It requires a working companion. Prefer exact identifier matches in your own normalization layer because idb marker matching can be substring-based.

```bash
idb ui describe-all --udid <UDID>
idb ui describe 'login.submit' --match-key AXUniqueId --udid <UDID>
idb ui tap 'login.submit' --match-key AXUniqueId \
  --expected-value 'Sign In' --expected-key AXLabel --udid <UDID>
idb ui set-value 'Email' --value 'user@example.test' --udid <UDID>
idb ui swipe 200 700 200 250 --duration 0.6 --udid <UDID>
idb ui tap 180 420 --duration 1.2 --udid <UDID>
idb ui text 'hello world' --udid <UDID>
```

- `describe-all`, element targeting, `scroll`, and `set-value` are accessibility operations.
- Coordinate tap/swipe/text are HID operations.
- A marker tap is an accessibility press, not necessarily a finger touch. Use coordinate HID when physical touch semantics matter.
- `--expected-value` is a useful guard, not a post-action verification.
- `axbridge-persistent` may reduce repeated read latency when the installed version supports it.

## Source-owned XCUIAutomation

Choose this for durable project tests, physical-device parity, or when private adapters are disallowed. A test runner can query `XCUIElement`, call `tap`, `typeText`, directional swipes, `press(forDuration:)`, coordinate press/drag, wait for existence, and attach screenshots.

For repeated runs, build once and run prepared tests:

```bash
xcodebuild build-for-testing \
  -workspace App.xcworkspace -scheme App \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /absolute/path/DerivedData

xcodebuild test-without-building \
  -workspace App.xcworkspace -scheme App \
  -destination 'platform=iOS Simulator,id=<UDID>' \
  -resultBundlePath /absolute/path/run.xcresult \
  -only-testing:AppUITests/AgentProbe/testExecuteScenario
```

Adding or changing a UI-test target is a project mutation; do it only when the user's request includes implementation. Keep accessibility identifiers stable and localization-independent.

## Appium/WebDriverAgent

Use this path when a persistent WebDriver session already exists, a remote client requires W3C WebDriver, or the wider task also targets physical devices. For a Simulator-only one-off task, it usually has more startup and state than the other adapters.

- Resolve elements by accessibility identifier first, then unique iOS predicate/class-chain selectors. Avoid broad XPath queries when a semantic selector is possible.
- Use the session's page source for semantic observation, the screenshot endpoint for pixels, element `sendKeys`/clear for fields, and W3C Actions for coordinate swipe, drag, and long press.
- Wait for explicit element/state predicates. Do not assume Appium's command response proves the app reached the intended screen.
- Preserve the session ID and capabilities with run evidence. A new session invalidates all element handles.
- Do not rebuild, re-sign, or reinstall WebDriverAgent merely as recovery unless the user's task authorizes environment changes.

## Screenshot inspection

1. Capture a PNG with `simctl`, the selected driver, or `scripts/capture_screenshot.py`.
2. Open it with the host's image-viewing capability at enough detail to read labels and detect overlays, clipping, keyboards, alerts, disabled states, and navigation changes.
3. Compare it with the semantic tree. If they disagree, treat the state as uncertain and investigate before acting.
4. Do not estimate coordinates from a rescaled chat preview. Use the original PNG dimensions and map pixels to logical points, or use the accessibility frame.
5. Record the screenshot path/hash with the action result; avoid embedding a new full-resolution image in every model turn unless visual reasoning is needed.

## Maintainer references

- Apple CLI truth: run the selected Xcode's `xcrun simctl help` and `xcodebuild -help`.
- XCUIAutomation: <https://developer.apple.com/documentation/xcuiautomation>
- AXe commands and agent guidance: <https://www.axe-cli.com/docs/command-reference>
- XcodeBuildMCP live tool reference: <https://www.xcodebuildmcp.com/docs/tools>
- agent-device project and installed-help policy: <https://github.com/callstack/agent-device>
- idb UI automation: <https://fbidb.io/docs/idb/ui/>
- Appium XCUITest driver: <https://appium.github.io/appium-xcuitest-driver/latest/>
