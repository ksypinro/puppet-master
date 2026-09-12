## What and why

<!-- What changes, and what problem it solves. Link any issue. -->

## Checks

```bash
python3 tools/validate_skills.py --strict
python3 tools/check_imports.py
/usr/bin/python3 -m py_compile $(find skills tools -name '*.py')
bash -n install.sh uninstall.sh
```

- [ ] All four pass locally
- [ ] `SKILL.md` stays under 500 lines; detail went to `references/`
- [ ] No new third-party Python dependency (or justified below)
- [ ] Version bumped consistently if this is a release (plugin manifests, `CITATION.cff`, every `SKILL.md`)

## Evidence discipline

<!-- Skip if this touches no skill instructions. -->

- [ ] Unavailable data is reported `unknown`, never `0`/`false`/`nil`
- [ ] Observation stays labeled separately from inference
- [ ] No invented commands (`simctl` still has no `tap` verb)
- [ ] Any state-mutating capability requires explicit authorization and says so

## Verification

<!-- How did you confirm this works? Which app, which device/Simulator, which OS?
     For instruction changes, a transcript showing the agent behaving differently is
     the most useful thing you can include. -->
