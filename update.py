import importlib, json, os, sys
from pathlib import Path
from datetime import datetime, timezone
BASE=Path(__file__).resolve().parent
OUT=BASE/'docs'/'data'; OUT.mkdir(parents=True,exist_ok=True)
results={}
for key,module in [('low','lowest'),('high','highest')]:
    try:
        m=importlib.import_module(module)
        m.STATE=OUT/(key+'.json')
        m.S=m.load()
        result=m.action('start')
        data=m.snapshot()
        data['message']=result['message']
        results[key]={'ok':True,'message':result['message']}
    except Exception as e:
        results[key]={'ok':False,'error':str(e)}
        print(key,'更新失败:',repr(e),file=sys.stderr)
        try:
            data=m.snapshot()
            data['last_error']=str(e)
        except Exception:
            data={'last_error':str(e)}
    (OUT/(key+'_view.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'health.json').write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
if not any(v['ok'] for v in results.values()):sys.exit(1)
