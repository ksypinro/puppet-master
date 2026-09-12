#!/usr/bin/env python3
"""Opt-in live Swift fixture validation, including artificial getter side effects."""
import argparse
import json
import os
from pathlib import Path
import time
import debugger

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--allow-fixture-execution',action='store_true',required=True)
    args=parser.parse_args()
    root=Path(args.output_dir).resolve();root.mkdir(mode=0o700,parents=True,exist_ok=False)
    session=root/'session'; seq=0;checks=[]
    source=Path(__file__).resolve().parents[1]/'assets/fixtures/native/code_state.swift'
    line=next(i for i,t in enumerate(source.read_text().splitlines(),1) if 'FIXTURE:SWIFT_BEFORE_WRITE' in t)
    def save(name,data):
        nonlocal seq
        seq+=1;fd=os.open(str(root/('%02d-%s.json'%(seq,name))),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2)
        return data
    def call(name,op,expect=True,**kw):
        req=dict(op=op,**kw);r=debugger.exchange(session,req,timeout=20);save(name,{'request':req,'response':r})
        if expect:assert r.get('ok'),r
        return r
    def status():return debugger.exchange(session,{'op':'status'})
    def stopped(name,op,**kw):return call(name,op,stop_token=status()['stop_token'],**kw)
    def check(name,value):checks.append({'check':name,'passed':bool(value)});assert value,name
    try:
        save('start',debugger.start(session))
        call('target','target',executable=str(Path(args.fixture_dir).resolve()/'code-state-swift'))
        bp=call('condition','breakpoint_add',file=str(source),line=line,condition='index == 2',allow_target_execution=True)['breakpoint']['id']
        call('launch','launch',stop_at_entry=False)
        w=save('wait-condition',debugger.wait_stop(session,'none',50,bp));assert w['ok'],w
        call('resolved-condition','breakpoints')
        r=stopped('raw-locals','variables',expect=False,depth=2)
        if not r['ok']:r=stopped('raw-locals-refreshed','variables',depth=2)
        values={v['name']:v for v in r['values']}
        check('Swift condition stopped at third debit',values['index']['value']=='2')
        check('Swift wrong delta before write',values['before']['value']=='805' and values['signedAmount']['value']=='40')
        stopped('stack','stack',count=8)
        old=status()['stop_token'];stopped('step-over','step',mode='over')
        w=save('step-done',debugger.wait_stop(session,old,10));check('Swift step completed',w['ok'])
        check('Swift write changes balance to845',stopped('balance-after-write','variables',path=['self','balance'])['values'][0]['value']=='845')
        check('description baseline0',stopped('description-before','variables',path=['self','descriptionReadCount'])['values'][0]['value']=='0')
        evaluated=stopped('typed-description','evaluate',expression='self.description',language='swift',timeout_us=2000000,allow_target_execution=True)
        check('getter response declares execution',evaluated['target_execution_requested'] is True)
        check('typed evaluation executes getter',stopped('description-after-evaluate','variables',path=['self','descriptionReadCount'])['values'][0]['value']=='1')
        po=call('po','raw',command='po self',allow_unsafe=True)
        check('po produced description','descriptionReads: 2' in po['output'])
        check('po changed stored state',stopped('description-after-po','variables',path=['self','descriptionReadCount'])['values'][0]['value']=='2')
        bad=stopped('bad-expression','evaluate',expect=False,expression='thisSymbolDoesNotExist_xyz',language='swift',allow_target_execution=True)
        check('expression error preserved',not bad['ok'])
        call('output','output');call('events','events')
    finally:
        if (session/'connection.json').exists():
            if status()['state'] not in ('exited','detached','unloaded','invalid'):call('terminate-owned','terminate',allow_mutation=True)
            call('shutdown','shutdown')
        save('checks',{'checks':checks})
    print(json.dumps({'ok':True,'checks_passed':len(checks),'evidence':str(root)},indent=2))

if __name__=='__main__':main()
