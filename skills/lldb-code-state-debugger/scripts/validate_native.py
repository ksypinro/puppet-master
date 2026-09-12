#!/usr/bin/env python3
"""Opt-in live C fixture validation. Launches/terminates only the supplied fixture."""
import argparse
import json
import os
from pathlib import Path
import time
import debugger

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture-dir', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--allow-fixture-execution', action='store_true', required=True)
    a = p.parse_args()
    root = Path(a.output_dir).resolve(); root.mkdir(mode=0o700, parents=True, exist_ok=False)
    session = root / 'session'
    source = Path(__file__).resolve().parents[1] / 'assets/fixtures/native/code_state.c'
    executable = Path(a.fixture_dir).resolve() / 'code-state-c'
    records = []; checks = []; sequence = 0
    def record(label, request, response):
        nonlocal sequence
        sequence += 1
        item = {'label':label, 'request':request, 'response':response, 'timestamp':time.time()}
        records.append(item)
        fd = os.open(str(root / ('%03d-%s.json' % (sequence,label))), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: json.dump(item, f, indent=2)
        return response
    def call(label, op, expect=True, **kw):
        req = dict(op=op, **kw); r = record(label, req, debugger.exchange(session, req, timeout=20))
        if expect: assert r.get('ok'), (label,r)
        return r
    def check(name, condition):
        checks.append({'check':name,'passed':bool(condition)})
        assert condition, name
    def status(): return debugger.exchange(session, {'op':'status'})
    def token(): return status()['stop_token']
    def stopped_call(label, op, **kw): return call(label, op, stop_token=token(), **kw)
    def wait(label, after, bp=None):
        r = record(label, {'wait_after':after,'breakpoint':bp}, debugger.wait_stop(session,after,30,bp))
        assert r.get('ok'), r
        return r['observation']
    def line(marker): return next(i for i,t in enumerate(source.read_text().splitlines(),1) if 'FIXTURE:'+marker in t)
    def variable(name, **kw): return stopped_call('value-'+name, 'variables',path=[name],scope='global' if name.startswith('fixture_') else 'frame', **kw)['values'][0]
    try:
        record('start',{},debugger.start(session))
        call('capabilities','capabilities')
        call('target','target', executable=str(executable),context={'fixture_source':str(source)})
        pending = call('pending','breakpoint_add',name='NO_SUCH_FIXTURE_SYMBOL_123')['breakpoint']
        check('pending symbol is not verified',not pending['verified'] and pending['locations_count']==0)
        call('delete-pending','breakpoint_delete',id=pending['id'])
        sym = call('symbol','breakpoint_add',name='apply_debit')['breakpoint']
        check('symbol resolves file locations',sym['locations_count']>=1)
        call('delete-symbol','breakpoint_delete',id=sym['id'])
        bp=call('source-condition','breakpoint_add',file=str(source),line=line('C_BEFORE_WRITE'),condition='index == 2',allow_target_execution=True)['breakpoint']['id']
        final=call('final-breakpoint','breakpoint_add',file=str(source),line=line('C_FINAL'))['breakpoint']['id']
        call('launch','launch',stop_at_entry=True)
        wait('entry','none')
        old=token(); call('resume','resume',stop_token=old); stop=wait('condition-hit',old,bp)
        check('actual expected breakpoint stop',bp in stop['breakpoint_ids'])
        bps=call('resolved-breakpoints','breakpoints')['breakpoints']
        check('source location resolved in live target',next(b for b in bps if b['id']==bp)['verified'])
        original_token=token()
        invalid=call('invalid-step','step',expect=False,stop_token=original_token,mode='not-a-mode')
        check('invalid step preserves stopped state',not invalid['ok'] and token()==original_token)
        st=stopped_call('stack','stack',count=10)
        check('callee and caller stack',any('apply_debit' in (f['function'] or '') for f in st['frames']) and any(f['function']=='main' for f in st['frames']))
        for name,expected in [('index','2'),('before','805'),('signed_amount','40'),('fixture_balance','805')]:
            check(name+' expected value',variable(name)['value']==expected)
        missing_local=stopped_call('global-not-local','variables',path=['fixture_balance'],scope='frame')
        check('local lookup does not silently become global',not missing_local['values'][0]['available'] and missing_local['lookup_scope']=='frame')
        debit=variable('debit',depth=0)
        page=stopped_call('children','children',reference=debit['reference'],start=0,count=1)
        check('bounded child paging',page['has_more'] and page['values'][0]['name']=='amount' and page['values'][0]['value']=='40')
        bytes_value=variable('fixture_bytes',depth=0)
        mem=stopped_call('memory','memory_read',address=bytes_value['address'],count=8)
        check('known eight bytes',mem['hex']=='0011223344556677')
        bad=call('bad-memory','memory_read',expect=False,stop_token=token(),address='0x0',count=8)
        check('invalid memory retains error',not bad['ok'] and bool(bad.get('error')))
        denied=call('evaluation-denied','evaluate',expect=False,stop_token=token(),expression='1+1')
        check('evaluation needs explicit authorization',not denied['ok'])
        denied=call('write-denied','memory_write',expect=False,stop_token=token(),address=bytes_value['address'],hex='aa')
        check('write needs explicit authorization',not denied['ok'])
        stopped_call('threads','threads'); stopped_call('registers','registers'); stopped_call('disassembly','disassemble',count=8); call('modules','modules')
        module_page=call('module-page','modules',start=0,count=1)
        check('module metadata is pageable',len(module_page['modules'])==1 and module_page['has_more'])
        check('machine state operations',True)
        old=token(); evaluation=stopped_call('expression','evaluate',expression='before + signed_amount',language='c',allow_target_execution=True)
        check('evaluation metadata is execution-capable',evaluation['target_execution_requested'] is True and 'not_pure' in evaluation['execution_policy'])
        stale=call('stale-expression-stop','variables',expect=False,stop_token=old,path=['before'])
        check('expression invalidates token',not stale['ok'])
        balance=variable('fixture_balance')
        watch=stopped_call('watch','watchpoint_add',address=balance['address'],size=4,write=True)['watchpoint']['id']
        call('disable-source','breakpoint_update',id=bp,enabled=False)
        old=token(); call('continue-to-writer','resume',stop_token=old); watchstop=wait('writer-hit',old)
        check('hardware write stop',any('watchpoint' in (r['description'] or '') for r in watchstop['stop_reasons']))
        check('wrong writer observed',variable('fixture_balance')['value']=='845')
        stopped_call('delete-watch','watchpoint_delete',id=watch)
        old=token(); stopped_call('step-over','step',mode='over'); wait('step-complete',old)
        stale=call('stale-step-stop','children',expect=False,stop_token=old,reference=debit['reference'])
        check('step invalidates handles',not stale['ok'])
        old=token(); stopped_call('step-out','step',mode='out'); wait('step-out-complete',old)
        check('step out to caller',stopped_call('caller','stack',count=3)['frames'][0]['function']=='main')
        old=token(); call('resume-to-final','resume',stop_token=old); wait('final-hit',old,final)
        check('actual mismatch',variable('actual')['value']=='845' and variable('expected')['value']=='765')
        # One reversible mutation of artificial bytes, not application business state.
        stopped_call('fixture-write','memory_write',address=bytes_value['address'],hex='aa11223344556677',allow_mutation=True)
        check('memory write verified',stopped_call('read-written','memory_read',address=bytes_value['address'],count=8)['hex']=='aa11223344556677')
        stopped_call('fixture-restore','memory_write',address=bytes_value['address'],hex='0011223344556677',allow_mutation=True)
        denied=call('live-shutdown-denied','shutdown',expect=False)
        check('shutdown refuses live target',not denied['ok'])
        call('raw-selects-other-target','raw',command='target create "'+str(executable)+'"',allow_unsafe=True)
        hidden=call('hidden-live-target-shutdown','shutdown',expect=False)
        check('shutdown checks every target',not hidden['ok'] and 'every live target' in hidden['error'])
        blocked=call('typed-target-switch-denied','variables',expect=False,stop_token=token(),path=['actual'])
        check('raw target switch blocks typed reads',not blocked['ok'])
        call('restore-managed-target','raw',command='target select 0',allow_unsafe=True)
        check('managed context restored',status()['managed_selection'])
        call('delete-final','breakpoint_delete',id=final)
        old=token(); call('finish','resume',stop_token=old)
        deadline=time.monotonic()+10
        while status()['state']!='exited' and time.monotonic()<deadline: time.sleep(.05)
        check('fixture exits',status()['state']=='exited')
        call('output','output'); call('events','events')
        call('replace-exited-target','target',executable=str(executable))
        check('replacement clears owner metadata',status()['owner'] is None)
        unowned=call('old-probe-not-owned','breakpoint_delete',expect=False,id=bp)
        check('probe IDs do not transfer to replacement target',not unowned['ok'])
        call('relaunch-fixture','launch',stop_at_entry=True); wait('relaunch-entry','none')
        call('terminate-relaunched-fixture','terminate',allow_mutation=True)
    except Exception as exc:
        record('failure',{}, {'ok':False,'error':str(exc)})
        raise
    finally:
        if (session/'connection.json').exists():
            s=status()
            if s['state'] not in ('unloaded','invalid','exited','detached'):
                call('cleanup-owned-fixture','terminate',allow_mutation=True)
            call('shutdown','shutdown')
        record('checks',{}, {'ok':bool(checks) and all(c['passed'] for c in checks),'checks':checks})
    print(json.dumps({'ok':True,'checks_passed':len(checks),'evidence':str(root)},indent=2))

if __name__=='__main__': main()
