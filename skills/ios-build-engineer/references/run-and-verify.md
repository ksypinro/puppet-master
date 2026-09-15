# Running an app, and proving it is running

Verified on Simulator against Xcode 27.0. The physical-device lane is documented
from Apple's material and this skill's own command surface; it is **not**
verified by fixtures.

## Launch success is not app liveness

An app that calls `fatalError()` during `onAppear`:

```
xcrun simctl launch <udid> com.example.app        → "com.example.app: 86120"   exit 0
xcrun devicectl device process launch …           → "Launched application …"   exit 0
```

Both report success for an app that is already dead. The exit code proves
**dispatch**, not execution. This is the single most consequential trap in the
run lane, because every naive script treats exit 0 as "it works".

## The probe that works

```sh
xcrun simctl spawn <udid> launchctl list | grep "UIKitApplication:<bundle-id>"
# healthy → "86349   0   UIKitApplication:com.example.app[b3b3][rb-legacy]"
# crashed → no output
```

Column 2 is the last exit status. Verified in both directions: a healthy app
matches, a crash-on-launch app does not. `pgrep -fl "<AppName>.app/<AppName>"`
on the host also works, because Simulator app processes are ordinary host
processes.

**`devicectl device info processes` cannot substitute.** Against a simulator it
listed 858 processes and zero matches for an app `launchctl` showed running.
Simulator liveness must come from `simctl`.

## Console streaming has two traps

**It only connects stdio when it starts the process.** Launching an app that is
already running exits 0 with a completely empty log — indistinguishable from
"the app printed nothing". Always terminate first, or pass
`--terminate-existing` on the `devicectl` side.

**`--console-pty` owns the app's lifetime.** Measured with the probe above:

```
console process alive   → app running
console process killed  → app gone
plain launch, 5s later  → app still running
```

So "stream the log" and "leave the app up for UI driving" cannot be the same
command. If a console is bounded with a kill and liveness is checked *after*,
a perfectly healthy app reads as a crash. `build_run.py` probes inside the read
loop for exactly this reason.

A further subtlety when reading that stream: `select()` polls the OS descriptor,
but a buffered text stream can hold complete lines that `select()` no longer
reports as ready. Read the raw descriptor non-blocking and split lines manually,
or output silently truncates.

## Arguments and environment

```sh
# Simulator — environment goes through the SIMCTL_CHILD_ prefix
SIMCTL_CHILD_MY_VAR=value xcrun simctl launch --console-pty <udid> <bundle-id> --arg1 k=v

# Device — JSON dictionary, or host vars prefixed DEVICECTL_CHILD_
xcrun devicectl device process launch --device <udid> --console --terminate-existing \
  -e '{"MY_VAR":"value"}' --json-output out.json <bundle-id> --arg1 k=v
```

Both verified to deliver argv and environment to the app. `-e` overrides any
`DEVICECTL_CHILD_` variables.

## Simulator lifecycle

```sh
xcrun simctl bootstatus <udid> -b      # boots if needed, then WAITS; returns at once if booted
xcrun simctl install <udid> /path/App.app
xcrun simctl terminate <udid> <bundle-id>
```

`simctl create NAME TYPE` writes the UDID to stdout and its informational notice
("No runtime specified, using …") to **stderr**. Capturing with `2>&1` prepends
that notice and breaks naive parsing; `$(… 2>/dev/null)` is clean.
`simctl list devices|runtimes|devicetypes -j` are all proper JSON.

## The physical-device lane

```sh
xcrun devicectl list devices --json-output devices.json
xcrun devicectl device install app --device <udid> /path/App.app --json-output install.json
xcrun devicectl device process launch --device <udid> --terminate-existing \
  --json-output launch.json <bundle-id>
```

`devicectl` states in its own help that **JSON written to a file is the only
supported scripting interface** and that stdout is not stable across releases.
Honour that: pass `--json-output` and read the file. The launch pid is at
`result.process.processIdentifier`.

Prerequisites, in the order they fail: pairing and trust → Developer Mode enabled
→ device unlocked → app signed by a usable identity → an embedded provisioning
profile whose App ID matches and whose device list includes this UDID →
CoreDevice services reachable.

Two things to know about `devicectl` in Xcode 27:

- It lists **simulators** as well as hardware, distinguished by
  `hardwareProperties.reality == "simulated"`. Treating every row as a device is
  a live bug.
- Against a simulator, `install app`, `process launch` and
  `capture screenshot` all work. Process enumeration does not.

Report a device launch as **dispatched**, never as running, until a liveness
probe exists for that lane.

## First-launch failure modes

An app that installs and then dies immediately is usually one of: a missing
entitlement for a capability it uses at startup, a required device capability the
target does not have, a dynamic library that failed to load, or a crash in an
`onAppear`/`applicationDidFinishLaunching` path. The launcher reports none of
these. Get the console output with a bounded `--console` run, and if the crash is
inside app code, hand off to `lldb-code-state-debugger` with the UDID, bundle id
and app path preserved.
