# Dependencies

A complete audit of what these skills need, why, and what happens without it.

**Summary: zero third-party Python packages.** `install.sh` downloads nothing and needs no package manager. Everything required is either already on a Mac with Xcode, or is an optional driver you install yourself.

Check this machine:

```bash
python3 tools/doctor.py
```

## Required

| Dependency | Version | Why | Without it |
|---|---|---|---|
| **macOS** | any current | Xcode toolchain is macOS-only | Nothing works |
| **Python** | 3.9+ | All helper scripts | Nothing works |
| **Full Xcode** | 14+ recommended | `xcrun`, `simctl`, `xcodebuild`, `lldb` | Nothing works |

### Python 3.9 is the floor, and it is already installed

Every script imports the **standard library only**. The audited import set across all four skills:

```
argparse  collections  copy  dataclasses  datetime  difflib  fcntl  hashlib
importlib  json  math  os  pathlib  platform  random  re  secrets  selectors
shlex  shutil  signal  socket  statistics  struct  subprocess  sys  tempfile
threading  time  types  typing  unittest  uuid  xml
```

The only non-stdlib import is `lldb`, which is provided by Xcode's embedded Python inside the LLDB process — not from PyPI, and not something you install. `lldb-code-state-debugger` is deliberately split for this reason: the client runs on your `python3` using stdlib only, and the worker runs inside LLDB's own interpreter. That avoids the system-Python binding mismatch that breaks most LLDB automation.

The whole tree compiles under **macOS system Python 3.9.6** at `/usr/bin/python3`, which ships with the Xcode Command Line Tools. So if you have Xcode, you have a working interpreter. CI enforces the 3.9 floor.

### Full Xcode, not the Command Line Tools

This distinction breaks more installs than anything else here.

```bash
xcode-select -p      # must point inside Xcode.app, not /Library/Developer/CommandLineTools
xcodebuild -version  # must succeed
```

If it points at the Command Line Tools:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

`xctrace`, the Instruments templates, and the iOS Simulator runtimes ship **only** with full Xcode. `ios-instruments-profiler` cannot work without them, and no workaround exists — `xctrace` is not redistributable.

## Optional

| Dependency | Needed for | Install | Without it |
|---|---|---|---|
| **A UI driver** | `ios-simulator-driver` input | see below | Observes and screenshots, but cannot tap, type, or swipe |
| **A physical Apple device** | device-fidelity performance claims | — | Simulator trends only; no real CPU/GPU/thermal/energy/power claims |
| **`ruff`, `shellcheck`** | contributor linting | `pip install -r requirements-dev.txt` | Nothing; CI does not require them |

### UI drivers — pick one

`simctl` has **no** `tap`, `swipe`, or `type` verb. It manages device and app lifecycle, screenshots, video, and diagnostics; it does not synthesize input. Any tool claiming `simctl tap` is inventing it, and `ios-simulator-driver` will not.

So the skill needs one of these:

| Driver | Install | Notes |
|---|---|---|
| [**AXe**](https://github.com/cameroncooke/AXe) | `brew install cameroncooke/axe/axe` | Low-latency standalone accessibility + HID. Simplest option. |
| [**XcodeBuildMCP**](https://github.com/cameroncooke/XcodeBuildMCP) | MCP server | Integrated build/run/snapshot/action with JSON output. |
| [**idb**](https://fbidb.io) | `brew tap facebook/fb && brew install idb-companion` | Lower-level accessibility and HID primitives. |
| **Appium + WebDriverAgent** | `npm i -g appium` | Heavier; also the path to physical devices. |
| **XCUIAutomation runner** | in your project | Most durable and fully supported; needs project source. |

The skill prefers an already-connected structured driver and does not switch mid-flow unless the current one is unhealthy — a switch invalidates element references.

### Physical devices

Required for any claim about real CPU, GPU, memory pressure, I/O, thermal state, energy, Neural Engine, or user-facing device performance. The Simulator shares your Mac's CPU and memory and has no real thermal or power behavior, so Simulator numbers are useful for *trends and pipeline development*, never for device claims. `ios-instruments-profiler` enforces this distinction rather than letting a Simulator measurement stand in.

Physical-device *UI automation* additionally needs a signed XCTest or WebDriverAgent workflow; `ios-simulator-driver` is Simulator-only by design and says so.

## Why no third-party packages

A deliberate constraint, not an accident.

An agent skill that requires `pip install` has a failure mode before it can be useful. Agents run in sandboxes without network access, on machines where the user cannot install packages, in CI containers, and in fresh checkouts where a dependency resolution failure is indistinguishable from the skill being broken. Every one of those turns "the skill did not work" into a support conversation.

Standard library only means `install.sh` never touches the network, CI needs no install step, and the skills work the moment they are linked.

This is enforced: CI compiles the tree against Python 3.9, and `tools/validate_skills.py` syntax-checks every script. A pull request adding a dependency needs a strong argument — see [CONTRIBUTING.md](../CONTRIBUTING.md).
