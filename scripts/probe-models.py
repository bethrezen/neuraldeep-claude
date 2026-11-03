#!/usr/bin/env python3
"""Probe model/billing routes. Dry run by default; --execute sends billable requests.

Receipts include no API keys or conversation bodies. Historical snapshots are
retained alongside the latest receipt, including failed results.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import base64
import copy
import datetime
import hashlib
import json
import os
import struct
import sys
import threading
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuraldeep_claude import catalog, protocol
from neuraldeep_claude.config import key_for, atomic_json
from neuraldeep_claude.transport import request, open_request, sse_chunks, UpstreamError

CAT = {}
KEYS = {}
TIMEOUT = 180
MAX_TOKENS = 4096
SUB_INTERVAL = 0.55
WRITE_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
NEXT_SUB = [0.0]
RESULT = {}

def png_chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
PNG=b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',struct.pack('>IIBBBBB',32,32,8,2,0,0,0))+png_chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*32)*32))+png_chunk(b'IEND',b'')
IMAGE=base64.b64encode(PNG).decode()

def wait_rate(mode):
 if mode!='subscription':return
 with RATE_LOCK:
  now=time.monotonic();pause=max(0,NEXT_SUB[0]-now);NEXT_SUB[0]=max(now,NEXT_SUB[0])+SUB_INTERVAL
 if pause:time.sleep(pause)

def call(model,body,kind,stream=False,effort=None):
 started=time.monotonic();m=copy.deepcopy(model)
 if effort:m['selected_effort']=effort
 body=copy.deepcopy(body);body['stream']=stream
 rec={'kind':kind,'effort_requested':effort or m.get('default_effort'),'stream':stream,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  translated=protocol.to_openai(body,m,m['upstream_id']);wait_rate(m['billing'])
  if stream:
   with open_request('POST','/v1/chat/completions',KEYS[m['billing']],translated,timeout=TIMEOUT) as response:
    content_type=response.headers.get('Content-Type','')
    if 'text/event-stream' in content_type:
     chunks=list(sse_chunks(response));events=list(protocol.stream_openai(chunks,m['id']))
     text=''.join(e.get('delta',{}).get('text','') for e in events)
     think=''.join(e.get('delta',{}).get('thinking','') for e in events)
     rec.update({'sse_chunks':len(chunks),'sse_events':len(events),'finish_reason':events[-2]['delta']['stop_reason'],'usage':events[-2]['usage']})
     reply={'content':[{'type':'text','text':text}]}
    else:
     res=json.load(response);reply=protocol.from_openai(res,m['id']);text='\n'.join(b.get('text','') for b in reply['content'] if b['type']=='text');think='\n'.join(b.get('thinking','') for b in reply['content'] if b['type']=='thinking');rec.update({'sse_response':False,'finish_reason':reply['stop_reason'],'usage':reply['usage']})
  else:
   res=request('POST','/v1/chat/completions',KEYS[m['billing']],translated,timeout=TIMEOUT);reply=protocol.from_openai(res,m['id']);text='\n'.join(b.get('text','') for b in reply['content'] if b['type']=='text');think='\n'.join(b.get('thinking','') for b in reply['content'] if b['type']=='thinking');rec.update({'finish_reason':reply['stop_reason'],'usage':reply['usage']})
  calls=[b for b in reply['content'] if b['type']=='tool_use'];rec.update({'status':'PASS','text_chars':len(text),'thinking_chars':len(think),'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'tool_calls':len(calls)})
  if kind in ['text','effort']:
   rec['expected_answer']=bool('OK' in text.upper())
   if not text.strip():rec['status']='FAIL_EMPTY_FINAL'
   elif not rec['expected_answer']:rec['status']='FAIL_EXPECTED_ANSWER'
   if effort:rec['effort_application']='accepted-effective-value-unverified'
  elif kind=='vision':
   rec['expected_answer']='red' in text.lower()
   if not rec['expected_answer']:rec['status']='FAIL_VISION_COLOR'
  elif kind=='tools':
   rec['parallel_tools_returned']=len(calls)>=2
   rec['valid_tool_inputs']=bool(calls) and all(b.get('name')=='echo' and isinstance(b.get('input'),dict) and isinstance(b['input'].get('value'),str) for b in calls)
   if not rec['valid_tool_inputs']:rec['status']='FAIL_TOOL_CALL'
  elif kind=='tool-roundtrip':
   rec['expected_answer']='ECHO42' in text and 'ECHO43' in text
   if not text.strip():rec['status']='FAIL_EMPTY_FINAL'
   elif not rec['expected_answer']:rec['status']='FAIL_EXPECTED_TOOL_RESULT'
  return rec,reply
 except UpstreamError as e:
  # Capture service error categories only; prompts and key material are never logged.
  msg=''
  try:
   data=json.loads(e.data);detail=data.get('error',data.get('detail',{}));msg=detail.get('message','') if isinstance(detail,dict) else str(detail)
  except Exception:pass
  for key in KEYS.values():msg=msg.replace(key,'[redacted]')
  rec.update({'status':'HTTP_ERROR','http_status':e.status,'error_message':msg[:500],'retry_after':e.headers.get('Retry-After'),'window':e.headers.get('X-Window')})
  return rec,None
 except Exception as e:
  rec.update({'status':'ERROR','error_type':type(e).__name__,'error_message':str(e)[:300]})
  return rec,None
 finally:rec['seconds']=round(time.monotonic()-started,3)

def test(model):
 out={'model':model['id'],'upstream_id':model['upstream_id'],'billing':model['billing'],'parameters':model.get('parameters',{}),'effort_status':model.get('effort_status'),'checks':[]}
 textbody={'max_tokens':MAX_TOKENS,'messages':[{'role':'user','content':'Reply exactly OK.'}]}
 rec,reply=call(model,textbody,'text',True);out['checks'].append(rec)
 # A route unavailable at service level is not called repeatedly; retain one definitive receipt.
 if rec['status']=='HTTP_ERROR' and rec.get('http_status') in [401,402,403,404,429,502,503,504]:
  out['skipped_after_unavailable']=True;return out
 toolbody={'max_tokens':MAX_TOKENS,'messages':[{'role':'user','content':'Call echo twice in parallel: value ECHO42, then value ECHO43. Use the tool, do not write text instead.'}],
  'tools':[{'name':'echo','description':'Returns value unchanged. Call this function when asked to echo a value.','input_schema':{'type':'object','properties':{'value':{'type':'string'}},'required':['value']}}],
  'tool_choice':{'type':'auto'}}
 rec,reply=call(model,toolbody,'tools');out['checks'].append(rec)
 if reply:
  calls=[b for b in reply['content'] if b['type']=='tool_use']
  if calls:
   toolbody['messages'].append({'role':'assistant','content':reply['content']})
   toolbody['messages'].append({'role':'user','content':[{'type':'tool_result','tool_use_id':b['id'],'content':str(b.get('input',{}).get('value','invalid'))} for b in calls]+[{'type':'text','text':'Give both returned values in one short answer without further tool calls.'}]})
   toolbody['tool_choice']={'type':'none'}
   rec,_=call(model,toolbody,'tool-roundtrip');out['checks'].append(rec)
 if model.get('capabilities',{}).get('vision'):
  vis={'max_tokens':MAX_TOKENS,'messages':[{'role':'user','content':[{'type':'text','text':'Name the single solid color shown in this image, in one English word.'},{'type':'image','source':{'type':'base64','media_type':'image/png','data':IMAGE}}]}]}
  rec,_=call(model,vis,'vision');out['checks'].append(rec)
 for effort in model.get('efforts',[]):
  rec,_=call(model,textbody,'effort',False,effort);out['checks'].append(rec)
 return out


def selected_models(data, billing, requested):
    """Select exact billing routes, resolving aliases and old effort IDs once."""
    selected = None
    if requested:
        selected = {catalog.resolve(data, name)["id"] for name in requested}
    models = [model for model in data["models"].values()
              if (billing == "all" or model["billing"] == billing)
              and (selected is None or model["id"] in selected)
              and catalog.picker_status(data, model) != "retired"]
    if not models:
        raise ValueError("No models match --model and --billing; use an explicit matching billing route")
    models.sort(key=lambda model: (model["upstream_id"], model["billing"]))
    return models


def aggregate_results(previous, current, run_path, prior_path=None):
    """Keep latest results per route, while raw run receipts stay independent."""
    old = previous or {}
    previous_checks = old.get("checks", [])
    updates = {row["model"]: copy.deepcopy(row) for row in current["checks"]}
    merged = []
    seen = set()
    for original in previous_checks:
        row = copy.deepcopy(original)
        identity = row["model"]
        if identity in updates:
            row = updates[identity]
        else:
            # Historic row outcomes are unchanged. Add missing provenance only;
            # an updated aggregate timestamp must not redate an old model test.
            row.setdefault("checked_at", old.get("finished_at") or old.get("updated_at") or old.get("started_at"))
            if prior_path is not None:
                row.setdefault("run_receipt", str(prior_path))
        merged.append(row)
        seen.add(identity)
    merged.extend(row for identity, row in updates.items() if identity not in seen)
    result = copy.deepcopy(current)
    result.update(receipt_kind="aggregate", checks=merged,
                  latest_run_receipt=str(run_path), model_count=len(merged),
                  latest_run_models=[row["model"] for row in current["checks"]])
    if old:
        result["previous_aggregate_finished_at"] = old.get("finished_at")
    return result


def main(argv=None):
    global CAT, KEYS, RESULT, TIMEOUT, MAX_TOKENS, SUB_INTERVAL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--billing", choices=["all", "subscription", "wallet"], default="all")
    parser.add_argument("--model", action="append", default=[], metavar="ID",
                        help="Probe only this model/billing route; repeat for multiple routes. Aliases use their default billing.")
    parser.add_argument("--execute", action="store_true", help="Send real requests; wallet routes incur charges")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=4096, help="Output budget per diagnostic request")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout per diagnostic request in seconds")
    args = parser.parse_args(argv)
    if args.workers < 1 or args.max_tokens < 1 or args.timeout < 1:
        parser.error("workers, max-tokens and timeout must be positive")
    path = ROOT / ".local/catalog.json"
    if not path.exists():
        parser.error("No catalog. Run: python scripts/nd.py models update")
    CAT = catalog.load(ROOT)
    try:
        models = selected_models(CAT, args.billing, args.model)
    except ValueError as error:
        parser.error(str(error))
    counts = {mode: sum(m["billing"] == mode for m in models) for mode in ("subscription", "wallet")}
    planned = sum(3 + bool(m.get("capabilities", {}).get("vision")) + len(m.get("efforts", [])) for m in models)
    print(json.dumps({"mode": "EXECUTE" if args.execute else "DRY_RUN", "billing": args.billing,
        "routes": len(models), "route_counts": counts, "planned_requests_up_to": planned,
        "wallet_is_billable": bool(counts["wallet"]), "max_tokens_per_request": args.max_tokens,
        "selected_models": [model["id"] for model in models],
        "catalog_refreshed_at": CAT["refreshed_at"]}, ensure_ascii=False), flush=True)
    if not args.execute:
        print("No requests sent. Use --execute to run this billable diagnostic.")
        return 0
    TIMEOUT, MAX_TOKENS = args.timeout, args.max_tokens
    rpm = CAT.get("limits", {}).get("subscription", {}).get("chat", {}).get("rpm", {}).get("limit")
    if rpm:
        SUB_INTERVAL = 60.0 / rpm
    KEYS = {mode: key_for(ROOT, mode) for mode in counts if counts[mode]}
    protocol.configure(ROOT)
    started = datetime.datetime.now(datetime.timezone.utc)
    history = ROOT / ".local/model-probes"
    history.mkdir(parents=True, exist_ok=True)
    # Archive any pre-existing latest receipt before replacing its convenience path.
    latest = ROOT / ".local/model-probes.json"
    old, old_path = None, None
    if latest.exists():
        old_raw = latest.read_bytes()
        old = json.loads(old_raw)
        if not isinstance(old, dict) or not isinstance(old.get("checks"), list) or any(
            not isinstance(row, dict) or not isinstance(row.get("model"), str)
            for row in old["checks"]
        ):
            raise ValueError("Previous model-probes receipt has an invalid checks array; preserve and repair it before probing")
        old_id = hashlib.sha256(old_raw).hexdigest()[:16]
        old_path = history / ("prior-" + old_id + ".json")
        try:
            descriptor = os.open(old_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if old_path.read_bytes() != old_raw:
                raise ValueError("Prior receipt hash path contains different bytes; refusing to replace evidence") from None
        else:
            with os.fdopen(descriptor, "wb") as archive:
                archive.write(old_raw)
    run_path = history / (started.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    RESULT = {"schema": 1, "started_at": started.isoformat(), "catalog_refreshed_at": CAT["refreshed_at"],
        "workers": args.workers, "network": "direct-no-proxy", "billing": args.billing,
        "receipt_kind": "run", "selected_models": [model["id"] for model in models],
        "max_tokens_per_request": MAX_TOKENS, "checks": [], "limitations": [
            "Short synthetic probes do not establish long-horizon coding quality, exact tokenizer/context limits or actual application of effort/thinking flags.",
            "Successful HTTP acceptance of experimental flags does not prove the upstream applies them."]}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(test, m): m["id"] for m in models}
        for future in as_completed(futures):
            try:
                out = future.result()
            except Exception as exc:
                out = {"model": futures[future], "fatal_error_type": type(exc).__name__, "checks": []}
            out = copy.deepcopy(out)
            out["checked_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            out["run_receipt"] = str(run_path)
            with WRITE_LOCK:
                RESULT["checks"].append(out)
                RESULT["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                atomic_json(run_path, RESULT, private=True)
                atomic_json(latest, aggregate_results(old, RESULT, run_path, old_path), private=True)
            stats = {r["kind"] + (":" + r["effort_requested"] if r["kind"] == "effort" else ""): r["status"] for r in out["checks"]}
            print(json.dumps({"completed": len(RESULT["checks"]), "total": len(models), "model": out["model"], "checks": stats}), flush=True)
    RESULT["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    atomic_json(run_path, RESULT, private=True)
    atomic_json(latest, aggregate_results(old, RESULT, run_path, old_path), private=True)
    print("Receipt: " + str(run_path))
    return 1 if any(not model["checks"] or model.get("fatal_error_type")
                    or any(check["status"] != "PASS" for check in model["checks"])
                    for model in RESULT["checks"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
