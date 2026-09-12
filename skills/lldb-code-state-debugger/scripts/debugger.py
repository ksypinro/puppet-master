#!/usr/bin/env python3
"""Agent-neutral client for a persistent LLDB SB-API worker (stdlib only)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

MAX_MESSAGE = 2 * 1024 * 1024

def exchange(session, request, timeout=12):
    config = json.loads((Path(session) / 'connection.json').read_text())
    payload = json.dumps({'token': config['token'], 'request': request}).encode() + b'\n'
    if len(payload) > MAX_MESSAGE:
        raise ValueError('request exceeds 2 MiB')
    with socket.create_connection(('127.0.0.1', config['port']), timeout=timeout) as conn:
        conn.settimeout(timeout)
        conn.sendall(payload)
        output = bytearray()
        while b'\n' not in output:
            chunk = conn.recv(min(65536, MAX_MESSAGE + 1 - len(output)))
            if not chunk:
                raise ConnectionError('worker disconnected; reconcile target state before further action')
            output.extend(chunk)
            if len(output) > MAX_MESSAGE:
                raise ValueError('response exceeds 2 MiB')
        return json.loads(output.split(b'\n', 1)[0])

def resolve_lldb(explicit=None):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise ValueError('LLDB path does not exist')
        return str(p)
    if sys.platform == 'darwin':
        return subprocess.check_output(['xcrun', '--find', 'lldb'], text=True, timeout=10).strip()
    p = shutil.which('lldb')
    if not p:
        raise ValueError('LLDB with Python scripting is required')
    return p

def doctor(explicit=None):
    lldb = resolve_lldb(explicit)
    commands = ['version', 'script import sys; print(sys.version)',
                'script print("SB_API", lldb.SBDebugger.GetVersionString())',
                'help process attach', 'help device process attach',
                'help language swift task', 'help process save-core', 'help po']
    argv = [lldb, '--no-lldbinit', '--batch']
    for command in commands:
        argv.extend(['-o', command])
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return {'ok': True, 'lldb': lldb, 'platform': sys.platform,
            'discovery_only': True, 'exit_code': r.returncode,
            'help': (r.stdout + r.stderr)[-40000:],
            'note': 'A help entry is not live target qualification; some commands can be unavailable.'}

def start(session, explicit=None):
    folder = Path(session).resolve()
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(folder, 0o700)
    lldb = resolve_lldb(explicit)
    token = secrets.token_hex(32)
    source = Path(__file__).with_name('lldb_worker.py').resolve()
    bootstrap = folder / 'bootstrap.json'
    fd = os.open(str(bootstrap), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump({'token': token}, f)
    code = ('import sys; sys.path.insert(0, ' + repr(str(source.parent)) + '); '
            'import lldb_worker; lldb_worker.serve(lldb.debugger, ' + repr(str(folder)) + ')')
    log = os.open(str(folder / 'worker.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        proc = subprocess.Popen([lldb, '--no-lldbinit', '--batch', '-o', 'script ' + code],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    finally:
        os.close(log)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (folder / 'connection.json').exists():
            status = exchange(folder, {'op': 'status'})
            return {'ok': True, 'session': str(folder), 'worker_pid': proc.pid, 'lldb': lldb,
                    'worker_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'status': status}
        if proc.poll() is not None:
            raise RuntimeError('LLDB worker exited; inspect ' + str(folder / 'worker.log'))
        time.sleep(.05)
    raise TimeoutError('worker startup not confirmed; do not start a duplicate; inspect worker.log')

def wait_stop(session, after, timeout, breakpoint_id=None):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = exchange(session, {'op': 'status'}, min(5, max(.1, deadline - time.monotonic())))
        if not last.get('ok'):
            return last
        state = last['state']
        if state in ('exited', 'detached', 'unloaded', 'invalid'):
            return {'ok': False, 'error': 'target did not reach requested stop', 'last': last}
        if state in ('stopped', 'crashed', 'suspended') and last.get('stop_token') != after:
            if breakpoint_id is None or breakpoint_id in last.get('breakpoint_ids', []):
                return {'ok': True, 'observation': last}
            if last.get('stop_reason_coverage_complete') is False:
                return {'ok': False, 'error': 'stop observed but breakpoint evidence is incomplete; inspect additional threads/reasons before deciding', 'last': last}
            return {'ok': False, 'error': 'different stop observed; inspect it before resuming', 'last': last}
        time.sleep(.05)
    return {'ok': False, 'error': 'wait deadline exceeded; process was NOT canceled or resumed', 'last': last}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', help='Save this response as private JSON; do not overwrite an existing file')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('doctor'); p.add_argument('--lldb')
    p = sub.add_parser('start'); p.add_argument('session'); p.add_argument('--lldb')
    p = sub.add_parser('call'); p.add_argument('session'); p.add_argument('request', nargs='?', help='JSON object; omit to read stdin'); p.add_argument('--timeout', type=float, default=12)
    p = sub.add_parser('status'); p.add_argument('session')
    p = sub.add_parser('wait'); p.add_argument('session'); p.add_argument('--after', required=True); p.add_argument('--timeout', type=float, default=10); p.add_argument('--breakpoint', type=int)
    args = parser.parse_args()
    try:
        if args.command == 'doctor': result = doctor(args.lldb)
        elif args.command == 'start': result = start(args.session, args.lldb)
        elif args.command == 'status': result = exchange(args.session, {'op': 'status'})
        elif args.command == 'wait': result = wait_stop(args.session, args.after, min(60, max(.1, args.timeout)), args.breakpoint)
        else:
            request = json.loads(args.request if args.request is not None else sys.stdin.read(MAX_MESSAGE + 1))
            result = exchange(args.session, request, min(60, max(.1, args.timeout)))
    except Exception as exc:
        result = {'ok': False, 'error': str(exc), 'error_type': type(exc).__name__,
                  'state': 'unknown', 'warning': 'A client timeout does not cancel native work. Do not replay or kill an attached app.'}
    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        fd = os.open(str(Path(args.out).resolve()), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: f.write(output + '\n')
    print(output)
    return 0 if result.get('ok') else 1

if __name__ == '__main__':
    raise SystemExit(main())
