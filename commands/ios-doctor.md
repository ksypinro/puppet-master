---
description: Check which Puppet Master iOS skills can run here and what is missing
allowed-tools: Bash(python3:*), Bash(xcrun:*), Bash(xcode-select:*), Read
---

Run the capability probe and report the result to the user.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/doctor.py"
```

Then:

1. **State plainly** how many of the four skills are operational.
2. **For each blocked skill**, give the specific fix — not a general suggestion:
   - Full Xcode not selected → `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`
   - No UI driver → `brew install cameroncooke/axe/axe` (or idb, Appium, XcodeBuildMCP)
   - Python too old → the Xcode Command Line Tools ship 3.9.6 at `/usr/bin/python3`
3. **Mention the warnings only if they matter** for what the user is about to do. A missing UI driver matters if they want to drive the Simulator; it is noise if they only want to profile.
4. **If a skill is ready but the user has a specific problem**, run that skill's deeper doctor — the probe output names the command for each.

Do not install anything, change `xcode-select`, boot a Simulator, or modify settings. This command is read-only: report what is true and what the user would need to run themselves.
