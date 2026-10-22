#!/usr/bin/env python3
# 连续验证会话服务：网页打开时每20秒保活，服务每30秒抓取开奖。
# 注意：免费实例休眠/重启时会停止；本地状态可能丢失。此服务不修改GitHub Pages历史。
import os,json,time,threading,importlib,traceback
from pathlib import Path
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'live_data';DATA.mkdir(exist_ok=True)
LOCK=threading.RLock()
modules={}
for key,name in [('low','lowest'),('high','highest')]:
    m=importlib.import_module(name)
    m.STATE=DATA/(key+'.json')
    m.S=m.load()
    modules[key]=m
control=DATA/'control.json'
try:state=json.loads(control.read_text())
except Exception:state={}
# 进程重启后不自动继续：需要用户重新点开始
state.update({'running':False,'last_run':None,'last_error':None,'checks':0})
def persist():
    tmp=control.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False));tmp.replace(control)
def update():
    results={}
    for key,m in modules.items():
        try:results[key]=m.action('start')['message']
        except Exception as e:results[key]='错误：'+str(e)
    with LOCK:
        state['last_run']=datetime.now(timezone.utc).isoformat()
        state['last_error']='；'.join(v for v in results.values() if v.startswith('错误：')) or None
        state['checks']+=1;state['results']=results;persist()
    return results
def worker():
    while True:
        time.sleep(30)
        with LOCK:active=state['running']
        if active:update()
threading.Thread(target=worker,daemon=True).start()
PAGE="""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>加拿大3D连续验证</title><style>body{font:16px system-ui;max-width:700px;margin:auto;padding:18px;background:#f5f6f9;color:#17243a}button{font-size:17px;padding:14px;border:0;border-radius:8px;margin:5px;background:#1765c1;color:white}.card{background:white;padding:16px;margin:12px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}</style><h2>加拿大3D｜A/B连续验证</h2><p>网页打开期间自动保活，每30秒检查一次开奖。免费服务器休眠或重启时会中断，不保证零漏期。</p><button onclick="cmd('start')">开始连续验证</button><button onclick="cmd('stop')">停止验证</button><p id="msg">读取中…</p><div class="card" id="summary"></div><div class="card"><b>A组：历史最低50期</b><pre id="low"></pre></div><div class="card"><b>B组：历史最高15期</b><pre id="high"></pre></div><script>const $=id=>document.getElementById(id);async function cmd(s){try{let r=await fetch('/api/'+s,{method:'POST'});let j=await r.json();$('msg').textContent=j.message||j.error;await refresh()}catch(e){$('msg').textContent=e}}async function refresh(){try{let r=await fetch('/api/status',{cache:'no-store'}),j=await r.json();$('summary').textContent='状态：'+(j.running?'连续验证中':'已停止')+'；检查次数：'+j.checks+'；最近检查：'+(j.last_run||'无')+'；错误：'+(j.last_error||'无');for(let k of ['low','high']){let x=j[k]||{},s=x.stats||{},pending=(x.records||[]).find(r=>r.actual===null);$(k).textContent='已核对 '+(s.settled||0)+' 期；覆盖 '+(s.hits||0)+' 期；覆盖率 '+(s.rate??'—')+'%\n最新开奖：'+(x.last_fetch?.issue||'无')+' / '+(x.last_fetch?.num||'')+'\n待验证期号：'+(pending?.issue||'无')+'\n排除百/十/个：'+(pending?['百位','十位','个位'].map(p=>pending.excluded[p].join(',')).join(' / '):'无')+'\n已保存记录数：'+(x.records||[]).length}}catch(e){$('msg').textContent='网络异常：'+e}}refresh();setInterval(refresh,20000);</script></html>"""
class Handler(BaseHTTPRequestHandler):
    def send(self,status,body,ctype='application/json; charset=utf-8'):
        raw=body.encode();self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/':return self.send(200,PAGE,'text/html; charset=utf-8')
        if path=='/health':return self.send(200,json.dumps({'ok':True,'running':state['running']},ensure_ascii=False))
        if path=='/api/status':
            with LOCK:res=dict(state)
            for key,m in modules.items():
                try:res[key]=m.snapshot()
                except Exception as e:res[key]={'error':str(e)}
            return self.send(200,json.dumps(res,ensure_ascii=False))
        self.send(404,'{"error":"not found"}')
    def do_POST(self):
        path=urlsplit(self.path).path
        if path not in ('/api/start','/api/stop'):return self.send(404,'{"error":"not found"}')
        with LOCK:state['running']=(path=='/api/start');persist()
        if state['running']:
            results=update()
            return self.send(200,json.dumps({'message':'已开启连续验证','results':results},ensure_ascii=False))
        return self.send(200,'{"message":"已停止连续验证"}')
if __name__=='__main__':
    port=int(os.environ.get('PORT','10000'))
    print('连续验证服务启动，端口',port,flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
