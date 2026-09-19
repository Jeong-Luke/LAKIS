#!/usr/bin/env python3
"""Run bounded, isolated recovery tests; no package installs or paid API calls.

Usage: python installer/tests/run_recovery_tests.py --report-dir /path/out
Optional --source PATH runs the SAME new assertions against another snapshot.
Use the portable runtime's Python (aiohttp, Pillow, torch) and Node on PATH.
The Windows/PowerShell/GPU integration gates are explicitly not performed.
"""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

NEW_TESTS=['test_recovery_patch.py','test_recovery_http.py','test_recovery_providers.py',
           'test_recovery_graphs.py','test_release_component_contract.py']
EXISTING_TESTS=['test_error_codes.py','test_installation_isolation.py','test_library_metadata.py',
                'test_ui_state_scoping.py','test_upscaler_state.py']

def child(test_path: Path, report: Path) -> int:
    """One module per process avoids sys.modules stubs crossing test suites."""
    original_connect=socket.socket.connect
    original_connect_ex=socket.socket.connect_ex
    def guard(address):
        if isinstance(address,tuple):
            host=address[0]
            if host=='localhost':return
            try:allowed=ipaddress.ip_address(host).is_loopback
            except ValueError:allowed=False
            if not allowed:raise RuntimeError('External network forbidden in recovery tests')
    def connect(s,address):guard(address);return original_connect(s,address)
    def connect_ex(s,address):guard(address);return original_connect_ex(s,address)
    socket.socket.connect=connect;socket.socket.connect_ex=connect_ex
    records={}
    class Result(unittest.TextTestResult):
        def startTest(self,test):
            records[test.id()]={'name':test.id(),'status':'RUNNING'};super().startTest(test)
        def addSuccess(self,test):records[test.id()]['status']='PASS';super().addSuccess(test)
        def addFailure(self,test,err):
            records.setdefault(test.id(),{'name':test.id()}).update(status='FAIL',error=self._exc_info_to_string(err,test))
            super().addFailure(test,err)
        def addError(self,test,err):
            records.setdefault(test.id(),{'name':test.id()}).update(status='ERROR',error=self._exc_info_to_string(err,test))
            super().addError(test,err)
        def addSkip(self,test,reason):
            records.setdefault(test.id(),{'name':test.id()}).update(status='SKIP',reason=reason);super().addSkip(test,reason)
        def addSubTest(self,test,subtest,err):
            if err:
                records[test.id()].update(status='FAIL' if issubclass(err[0],test.failureException) else 'ERROR',
                    error=self._exc_info_to_string(err,test))
            super().addSubTest(test,subtest,err)
    spec=importlib.util.spec_from_file_location('recovery_cases',test_path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    # Keep real product audit writes inside the explicit report directory, not
    # beside the source snapshot. No audit implementation is replaced.
    for name in ("workflow_bridge", "serve_ui"):
        loaded=sys.modules.get(name)
        if loaded is not None and hasattr(loaded,"AUDIT_PATH"):
            loaded.AUDIT_PATH=report.parent/(name+"_audit.jsonl")
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    report.write_text(json.dumps({'test_file':test_path.name,'total':result.testsRun,
        'passed':sum(x['status']=='PASS' for x in records.values()),
        'failed':sum(x['status']=='FAIL' for x in records.values()),
        'errors':sum(x['status']=='ERROR' for x in records.values()),
        'skipped':sum(x['status']=='SKIP' for x in records.values()),
        'results':list(records.values())},ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result.wasSuccessful() else 1

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--child',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    args.report_dir.mkdir(parents=True,exist_ok=True)
    if args.child:return child(args.child,args.report_dir/'case_results.json')
    source=args.source.resolve();test_root=Path(__file__).resolve().parent
    summary={'source_root':str(source),'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'python':sys.version,'platform':platform.platform(), 'suites':[],
        'scope':'new/legacy unit, CPU tensor, actual loopback HTTP, JS VM, static source; not Windows/GPU/browser',
        'not_run':['Windows C# compilation and EXE execution','PowerShell release/repair gates',
            'Fresh install / legacy updater / repair integration','Real ComfyUI GPU generation and browser rendering',
            'Pinned RealESRGAN download test (requires verified model fixture; no model downloaded)']}
    overall=True
    for test_file in NEW_TESTS+EXISTING_TESTS:
        test_path=(test_root if test_file in NEW_TESTS else source/'installer/tests')/test_file
        directory=args.report_dir/test_file.removesuffix('.py');directory.mkdir(exist_ok=True)
        # A crashed child must not inherit a previous run's successful JSON.
        (directory/'case_results.json').unlink(missing_ok=True)
        env=os.environ.copy();env['LAKIS_TEST_SOURCE_ROOT']=str(source)
        env.pop('LAKIS_CAPTURE_GRAPH_HASHES',None)
        started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix='lakis-test-state-') as appdata:
            env['LOCALAPPDATA']=appdata
            try:
                completed=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',str(test_path),
                    '--report-dir',str(directory)],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35)
                code=completed.returncode;log=completed.stdout+'\n'+completed.stderr
            except subprocess.TimeoutExpired as error:
                code=124
                def decoded(value):
                    return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else (value or '')
                log='Test module exceeded 35 seconds; terminated.\n'+decoded(error.stdout)+'\n'+decoded(error.stderr)
        (directory/'console.log').write_text(log,encoding='utf-8')
        result_path=directory/'case_results.json'
        payload=json.loads(result_path.read_text()) if result_path.exists() else {'test_file':test_file,'status':'TIMEOUT' if code==124 else 'HARNESS_ERROR','total':0}
        payload.update(exit_code=code,elapsed_seconds=round(time.monotonic()-started,3))
        summary['suites'].append(payload);overall=overall and code==0
        print(f"{test_file}: exit={code}; passed={payload.get('passed',0)}/{payload.get('total',0)}",flush=True)
    node=shutil.which('node')
    if node:
        env=os.environ.copy();env['LAKIS_TEST_SOURCE_ROOT']=str(source)
        try:
            completed=subprocess.run([node,str(test_root/'test_recovery_autopatch.cjs')],env=env,
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
            (args.report_dir/'autopatch_console.log').write_text(completed.stdout+'\n'+completed.stderr,encoding='utf-8')
            payload=json.loads(completed.stdout);payload.update(test_file='test_recovery_autopatch.cjs',exit_code=completed.returncode)
            summary['suites'].append(payload);overall=overall and completed.returncode==0
        except (subprocess.TimeoutExpired,ValueError) as error:
            summary['suites'].append({'test_file':'test_recovery_autopatch.cjs','total':0,'status':'HARNESS_ERROR','error':str(error)});overall=False
    else:
        summary['suites'].append({'test_file':'test_recovery_autopatch.cjs','total':0,'status':'NOT_RUN','reason':'node is not installed'});overall=False
    summary['total']=sum(x.get('total',0) for x in summary['suites'])
    summary['passed']=sum(x.get('passed',0) for x in summary['suites'])
    summary['result']='PASS_WITH_UNTESTED_INTEGRATION_GATES' if overall else 'FAIL'
    summary['finished_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    (args.report_dir/'TEST_RESULTS.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{summary['result']}: {summary['passed']}/{summary['total']}")
    return 0 if overall else 1

if __name__=='__main__':raise SystemExit(main())
