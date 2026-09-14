#!/usr/bin/env python3
"""Build, archive, export, install, launch — and prove the app is actually alive.

`xcodebuild` has no `run` action. Running is a composite: build, resolve the
product, install, launch, then verify. The last step is not optional: both
`simctl launch` and `devicectl process launch` exit 0 and print a process id for
an app that has already crashed.

    python3 build_run.py plan    --path P --scheme S --simulator
    python3 build_run.py build   --path P --scheme S --simulator
    python3 build_run.py run     --path P --scheme S --device-id UDID
    python3 build_run.py run     --path P --scheme S --console --env K=V
    python3 build_run.py verify  --device-id UDID --bundle-id com.example.app
"""

from __future__ import annotations

import argparse
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from build_util import (
    TIMEOUT_BUILD, BuildError, Container, build_settings, emit,
    read_build_results, resolve_product, run, run_json, text_fallback_errors,
)

ACTIONS = ["build", "build-for-testing", "analyze", "archive", "clean", "docbuild", "install"]

# Keep the tail of a chatty app's output rather than the whole stream.
CONSOLE_TAIL = 400


# ---------------------------------------------------------------- simulators

def resolve_simulator(identifier=None):
    data = run_json(["xcrun", "simctl", "list", "devices", "-j"]) or {}
    devices = []
    for runtime, entries in (data.get("devices") or {}).items():
        for device in entries:
            if device.get("isAvailable"):
                device = dict(device)
                device["runtime"] = runtime.rsplit(".", 1)[-1]
                devices.append(device)
    if not devices:
        raise BuildError("no available simulators; try xcodebuild -downloadPlatform iOS")
    if identifier:
        for device in devices:
            if identifier in (device["udid"], device["name"]):
                return device
        raise BuildError("no available simulator matching %r" % identifier)
    booted = [d for d in devices if d["state"] == "Booted"]
    if booted:
        return booted[0]
    raise BuildError(
        "no simulator is booted and none was named. Pass --device-id to choose one "
        "explicitly — an implicit target silently invalidates comparisons."
    )


def ensure_booted(udid):
    status = run(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout=600)
    if status.returncode == 0:
        return
    run(["xcrun", "simctl", "boot", udid], timeout=600)
    status = run(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout=600)
    if status.returncode != 0:
        raise BuildError("simulator %s did not reach a booted state" % udid)


LAUNCHCTL = "UIKitApplication:%s"


def simulator_liveness(udid, bundle_id):
    """The probe that separates 'launched' from 'running'.

    simctl and devicectl both report success for an app that crashed during
    launch, so their exit code proves dispatch only. launchctl on the simulated
    device is authoritative; devicectl's own process listing cannot see
    Simulator app processes at all.
    """
    proc = run(["xcrun", "simctl", "spawn", udid, "launchctl", "list"], timeout=120)
    pattern = re.compile(
        r"^(\d+)\s+(\S+)\s+" + re.escape(LAUNCHCTL % bundle_id), re.M
    )
    match = pattern.search(proc.stdout)
    if not match:
        return {"running": False, "pid": None, "lastExitStatus": None}
    return {"running": True, "pid": int(match.group(1)), "lastExitStatus": match.group(2)}


# ---------------------------------------------------------------- build

def compose(container, destination, action, extra=None, result_bundle=None,
            archive_path=None):
    cmd = ["xcodebuild"] + container.common()
    if destination:
        cmd += ["-destination", destination]
    if archive_path:
        cmd += ["-archivePath", str(archive_path)]
    if result_bundle:
        cmd += ["-resultBundlePath", str(result_bundle)]
    cmd += list(extra or [])
    cmd += [action]
    return cmd


def execute_build(container, destination, action, extra=None, archive_path=None,
                  keep_bundle=None):
    """Run one xcodebuild action and return typed diagnostics, not log text."""
    holder = Path(keep_bundle) if keep_bundle else Path(tempfile.mkdtemp(prefix="ibe-"))
    holder.mkdir(parents=True, exist_ok=True)
    bundle = holder / "result.xcresult"
    if bundle.exists():
        shutil.rmtree(bundle, ignore_errors=True)

    cmd = compose(container, destination, action, extra, bundle, archive_path)
    started = time.time()
    proc = run(cmd, cwd=container.cwd, timeout=TIMEOUT_BUILD)
    elapsed = round(time.time() - started, 2)

    diagnostics = read_build_results(bundle)
    if diagnostics is None:
        # exportArchive produces no bundle at all on failure; some very early
        # failures do the same. Say so rather than implying a clean result.
        diagnostics = {
            "status": "succeeded" if proc.returncode == 0 else "failed",
            "errorCount": None,
            "errors": [{"type": "unstructured", "message": m, "location": None}
                       for m in text_fallback_errors(proc.stdout + proc.stderr)],
            "warnings": [],
            "source": "text fallback — no result bundle was produced",
        }
    else:
        diagnostics["source"] = "result bundle"

    if not keep_bundle:
        shutil.rmtree(holder, ignore_errors=True)

    return {
        "ok": proc.returncode == 0,
        "action": action,
        "exitStatus": proc.returncode,
        "seconds": elapsed,
        "command": cmd,
        "destination": destination,
        "diagnostics": diagnostics,
        "resultBundle": str(bundle) if keep_bundle else None,
    }


def destination_for(args):
    if args.destination:
        return args.destination
    if args.device_id:
        if args.physical:
            return "platform=iOS,id=%s" % args.device_id
        return "platform=iOS Simulator,id=%s" % args.device_id
    if args.physical:
        return "generic/platform=iOS"
    if args.simulator:
        return "generic/platform=iOS Simulator"
    return "generic/platform=iOS Simulator"


def extra_args(args):
    """xcodebuild accepts KEY=VALUE overrides anywhere in the argument list.
    Both --xcarg and --setting must reach it; dropping --setting silently would
    make an override such as CODE_SIGNING_ALLOWED=NO appear to be applied when
    it was not."""
    combined = list(getattr(args, "xcarg", None) or [])
    for setting in (getattr(args, "setting", None) or []):
        if "=" not in setting:
            raise BuildError("--setting expects KEY=VALUE, got %r" % setting)
        combined.append(setting)
    return combined


def container_from(args):
    return Container.discover(
        args.path, scheme=args.scheme, configuration=args.configuration,
        derived_data=args.derived_data,
    )


def cmd_plan(args):
    container = container_from(args)
    destination = destination_for(args)
    cmd = compose(container, destination, args.action, extra_args(args),
                  "<result-bundle>", args.archive_path)
    emit({"ok": True, "command": cmd, "cwd": container.cwd,
          "destination": destination,
          "note": "printed only; nothing was executed"})


def cmd_build(args):
    container = container_from(args)
    if not container.scheme:
        raise BuildError("--scheme is required")
    result = execute_build(container, destination_for(args), args.action,
                           extra_args(args), args.archive_path, args.result_bundle)
    emit(result)
    raise SystemExit(0 if result["ok"] else 1)


def cmd_archive(args):
    container = container_from(args)
    if not container.scheme:
        raise BuildError("--scheme is required")
    if not args.archive_path:
        raise BuildError("--archive-path is required for archive")
    destination = args.destination or "generic/platform=iOS"
    result = execute_build(container, destination, "archive", extra_args(args),
                           args.archive_path, args.result_bundle)
    archive = Path(args.archive_path)
    if result["ok"] and archive.exists():
        result["archive"] = {
            "path": str(archive),
            "products": [str(p) for p in (archive / "Products").rglob("*.app")],
            "dsyms": [str(p) for p in (archive / "dSYMs").glob("*.dSYM")],
        }
    emit(result)
    raise SystemExit(0 if result["ok"] else 1)


def cmd_export(args):
    """Export an archive to a signed .ipa.

    Deliberately does not pass -resultBundlePath as a promise of structure:
    export failures produce no result bundle, so diagnosis here is text-based
    and is labelled as such. Use signing_doctor.py classify on the messages.
    """
    archive = Path(args.archive_path)
    if not archive.exists():
        raise BuildError("archive not found: %s" % archive)
    cmd = ["xcodebuild", "-exportArchive",
           "-archivePath", str(archive),
           "-exportPath", str(args.export_path),
           "-exportOptionsPlist", str(args.options_plist)]
    cmd += list(args.xcarg or [])
    proc = run(cmd, timeout=TIMEOUT_BUILD)
    messages = text_fallback_errors(proc.stdout + proc.stderr)
    payload = {
        "ok": proc.returncode == 0,
        "exitStatus": proc.returncode,
        "command": cmd,
        "messages": messages,
        "diagnosticsSource": "text only — exportArchive writes no result bundle on failure",
    }
    if proc.returncode == 0:
        out = Path(args.export_path)
        payload["exported"] = [str(p) for p in out.glob("*")] if out.exists() else []
    else:
        payload["next"] = "python3 signing_doctor.py classify --message '<message>'"
    emit(payload)
    raise SystemExit(0 if proc.returncode == 0 else 1)


# ---------------------------------------------------------------- deploy

def cmd_install(args):
    app = Path(args.app).resolve()
    if not app.exists():
        raise BuildError("app bundle not found: %s" % app)
    if args.physical:
        result = run(["xcrun", "devicectl", "device", "install", "app",
                      "--device", args.device_id, str(app)], timeout=1800)
        emit({"ok": result.returncode == 0, "target": "device",
              "exitStatus": result.returncode,
              "output": result.stdout.strip()[-2000:] or result.stderr.strip()[-2000:],
              "verified": False,
              "note": "physical-device install is unverified by this skill's fixtures"})
        raise SystemExit(0 if result.returncode == 0 else 1)

    device = resolve_simulator(args.device_id)
    ensure_booted(device["udid"])
    result = run(["xcrun", "simctl", "install", device["udid"], str(app)], timeout=900)
    emit({"ok": result.returncode == 0, "target": "simulator",
          "device": {"name": device["name"], "udid": device["udid"]},
          "exitStatus": result.returncode,
          "error": result.stderr.strip() or None})
    raise SystemExit(0 if result.returncode == 0 else 1)


def _split_env(pairs):
    out = {}
    for item in pairs or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise BuildError("--env expects KEY=VALUE, got %r" % item)
        out[key] = value
    return out


def launch_simulator(device, bundle_id, app_args, env, console, console_seconds,
                     settle):
    udid = device["udid"]
    # A console attach only connects stdio when it STARTS the process. Launching
    # an app that is already running exits 0 with an empty log, which is
    # indistinguishable from "the app printed nothing".
    run(["xcrun", "simctl", "terminate", udid, bundle_id], timeout=120)

    child_env = {("SIMCTL_CHILD_" + k): v for k, v in env.items()}
    cmd = ["xcrun", "simctl", "launch"]
    if console:
        cmd.append("--console-pty")
    cmd += [udid, bundle_id] + list(app_args or [])

    if not console:
        proc = run(cmd, env=child_env, timeout=600)
        if proc.returncode != 0:
            return {"ok": False, "stage": "launch",
                    "error": (proc.stderr or proc.stdout).strip()}
        time.sleep(settle)
        liveness = simulator_liveness(udid, bundle_id)
        return {"ok": liveness["running"], "stage": "launch",
                "reportedByLauncher": proc.stdout.strip(),
                "liveness": liveness, "consoleLines": None}

    # --console-pty makes the app a CHILD of this process: closing the console
    # terminates the app. The liveness probe therefore has to run while the
    # console is still open, or a healthy app reads as a crash.
    merged = dict(os.environ)
    merged.update(child_env)
    # Binary, unbuffered, non-blocking reads on the raw descriptor. A buffered
    # text stream breaks this loop: readline() pulls a whole chunk into Python's
    # buffer and returns one line, after which select() reports the descriptor
    # as not ready and the remaining buffered lines are never read.
    proc = subprocess.Popen(cmd, env=merged, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, bufsize=0)
    fd = proc.stdout.fileno()
    os.set_blocking(fd, False)

    deadline = time.time() + console_seconds
    probe_at = time.time() + settle
    liveness, lines, pending = None, [], b""

    def absorb(chunk):
        nonlocal pending
        pending += chunk
        parts = pending.split(b"\n")
        pending = parts.pop()
        for raw in parts:
            lines.append(raw.decode("utf-8", "replace").rstrip("\r"))

    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if liveness is None and time.time() >= probe_at:
                liveness = simulator_liveness(udid, bundle_id)
            ready, _, _ = select.select([fd], [], [], min(0.5, remaining))
            if not ready:
                continue
            try:
                chunk = os.read(fd, 65536)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                break  # pty closes with EIO once the child is gone
            if not chunk:
                break
            absorb(chunk)
    finally:
        if pending:
            lines.append(pending.decode("utf-8", "replace").rstrip("\r"))
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if liveness is None:
        liveness = simulator_liveness(udid, bundle_id)
    return {
        "ok": liveness["running"], "stage": "launch",
        "liveness": liveness,
        "console": lines[-CONSOLE_TAIL:],
        "consoleLines": len(lines),
        "consoleTruncated": len(lines) > CONSOLE_TAIL,
        "note": ("--console-pty owned the app's lifetime; the app was terminated when "
                 "the console closed. Launch without --console to leave it running."),
    }


def launch_device(device_id, bundle_id, app_args, env, console):
    """Physical-device launch. Unverified by this skill's fixtures.

    devicectl states that JSON written to a file is the only supported scripting
    interface and that stdout is not stable, so the pid is read from the file.
    """
    handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    handle.close()
    cmd = ["xcrun", "devicectl", "device", "process", "launch",
           "--device", device_id, "--json-output", handle.name,
           "--terminate-existing"]
    if console:
        cmd.append("--console")
    if env:
        import json as _json
        cmd += ["-e", _json.dumps(env)]
    cmd += [bundle_id] + list(app_args or [])

    proc = run(cmd, timeout=900)
    pid = None
    try:
        import json as _json
        with open(handle.name) as fh:
            payload = _json.load(fh)
        pid = (((payload.get("result") or {}).get("process") or {})
               .get("processIdentifier"))
    except Exception:
        pass
    finally:
        os.unlink(handle.name)

    return {
        "ok": proc.returncode == 0,
        "stage": "launch",
        "target": "device",
        "pid": pid,
        "exitStatus": proc.returncode,
        "output": (proc.stdout or proc.stderr).strip()[-2000:],
        "liveness": None,
        "verified": False,
        "note": ("a launch pid proves dispatch, not liveness; devicectl cannot be "
                 "used to probe Simulator processes, and this device path is "
                 "unverified by this skill's fixtures"),
    }


def cmd_launch(args):
    env = _split_env(args.env)
    if args.physical:
        if not args.device_id:
            raise BuildError("--device-id is required for a physical device")
        result = launch_device(args.device_id, args.bundle_id, args.arg, env,
                               args.console)
    else:
        device = resolve_simulator(args.device_id)
        ensure_booted(device["udid"])
        result = launch_simulator(device, args.bundle_id, args.arg, env,
                                  args.console, args.console_seconds, args.settle)
        result["device"] = {"name": device["name"], "udid": device["udid"]}
    emit(result)
    raise SystemExit(0 if result["ok"] else 1)


def cmd_verify(args):
    if args.physical:
        emit({"ok": False,
              "error": "physical-device liveness has no verified first-party probe in this skill",
              "guidance": ("devicectl device info processes enumerates device processes, "
                           "but this path is unverified here; treat a device launch as "
                           "dispatch only")})
        raise SystemExit(2)
    device = resolve_simulator(args.device_id)
    liveness = simulator_liveness(device["udid"], args.bundle_id)
    emit({
        "ok": liveness["running"],
        "device": {"name": device["name"], "udid": device["udid"]},
        "bundleId": args.bundle_id,
        "liveness": liveness,
        "verdict": "running" if liveness["running"] else
                   "not running — if a launch just reported success, the app exited during launch",
    })
    raise SystemExit(0 if liveness["running"] else 1)


def cmd_stop(args):
    if args.physical:
        raise BuildError("stopping a device process is out of scope for this skill")
    device = resolve_simulator(args.device_id)
    proc = run(["xcrun", "simctl", "terminate", device["udid"], args.bundle_id],
               timeout=120)
    emit({"ok": proc.returncode == 0,
          "device": {"name": device["name"], "udid": device["udid"]},
          "bundleId": args.bundle_id,
          "error": proc.stderr.strip() or None})


# ---------------------------------------------------------------- run

def cmd_run(args):
    container = container_from(args)
    if not container.scheme:
        raise BuildError("--scheme is required")

    stages = []
    if args.physical:
        if not args.device_id:
            raise BuildError("--device-id is required for a physical device")
        destination = "platform=iOS,id=%s" % args.device_id
        device = None
    else:
        device = resolve_simulator(args.device_id)
        ensure_booted(device["udid"])
        destination = "platform=iOS Simulator,id=%s" % device["udid"]

    if not args.no_build:
        build = execute_build(container, destination, "build", extra_args(args),
                              None, args.result_bundle)
        stages.append(build)
        if not build["ok"]:
            emit({"ok": False, "failedStage": "build", "stages": stages})
            raise SystemExit(1)

    settings = build_settings(container, destination, extra=args.setting)
    product = resolve_product(settings)
    if not product["bundleId"]:
        raise BuildError("PRODUCT_BUNDLE_IDENTIFIER is unset for this target")
    if not Path(product["appPath"]).exists():
        raise BuildError(
            "no product at %s — run without --no-build" % product["appPath"]
        )
    stages.append({"ok": True, "stage": "resolve", "product": product})

    if args.physical:
        install = run(["xcrun", "devicectl", "device", "install", "app",
                       "--device", args.device_id, product["appPath"]], timeout=1800)
        stages.append({"ok": install.returncode == 0, "stage": "install",
                       "target": "device", "verified": False,
                       "output": (install.stdout or install.stderr).strip()[-1500:]})
        if install.returncode != 0:
            emit({"ok": False, "failedStage": "install", "stages": stages})
            raise SystemExit(1)
        launch = launch_device(args.device_id, product["bundleId"], args.arg,
                               _split_env(args.env), args.console)
    else:
        install = run(["xcrun", "simctl", "install", device["udid"],
                       product["appPath"]], timeout=900)
        stages.append({"ok": install.returncode == 0, "stage": "install",
                       "target": "simulator",
                       "error": install.stderr.strip() or None})
        if install.returncode != 0:
            emit({"ok": False, "failedStage": "install", "stages": stages})
            raise SystemExit(1)
        launch = launch_simulator(device, product["bundleId"], args.arg,
                                  _split_env(args.env), args.console,
                                  args.console_seconds, args.settle)
    stages.append(launch)

    payload = {
        "ok": bool(launch.get("ok")),
        "bundleId": product["bundleId"],
        "appPath": product["appPath"],
        "destination": destination,
        "stages": stages,
    }
    if device:
        payload["device"] = {"name": device["name"], "udid": device["udid"]}
    if not args.physical:
        liveness = launch.get("liveness") or {}
        payload["verdict"] = (
            "running" if liveness.get("running")
            else "launched then exited — a FAILURE, even though the launcher exited 0"
        )
    else:
        payload["verdict"] = ("dispatched to device — liveness NOT verified by this skill")
    emit(payload)
    raise SystemExit(0 if payload["ok"] else 1)


# ---------------------------------------------------------------- cli

def add_build_args(parser):
    parser.add_argument("--path", default=".")
    parser.add_argument("--scheme")
    parser.add_argument("--configuration")
    parser.add_argument("--derived-data", dest="derived_data")
    parser.add_argument("--destination")
    parser.add_argument("--device-id", dest="device_id")
    parser.add_argument("--simulator", action="store_true")
    parser.add_argument("--physical", action="store_true",
                        help="target physical hardware (unverified lane)")
    parser.add_argument("--xcarg", action="append",
                        help="extra xcodebuild argument, repeatable")
    parser.add_argument("--setting", action="append",
                        help="extra KEY=VALUE build setting, repeatable")
    parser.add_argument("--result-bundle", dest="result_bundle",
                        help="keep the .xcresult under this directory")
    parser.add_argument("--archive-path", dest="archive_path")


def add_launch_args(parser):
    parser.add_argument("--arg", action="append",
                        help="argument for the app; use --arg=--flag for leading dashes")
    parser.add_argument("--env", action="append", metavar="KEY=VALUE")
    parser.add_argument("--console", action="store_true",
                        help="stream app stdout; the app is terminated when it closes")
    parser.add_argument("--console-seconds", dest="console_seconds", type=float,
                        default=20.0)
    parser.add_argument("--settle", type=float, default=2.5,
                        help="seconds to wait before probing liveness")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan"); add_build_args(p)
    p.add_argument("--action", default="build", choices=ACTIONS)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("build"); add_build_args(p)
    p.add_argument("--action", default="build", choices=ACTIONS)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("archive"); add_build_args(p); p.set_defaults(func=cmd_archive)

    p = sub.add_parser("export")
    p.add_argument("--archive-path", dest="archive_path", required=True)
    p.add_argument("--export-path", dest="export_path", required=True)
    p.add_argument("--options-plist", dest="options_plist", required=True)
    p.add_argument("--xcarg", action="append")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("install")
    p.add_argument("--app", required=True)
    p.add_argument("--device-id", dest="device_id")
    p.add_argument("--physical", action="store_true")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("launch")
    p.add_argument("--bundle-id", dest="bundle_id", required=True)
    p.add_argument("--device-id", dest="device_id")
    p.add_argument("--physical", action="store_true")
    add_launch_args(p)
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("verify")
    p.add_argument("--bundle-id", dest="bundle_id", required=True)
    p.add_argument("--device-id", dest="device_id")
    p.add_argument("--physical", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("stop")
    p.add_argument("--bundle-id", dest="bundle_id", required=True)
    p.add_argument("--device-id", dest="device_id")
    p.add_argument("--physical", action="store_true")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("run"); add_build_args(p); add_launch_args(p)
    p.add_argument("--no-build", dest="no_build", action="store_true")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2)
