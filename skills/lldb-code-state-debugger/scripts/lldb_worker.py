"""Runs inside LLDB's matching embedded Python. No prompt parsing or third-party packages."""
import collections
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import time
import uuid
import lldb

MAX_MESSAGE = 2 * 1024 * 1024
STOPPED = {lldb.eStateStopped, lldb.eStateCrashed, lldb.eStateSuspended}

def bounded(value, low, high):
    return max(low, min(high, int(value)))

def error_check(error):
    if error.Fail(): raise RuntimeError(error.GetCString() or 'LLDB operation failed')

def file_path(spec):
    return os.path.join(spec.GetDirectory() or '', spec.GetFilename() or '')

class Worker:
    def __init__(self, debugger, folder):
        self.debugger = debugger
        self.debugger.SetAsync(True)
        self.listener = lldb.SBListener('code-state-worker-' + str(uuid.uuid4()))
        self.folder = Path(folder)
        self.session_id = str(uuid.uuid4())
        self.revision = 0
        self.event_seq = 0
        self.events = collections.deque(maxlen=256)
        self.output = collections.deque(maxlen=128)
        self.fingerprint = None
        self.refs = {}
        self.ref_counter = 0
        self.owned_breakpoints = set()
        self.owned_watchpoints = set()
        self.owner = None
        self.binding = None
        self.lease = None
        self.closed = False
        self.started = time.time()
        self.published_state = lldb.eStateUnloaded
        self.managed_target = lldb.SBTarget()
        self.managed_process_id = None

    def managed_selection(self):
        selected = self.target()
        return (self.managed_target.IsValid() and selected == self.managed_target and
                (not self.process().IsValid() or self.managed_process_id == self.process().GetUniqueID()))

    def state(self):
        p = self.process()
        if not p.IsValid(): return lldb.eStateUnloaded
        native = p.GetState()
        # GetState may expose a transient breakpoint/watchpoint stop before LLDB
        # has evaluated its condition or completed a watchpoint step-over.
        if native in STOPPED and self.published_state not in STOPPED:
            return self.published_state
        return native

    def target(self):
        return self.debugger.GetSelectedTarget()

    def process(self):
        return self.target().GetProcess()

    def invalidate(self):
        self.revision += 1
        self.refs.clear()

    def token(self):
        p = self.process()
        if not p.IsValid() or not self.managed_selection() or self.state() not in STOPPED: return None
        return '%s:%s:%s:%s' % (self.session_id, p.GetUniqueID(), p.GetStopID(True), self.revision)

    def reconcile(self):
        # Drain notifications independently of client waits; current SB state is authoritative.
        event = lldb.SBEvent()
        for _ in range(128):
            if not self.listener.GetNextEvent(event): break
            if lldb.SBProcess.EventIsProcessEvent(event):
                event_state = lldb.SBProcess.GetStateFromEvent(event)
                restarted = lldb.SBProcess.GetRestartedFromEvent(event)
                if (event.GetType() & lldb.SBProcess.eBroadcastBitStateChanged and
                        lldb.SBProcess.GetProcessFromEvent(event).GetUniqueID() == self.process().GetUniqueID()):
                    self.published_state = lldb.eStateRunning if restarted else event_state
                self.event_seq += 1
                self.events.append({'seq': self.event_seq, 'time': time.time(),
                                    'process_unique_id': lldb.SBProcess.GetProcessFromEvent(event).GetUniqueID(),
                                    'pid': lldb.SBProcess.GetProcessFromEvent(event).GetProcessID(),
                                    'state': lldb.SBDebugger.StateAsCString(event_state),
                                    'restarted': restarted})
        p = self.process()
        if p.IsValid():
            current = (p.GetUniqueID(), p.GetState(), p.GetStopID(True))
            if current != self.fingerprint:
                self.refs.clear()
                self.fingerprint = current
            for name, reader in [('stdout', p.GetSTDOUT), ('stderr', p.GetSTDERR)]:
                chunk = reader(4096)
                if chunk: self.output.append({'stream': name, 'text': chunk, 'time': time.time(),
                                              'process_unique_id': p.GetUniqueID(), 'pid': p.GetProcessID()})

    def status(self):
        self.reconcile()
        p = self.process()
        threads = []
        bp_ids = []
        reasons_truncated = False
        if p.IsValid() and self.state() in STOPPED:
            for i in range(min(p.GetNumThreads(), 64)):
                t = p.GetThreadAtIndex(i)
                reason = t.GetStopReason()
                data = [t.GetStopReasonDataAtIndex(j) for j in range(min(32, t.GetStopReasonDataCount()))]
                reasons_truncated = reasons_truncated or t.GetStopReasonDataCount() > 32
                if reason == lldb.eStopReasonBreakpoint: bp_ids.extend(data[::2])
                if reason != lldb.eStopReasonNone:
                    threads.append({'thread_id': t.GetThreadID(), 'index_id': t.GetIndexID(),
                                    'reason': reason, 'description': t.GetStopDescription(1024), 'data': data})
        return {'ok': True, 'session_id': self.session_id, 'state': lldb.SBDebugger.StateAsCString(self.state()) if p.IsValid() else 'unloaded',
                'native_state': lldb.SBDebugger.StateAsCString(p.GetState()) if p.IsValid() else 'unloaded',
                'pid': p.GetProcessID() if p.IsValid() else None,
                'process_unique_id': p.GetUniqueID() if p.IsValid() else None,
                'stop_id': p.GetStopID(True) if p.IsValid() else None, 'stop_token': self.token(),
                'revision': self.revision, 'event_seq': self.event_seq, 'stop_reasons': threads,
                'managed_selection': self.managed_selection(),
                'stop_reason_coverage_complete': (not p.IsValid() or p.GetNumThreads() <= 64) and not reasons_truncated,
                'threads_total': p.GetNumThreads() if p.IsValid() else 0,
                'threads_scanned_for_stops': min(p.GetNumThreads(), 64) if p.IsValid() and self.state() in STOPPED else 0,
                'reason_data_truncated': reasons_truncated,
                'breakpoint_ids': bp_ids, 'owner': self.owner, 'binding': self.binding,
                'async_execution': self.debugger.GetAsync(), 'timestamp': time.time()}

    def stopped(self, request):
        self.reconcile()
        token = self.token()
        if token is None: raise RuntimeError('target is not stopped')
        if request.get('stop_token') != token: raise ValueError('stale or missing stop_token; obtain status and choose the frame again')
        return token

    def frame(self, request):
        p = self.process()
        t = p.GetThreadByID(int(request['thread_id'])) if 'thread_id' in request else p.GetSelectedThread()
        if not t.IsValid(): raise ValueError('invalid thread ID (not a thread array index)')
        f = t.GetFrameAtIndex(bounded(request.get('frame_index', 0), 0, 10000))
        if not f.IsValid(): raise ValueError('invalid frame index')
        return t, f

    def frame_json(self, f):
        line = f.GetLineEntry()
        return {'valid': f.IsValid(), 'frame_index': f.GetFrameID(), 'pc': hex(f.GetPC()), 'function': f.GetFunctionName(),
                'file': file_path(line.GetFileSpec()), 'line': line.GetLine() if line.IsValid() else None, 'column': line.GetColumn() if line.IsValid() else None,
                'module': file_path(f.GetModule().GetFileSpec()), 'module_uuid': f.GetModule().GetUUIDString()}

    def value_json(self, value, depth=0, children=20, budget=None):
        if budget is None: budget = [200]
        budget[0] -= 1
        value = value.GetNonSyntheticValue()
        value.SetPreferSyntheticValue(False)
        value.SetPreferDynamicValue(lldb.eNoDynamicValues)
        err = value.GetError()
        result = {'name': value.GetName(), 'type': value.GetTypeName(), 'value': value.GetValue(),
                  'available': value.IsValid() and err.Success(),
                  'error': err.GetCString() if err.Fail() else None,
                  'byte_size': value.GetByteSize(), 'address': None,
                  'evaluation_mode': 'raw_no_dynamic_no_synthetic'}
        address = value.GetLoadAddress()
        if address != lldb.LLDB_INVALID_ADDRESS: result['address'] = hex(address)
        # Probe only a bounded count; exact total may require expensive formatter work.
        count = value.GetNumChildren(children + 1)
        result['child_count_lower_bound'] = count
        result['truncated'] = count > children
        if count:
            self.ref_counter += 1
            key = 'v%d' % self.ref_counter
            if len(self.refs) < 2048:
                self.refs[key] = value
                result['reference'] = key
            if depth > 0:
                result['children'] = []
                for i in range(min(count, children)):
                    if budget[0] <= 0:
                        result['truncated'] = True; break
                    result['children'].append(self.value_json(value.GetChildAtIndex(i, lldb.eNoDynamicValues, False), depth - 1, children, budget))
        if result['value'] is not None and len(result['value']) > 4096:
            result['value'] = result['value'][:4096]; result['value_truncated'] = True
        return result

    def breakpoint_json(self, bp):
        locations = []
        for i in range(min(bp.GetNumLocations(), 100)):
            loc = bp.GetLocationAtIndex(i); address = loc.GetAddress(); line = address.GetLineEntry()
            locations.append({'id': loc.GetID(), 'resolved': loc.IsResolved(),
                              'address': hex(address.GetLoadAddress(self.target())),
                              'file': file_path(line.GetFileSpec()), 'line': line.GetLine(),
                              'module': file_path(address.GetModule().GetFileSpec()), 'module_uuid': address.GetModule().GetUUIDString()})
        return {'id': bp.GetID(), 'enabled': bp.IsEnabled(), 'condition': bp.GetCondition(),
                'hit_count': bp.GetHitCount(), 'locations_count': bp.GetNumLocations(),
                'resolved_count': bp.GetNumResolvedLocations(), 'verified': bp.GetNumResolvedLocations() > 0,
                'locations': locations, 'truncated': bp.GetNumLocations() > 100}

    def require_execution(self, r):
        if r.get('allow_target_execution') is not True:
            raise ValueError('operation can execute target code; explicit allow_target_execution=true and task authority required')

    def require_mutation(self, r):
        if r.get('allow_mutation') is not True:
            raise ValueError('explicit allow_mutation=true and task authority required')

    def claim_pid(self, pid):
        # Advisory lease between this tool's workers; LLDB still enforces real attach rights.
        import fcntl
        lock = os.open('/tmp/lldb-code-state-%d-%d.lock' % (os.getuid(), pid), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(lock); raise RuntimeError('another code-state worker owns this host PID')
        self.lease = lock

    def remove_owned_probes(self):
        for ident in self.owned_breakpoints: self.managed_target.BreakpointDelete(ident)
        for ident in self.owned_watchpoints: self.managed_target.DeleteWatchpoint(ident)
        self.owned_breakpoints.clear(); self.owned_watchpoints.clear()

    def release(self):
        if self.lease is not None: os.close(self.lease); self.lease = None

    def dispatch(self, r):
        self.reconcile()
        op = r.get('op')
        if op == 'status': return self.status()
        if op not in ('raw', 'capabilities', 'shutdown', 'events', 'output') and self.managed_target.IsValid() and not self.managed_selection():
            raise ValueError('raw command changed target/process ownership; restore the managed target or explicitly clean up through the raw console; typed operations are blocked')
        if op == 'capabilities':
            return {'ok': True, 'backend': 'LLDB embedded SB API', 'schema': 1,
                    'operations': ['target', 'launch', 'attach', 'breakpoint_add', 'breakpoint_update', 'breakpoint_delete', 'breakpoints', 'resume', 'pause', 'step', 'threads', 'stack', 'variables', 'children', 'evaluate', 'memory_read', 'memory_write', 'registers', 'disassemble', 'modules', 'watchpoint_add', 'watchpoint_delete', 'raw', 'output', 'events', 'detach', 'terminate', 'shutdown'],
                    'limits': {'message_bytes': MAX_MESSAGE, 'memory_bytes': 4096, 'value_nodes': 200, 'depth': 5, 'children_per_page': 50, 'frames': 100, 'expression_timeout_us': 5000000},
                    'limitations': ['No universal language/runtime or device qualification', 'Raw commands can wedge the worker; client timeout is not cancellation', 'No full Xcode memory graph or logical SwiftUI tree', 'Advisory lease only covers this tool; do not compete with Xcode', 'Event/output retention is bounded and lossy; not a complete trace'],
                    'lldb_version': self.debugger.GetVersionString()}
        if op in ('target', 'attach', 'launch'):
            p = self.process()
            if p.IsValid() and p.GetState() not in (lldb.eStateExited, lldb.eStateDetached, lldb.eStateInvalid):
                raise ValueError('detach the current process before replacing its target')
            # A naturally exited process still has an advisory PID lease. Never
            # overwrite its descriptor, or carry target-local probe IDs into a
            # replacement target where numeric IDs can be reused.
            self.release()
            if op in ('target', 'attach'):
                self.remove_owned_probes()
                self.owner = None
                self.binding = None
                self.published_state = lldb.eStateUnloaded
            if op == 'launch':
                target = self.target()
                if not target.IsValid(): raise ValueError('create target first')
                launch = lldb.SBLaunchInfo(r.get('arguments', []))
                launch.SetListener(self.listener)
                launch.SetWorkingDirectory(r.get('cwd', str(Path.cwd())))
                launch.SetLaunchFlags(lldb.eLaunchFlagDebug | (lldb.eLaunchFlagStopAtEntry if r.get('stop_at_entry', True) else 0))
                if r.get('environment'): launch.SetEnvironmentEntries(r['environment'], True)
                self.published_state = lldb.eStateLaunching
                err = lldb.SBError(); process = target.Launch(launch, err); error_check(err)
                self.managed_process_id = process.GetUniqueID()
                self.owner = 'launched'; self.claim_pid(process.GetProcessID())
            else:
                executable = str(Path(r['executable']).resolve())
                if not Path(executable).is_file(): raise ValueError('executable must exist on debugger host')
                if op == 'attach': self.claim_pid(int(r['pid']))
                err = lldb.SBError()
                target = self.debugger.CreateTarget(executable, r.get('triple'), r.get('platform'), True, err)
                try:
                    error_check(err)
                    self.debugger.SetSelectedTarget(target)
                    self.managed_target = target
                    self.managed_process_id = None
                    self.binding = {'executable': executable, 'sha256': hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                                    'context': r.get('context', {}), 'bound_at': time.time()}
                    if op == 'attach':
                        self.published_state = lldb.eStateAttaching
                        attached = target.AttachToProcessWithID(self.listener, int(r['pid']), err); error_check(err)
                        # The synchronous attach API may consume its initial stop
                        # event before returning. Successful return qualifies that
                        # initial state; later execution still uses event gating.
                        self.published_state = attached.GetState()
                        self.managed_process_id = attached.GetUniqueID()
                        self.owner = 'attached'
                except Exception:
                    self.release(); raise
            self.invalidate()
            return self.status()
        if op == 'breakpoints':
            return {'ok': True, 'breakpoints': [self.breakpoint_json(self.target().GetBreakpointAtIndex(i)) for i in range(min(200, self.target().GetNumBreakpoints()))]}
        if op == 'breakpoint_add':
            if not self.target().IsValid(): raise ValueError('no target')
            if r.get('condition'): self.require_execution(r)
            if 'file' in r:
                path = str(Path(r['file']).resolve())
                bp = self.target().BreakpointCreateByLocation(path, int(r['line']))
                source = {'file': path, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None, 'requested_line': int(r['line'])}
            elif 'regex' in r:
                bp = self.target().BreakpointCreateByRegex(r['regex']); source = {'regex': r['regex']}
            else:
                bp = self.target().BreakpointCreateByName(r['name']); source = {'name': r['name']}
            if not bp.IsValid(): raise RuntimeError('invalid breakpoint')
            self.owned_breakpoints.add(bp.GetID())
            if r.get('condition'): bp.SetCondition(r['condition'])
            bp.SetIgnoreCount(bounded(r.get('ignore_count', 0), 0, 1000000))
            bp.SetOneShot(bool(r.get('one_shot', False)))
            return {'ok': True, 'breakpoint': self.breakpoint_json(bp), 'source': source}
        if op in ('breakpoint_update', 'breakpoint_delete'):
            ident = int(r['id'])
            if ident not in self.owned_breakpoints: raise ValueError('not an owned breakpoint')
            if op == 'breakpoint_delete':
                success = self.target().BreakpointDelete(ident); self.owned_breakpoints.discard(ident)
                return {'ok': bool(success)}
            bp = self.target().FindBreakpointByID(ident)
            if 'condition' in r: self.require_execution(r); bp.SetCondition(r['condition'])
            if 'commands' in r:
                self.require_execution(r)
                commands = lldb.SBStringList()
                for c in r['commands'][:20]: commands.AppendString(c)
                bp.SetCommandLineCommands(commands)
            for key, method in [('enabled', bp.SetEnabled), ('one_shot', bp.SetOneShot), ('auto_continue', bp.SetAutoContinue)]:
                if key in r: method(bool(r[key]))
            if 'ignore_count' in r: bp.SetIgnoreCount(bounded(r['ignore_count'], 0, 1000000))
            return {'ok': True, 'breakpoint': self.breakpoint_json(bp)}
        if op == 'pause':
            p = self.process()
            if not p.IsValid(): raise RuntimeError('no process')
            if p.GetState() not in STOPPED: error_check(p.Stop())
            self.invalidate(); return {'ok': True, 'acknowledged': True, 'status': self.status()}
        if op in ('resume', 'step'):
            self.stopped(r)
            if op == 'step':
                t, f = self.frame(r)
                mode = r.get('mode', 'over')
                if int(r.get('frame_index', 0)) != 0: raise ValueError('stepping requires frame_index 0')
                if mode not in ('over', 'into', 'out', 'instruction', 'instruction_over'): raise ValueError('invalid step mode')
            self.debugger.SetAsync(True)
            self.invalidate()
            self.published_state = lldb.eStateRunning
            if op == 'resume':
                err = self.process().Continue()
                if err.Fail(): self.published_state = self.process().GetState()
                error_check(err)
            else:
                if mode == 'over': t.StepOver(lldb.eOnlyDuringStepping)
                elif mode == 'into': t.StepInto(lldb.eOnlyDuringStepping)
                elif mode == 'out': t.StepOut()
                elif mode == 'instruction': t.StepInstruction(False)
                elif mode == 'instruction_over': t.StepInstruction(True)
                else: raise ValueError('invalid step mode')
            return {'ok': True, 'acknowledged': True, 'status': self.status()}
        if op in ('output', 'events'):
            records = list(self.output if op == 'output' else self.events)
            if op == 'events': records = [e for e in records if e['seq'] > int(r.get('after', 0))]
            return {'ok': True, 'records': records, 'bounded_retention': True, 'complete_history': False}
        if op == 'modules':
            target = self.target(); start = bounded(r.get('start', 0), 0, 100000); count = bounded(r.get('count', 200), 1, 200)
            end = min(target.GetNumModules(), start + count)
            return {'ok': True, 'start': start, 'total': target.GetNumModules(), 'modules': [{'path': file_path(target.GetModuleAtIndex(i).GetFileSpec()), 'uuid': target.GetModuleAtIndex(i).GetUUIDString(), 'triple': target.GetModuleAtIndex(i).GetTriple()} for i in range(start, end)], 'truncated': target.GetNumModules() > end, 'has_more': target.GetNumModules() > end}
        if op in ('detach', 'terminate'):
            if op == 'terminate': self.require_mutation(r)
            self.remove_owned_probes()
            p = self.process()
            if p.IsValid() and p.GetState() not in (lldb.eStateExited, lldb.eStateDetached):
                error_check(p.Detach(bool(r.get('keep_stopped', False))) if op == 'detach' else p.Kill())
            self.invalidate(); self.release()
            return {'ok': True, 'status': self.status(), 'requested_disposition': 'stopped' if r.get('keep_stopped') else ('terminated' if op == 'terminate' else 'running')}
        if op == 'shutdown':
            live_targets = []
            for i in range(self.debugger.GetNumTargets()):
                p = self.debugger.GetTargetAtIndex(i).GetProcess()
                if p.IsValid() and p.GetState() not in (lldb.eStateExited, lldb.eStateDetached, lldb.eStateInvalid):
                    live_targets.append({'target_index': i, 'pid': p.GetProcessID()})
            if live_targets:
                raise ValueError('explicitly dispose every live target before shutdown: ' + json.dumps(live_targets))
            self.release(); self.closed = True; return {'ok': True}
        if op == 'raw':
            if r.get('allow_unsafe') is not True: raise ValueError('raw commands need allow_unsafe=true; this grants trusted host and target execution, not a sandbox')
            self.invalidate()
            result = lldb.SBCommandReturnObject()
            self.debugger.GetCommandInterpreter().HandleCommand(r['command'], result)
            self.reconcile()
            return {'ok': result.Succeeded(), 'output': (result.GetOutput() or '')[:65536], 'error': (result.GetError() or '')[:65536],
                    'mode': 'trusted_raw_may_execute_or_mutate', 'status': self.status(), 'output_may_be_truncated': True}
        token = self.stopped(r)
        result = {'ok': True, 'stop_token': token, 'target_execution_requested': False,
                  'execution_policy': 'raw_no_dynamic_no_synthetic; native metadata work is not proven pure'}
        if op == 'threads':
            p = self.process(); count = min(p.GetNumThreads(), 100)
            result['threads'] = [{'thread_id': p.GetThreadAtIndex(i).GetThreadID(), 'index_id': p.GetThreadAtIndex(i).GetIndexID(), 'name': p.GetThreadAtIndex(i).GetName(), 'top': self.frame_json(p.GetThreadAtIndex(i).GetFrameAtIndex(0))} for i in range(count)]
            result['truncated'] = p.GetNumThreads() > count
        elif op == 'stack':
            t, f = self.frame(r); start = bounded(r.get('start', 0), 0, 10000); count = bounded(r.get('count', 30), 1, 100)
            result.update(thread_id=t.GetThreadID(), frames=[self.frame_json(t.GetFrameAtIndex(i)) for i in range(start, min(t.GetNumFrames(), start + count))], has_more=t.GetNumFrames() > start + count)
        elif op in ('variables', 'children'):
            depth = bounded(r.get('depth', 1), 0, 5); count = bounded(r.get('count', 20), 1, 50); budget = [200]
            if op == 'children':
                value = self.refs.get(r['reference'])
                if value is None: raise ValueError('unknown or invalidated value reference')
                start = bounded(r.get('start', 0), 0, 100000)
                total = value.GetNumChildren(start + count + 1)
                values = [value.GetChildAtIndex(i, lldb.eNoDynamicValues, False) for i in range(start, min(total, start + count))]
                result.update(start=start, has_more=total > start + count)
            else:
                t, f = self.frame(r)
                result.update(thread_id=t.GetThreadID(), frame=self.frame_json(f))
                if r.get('path'):
                    path = r['path']
                    if not isinstance(path, list) or not path: raise ValueError('path is a nonempty array of member names/indices, not an expression')
                    scope = r.get('scope', 'frame')
                    if scope == 'frame': value = f.FindVariable(str(path[0]), lldb.eNoDynamicValues)
                    elif scope == 'global':
                        candidates = self.target().FindGlobalVariables(str(path[0]), 2)
                        if candidates.GetSize() > 1: raise ValueError('ambiguous global; use a qualified name or raw symbol investigation')
                        value = candidates.GetValueAtIndex(0)
                    else: raise ValueError('scope must be frame or global')
                    result['lookup_scope'] = scope
                    for member in path[1:]:
                        value = value.GetNonSyntheticValue()
                        value = value.GetChildAtIndex(member, lldb.eNoDynamicValues, False) if isinstance(member, int) else value.GetChildMemberWithName(member, lldb.eNoDynamicValues)
                    values = [value]
                else:
                    collection = f.GetVariables(True, True, True, True, lldb.eNoDynamicValues)
                    values = [collection.GetValueAtIndex(i) for i in range(min(count, collection.GetSize()))]
                    result['has_more'] = collection.GetSize() > count
            result['values'] = []
            for value in values:
                if budget[0] <= 0: result['truncated'] = True; break
                result['values'].append(self.value_json(value, depth, count, budget))
        elif op == 'evaluate':
            self.require_execution(r); t, f = self.frame(r)
            opts = lldb.SBExpressionOptions(); opts.SetTimeoutInMicroSeconds(bounded(r.get('timeout_us', 500000), 1000, 5000000))
            opts.SetTryAllThreads(False); opts.SetUnwindOnError(True); opts.SetIgnoreBreakpoints(True)
            opts.SetFetchDynamicValue(lldb.eNoDynamicValues)
            languages = {'swift': lldb.eLanguageTypeSwift, 'objc': lldb.eLanguageTypeObjC_plus_plus, 'c': lldb.eLanguageTypeC, 'cpp': lldb.eLanguageTypeC_plus_plus}
            if 'language' in r: opts.SetLanguage(languages[r['language']])
            self.invalidate()
            value = f.EvaluateExpression(r['expression'], opts)
            result['value'] = self.value_json(value, 1, 20)
            result['ok'] = value.IsValid() and value.GetError().Success()
            result['executed_target_code'] = 'permitted_may_have_executed'
            result['target_execution_requested'] = True
            result['execution_policy'] = 'explicit_evaluation_not_pure; timeout_and_unwind_are_not_rollback'
            result['thread_id'] = t.GetThreadID()
            result['frame'] = self.frame_json(f)
            result['prior_stop_token'] = token
            result['status'] = self.status()
            result['stop_token'] = self.token()
            return result
        elif op in ('memory_read', 'memory_write'):
            address = int(str(r['address']), 0)
            err = lldb.SBError()
            if op == 'memory_read':
                count = bounded(r.get('count', 64), 1, 4096)
                data = self.process().ReadMemory(address, count, err); error_check(err)
                result.update(address=hex(address), hex=data.hex(), bytes_read=len(data), requested_bytes=count)
            else:
                self.require_mutation(r)
                data = bytes.fromhex(r['hex'])
                if not 0 < len(data) <= 4096: raise ValueError('write size must be 1..4096')
                self.invalidate(); written = self.process().WriteMemory(address, data, err); error_check(err)
                return {'ok': written == len(data), 'bytes_written': written, 'status': self.status(), 'mutated_target': True}
        elif op == 'registers':
            t, f = self.frame(r); registers = f.GetRegisters()
            result['sets'] = [self.value_json(registers.GetValueAtIndex(i), 1, 50) for i in range(min(registers.GetSize(), 16))]
        elif op == 'disassemble':
            t, f = self.frame(r); address = f.GetPCAddress() if 'address' not in r else self.target().ResolveLoadAddress(int(str(r['address']), 0))
            instructions = self.target().ReadInstructions(address, bounded(r.get('count', 20), 1, 100))
            result['instructions'] = [{'address': hex(ins.GetAddress().GetLoadAddress(self.target())), 'mnemonic': ins.GetMnemonic(self.target()), 'operands': ins.GetOperands(self.target()), 'comment': ins.GetComment(self.target())} for ins in instructions]
        elif op == 'watchpoint_add':
            size = int(r['size'])
            if size not in (1, 2, 4, 8): raise ValueError('hardware watch size must be 1, 2, 4 or 8')
            err = lldb.SBError(); watch = self.target().WatchAddress(int(str(r['address']), 0), size, bool(r.get('read', False)), bool(r.get('write', True)), err); error_check(err)
            self.owned_watchpoints.add(watch.GetID())
            result['watchpoint'] = {'id': watch.GetID(), 'address': hex(watch.GetWatchAddress()), 'size': watch.GetWatchSize(), 'enabled': watch.IsEnabled()}
        elif op == 'watchpoint_delete':
            ident = int(r['id'])
            if ident not in self.owned_watchpoints: raise ValueError('not an owned watchpoint')
            result['ok'] = self.target().DeleteWatchpoint(ident); self.owned_watchpoints.discard(ident)
        else: raise ValueError('unknown operation: ' + str(op))
        self.reconcile()
        if self.token() != token: raise RuntimeError('state changed during inspection; discard partial values and obtain a fresh stop')
        result['timestamp'] = time.time()
        return result

def serve(debugger, folder):
    secret = json.loads((Path(folder) / 'bootstrap.json').read_text())['token']
    # Do not share the CLI debugger's event/IO consumer. Its console handler can
    # also process stops and consume stdout while this Python command is active.
    # A dedicated SBDebugger makes this worker the only process-event controller.
    isolated_debugger = lldb.SBDebugger.Create(False)
    worker = Worker(isolated_debugger, folder)
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0)); server.listen(16); server.settimeout(.05)
        config = {'port': server.getsockname()[1], 'token': secret, 'worker_pid': os.getpid(), 'session_id': worker.session_id}
        path = Path(folder) / 'connection.json'
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: json.dump(config, f)
        while not worker.closed:
            worker.reconcile()
            try: conn, _ = server.accept()
            except socket.timeout: continue
            with conn:
                conn.settimeout(2)
                try:
                    data = bytearray()
                    while b'\n' not in data:
                        part = conn.recv(min(65536, MAX_MESSAGE + 1 - len(data)))
                        if not part: raise ValueError('incomplete request')
                        data.extend(part)
                        if len(data) > MAX_MESSAGE: raise ValueError('request too large')
                    envelope = json.loads(data.split(b'\n', 1)[0])
                    if not secrets.compare_digest(str(envelope.get('token', '')), secret): raise ValueError('unauthorized local client')
                    response = worker.dispatch(envelope['request'])
                except Exception as exc:
                    response = {'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}
                    try: response['status'] = worker.status()
                    except Exception: response['state'] = 'unknown'
                serialized = json.dumps(response, ensure_ascii=False).encode() + b'\n'
                if len(serialized) > MAX_MESSAGE:
                    serialized = b'{"ok":false,"error":"response exceeded limit; request less data"}\n'
                try: conn.sendall(serialized)
                except OSError: pass  # A lost response never replays a command.
    lldb.SBDebugger.Destroy(isolated_debugger)
