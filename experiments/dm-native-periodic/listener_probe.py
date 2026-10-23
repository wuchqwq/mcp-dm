#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Separate finite native-to-C1-listener busy experiment. No production imports."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid

import client

HERE = Path(__file__).resolve().parent
PROBE_FILE = HERE.parent / "dm-event-listener" / "probe.py"


def c1_module():
    spec = importlib.util.spec_from_file_location("c1_external_template", str(PROBE_FILE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(root, host_pid):
    root = Path(root).resolve()
    path = root.as_posix()
    if any(ord(c)<32 or ord(c)>126 or c=='"' for c in path): raise ValueError("Unsafe path")
    if isinstance(host_pid,bool) or not isinstance(host_pid,int) or host_pid<=0: raise ValueError("Bad host PID")
    root.mkdir(parents=True, exist_ok=False)
    (root / "issued").mkdir()
    token = uuid.uuid4().hex
    template = (HERE / "listener_task.s.in").read_text(encoding="utf-8")
    template_sha = hashlib.sha256(template.encode("utf-8")).hexdigest()
    client.save(root / "session.json", dict(token=token, expected_host_pid=host_pid,
                template_sha256=template_sha, hold_nonce=uuid.uuid4().hex))
    client.bind_host(root, host_pid)
    probe = c1_module()
    probe.prepare(root / "listener")
    for key, value in {"ROOT":path,"TOKEN":token,"CLASS":token[:12],"SHA":template_sha}.items():
        template = template.replace("@"+key+"@",value)
    (root / "prepared_native_task.s").write_text(template, encoding="utf-8")
    starter = ("import importlib.util,sys,os,json,hashlib\nfrom pathlib import Path\n"
               "import DigitalMicrograph as DM\n"
               "if os.getpid()!=%d or not DM.IsScriptOnMainThread(): raise RuntimeError('Wrong host/thread')\n"
               "root=Path(%r)\nkey='mcp_dm_c1_probe'\n"
               "if key in sys.modules: raise RuntimeError('Existing C1 root; inspect cleanup first')\n"
               "spec=importlib.util.spec_from_file_location(key,%r)\n"
               "module=importlib.util.module_from_spec(spec)\nsys.modules[key]=module\n"
               "spec.loader.exec_module(module)\nmodule.register(str(root/'listener'))\n"
               "s=module.SESSION\n"
               "native=(root/'prepared_native_task.s').read_text().replace('@TRIGGER_ID@',str(int(s.trigger_id))).replace('@C1_TOKEN@',s.token)\n"
               "with (root/'executed_native_task.s').open('x') as f: f.write(native)\n"
               "DM.ExecuteScriptString(native)\n"
               "with (root/'starter_complete.json').open('x') as f:\n"
               "    json.dump(dict(token=%r,host_pid=os.getpid(),thread=__import__('threading').get_ident(),native_source_sha256=hashlib.sha256(native.encode()).hexdigest()),f)\n"
               "print('C1 listener and native periodic task registered; script returning')\n") % (
                   host_pid,str(root),str(PROBE_FILE),token)
    # The ungated host-run source is preserved privately. Do not silently make
    # a known-crashing experiment runnable again or treat a timer as admission.
    starter = "raise RuntimeError('QUARANTINED: real-host busy callback crashed Python; do not run')\n" + starter
    (root / "01_start_listener.py").write_text(starter, encoding="utf-8")
    busy = ("import os,time,json,threading\nfrom pathlib import Path\n"
            "root=Path(%r)\n"
            "if os.getpid()!=%d: raise RuntimeError('Wrong host')\n"
            "def mark(name):\n"
            "    with (root/(name+'.json')).open('x') as f:\n"
            "        json.dump(dict(token=%r,pid=os.getpid(),thread=threading.get_ident(),time=time.time(),monotonic=time.monotonic()),f)\n"
            "mark('busy_started')\ntry:\n    time.sleep(10)\nfinally:\n    mark('busy_finished')\n") % (str(root),host_pid,token)
    (root / "bounded_busy.py").write_text(busy, encoding="utf-8")
    cleanup = ("import sys,json\nfrom pathlib import Path\nroot=Path(%r)\n"
               "if not (root/'stopped.json').exists(): raise RuntimeError('Native task not confirmed stopped')\n"
               "if (root/'busy_started.json').exists() and not (root/'busy_finished.json').exists(): raise RuntimeError('Busy script not confirmed finished')\n"
               "m=sys.modules.get('mcp_dm_c1_probe')\n"
               "if m is None: raise RuntimeError('Missing C1 root; inspect')\n"
               "m.SESSION.cleanup()\n") % str(root)
    cleanup += probe.recovery_code()
    (root / "04_cleanup_listener.py").write_text(cleanup, encoding="utf-8")
    return {"state":"prepared_not_executed","directory":str(root)}


def _request_for_protocol_tests(root, action):
    root = Path(root)
    session = client.read(root / "session.json")
    if action not in ("wake","hold"): raise ValueError("Fixed experiment operations only")
    if (root / "stopped.json").exists(): raise RuntimeError("Stopped")
    if not (root / "starter_complete.json").exists(): raise RuntimeError("Registration not confirmed")
    if action == "wake":
        request_id = c1_module().make_request(root / "listener")["request_id"]
    else:
        request_id = uuid.uuid4().hex
    for slot in range(8):
        issued = dict(token=session["token"],request_id=request_id,slot=slot,operation=action,reserved_at=time.time())
        try: client.save(root / "issued" / (str(slot)+".json"),issued)
        except FileExistsError: continue
        data = (session["token"]+"|"+request_id+"|"+action.ljust(8)).ljust(128).encode("ascii")
        temporary = root / ("request_%d.pending"%slot)
        with temporary.open("xb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        client.atomic_publish(temporary,root/("request_%d.ready"%slot))
        return dict(issued,state="published_outcome_unknown")
    raise RuntimeError("Experiment request limit")


def request(root, action):
    raise RuntimeError("QUARANTINED after real DM Python access-violation; no new listener requests or automatic retries")


def _query(root, slot):
    root = Path(root)
    issued = client.read(root / "issued" / (str(slot)+".json"))
    native = client.query(root,slot)
    if issued["operation"] != "wake": return native
    path = root / "listener" / "replies" / (issued["request_id"]+".json")
    if not path.exists(): return dict(native,python_state="unknown_do_not_retry")
    probe = c1_module()
    request_data = probe.read_json(root/"listener"/"requests"/(issued["request_id"]+".json"))
    reply = probe.read_json(path)
    registered = probe.read_json(root/"listener"/"registered.json")
    session = client.read(root/"session.json")
    expected_sum = sum(10*y+x for y in range(8) for x in range(12))
    ok = (reply.get("state")=="completed" and reply.get("scope")=="real_dm" and
          reply.get("id")==issued["request_id"] and reply.get("token")==registered["token"] and
          reply.get("host_pid")==session["expected_host_pid"] and
          reply.get("request_sha256")==probe.fingerprint(request_data) and
          reply.get("result",{}).get("echo_nonce")==request_data["nonce"] and
          reply["result"].get("source_image_id")==registered["source_id"] and
          reply["result"].get("sum")==expected_sum and reply["result"].get("mean")==40.5 and
          reply["result"].get("min")==0 and reply["result"].get("max")==81 and
          reply["result"].get("shape_yx")==[8,12] and reply["result"].get("dtype")=="float32" and
          reply["result"].get("source_sha256")==registered["source_sha256"] and
          reply["result"].get("calibration_xy")==[[1.25,-0.25,"nm"],[-2.5,0.5,"nm"]])
    return dict(native,python_state="completed_verified" if ok else "unknown_invalid_reply",python_reply=reply)


def query(root, slot):
    try:
        return _query(root, slot)
    except (ValueError, KeyError, TypeError, FileNotFoundError):
        return {"state":"unknown","python_state":"unknown_invalid_or_incomplete_reply_do_not_retry"}


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("prepare","request","query","stop","cleanup-check"))
    p.add_argument("directory")
    p.add_argument("--host-pid",type=int)
    p.add_argument("--operation",choices=("wake","hold"),default="wake")
    p.add_argument("--slot",type=int,default=0)
    a=p.parse_args()
    if a.action=="prepare": result=prepare(a.directory,a.host_pid)
    elif a.action=="request": result=request(a.directory,a.operation)
    elif a.action=="query": result=query(a.directory,a.slot)
    elif a.action=="stop": result=client.stop(a.directory)
    else: result=client.cleanup_check(a.directory)
    print(json.dumps(result,indent=2,sort_keys=True))
