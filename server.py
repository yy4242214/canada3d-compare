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
def start_background():
    with LOCK:
        if state.get('starting'):
            return False
        state['running']=True
        state['starting']=True
        persist()
    def job():
        try:
            update()
        finally:
            with LOCK:
                state['starting']=False
                persist()
    threading.Thread(target=job,daemon=True).start()
    return True

def worker():
    while True:
        time.sleep(30)
        with LOCK:active=state['running']
        if active:update()
threading.Thread(target=worker,daemon=True).start()
PAGE=r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>加拿大3D连续验证</title><style>
body{font:16px system-ui,sans-serif;max-width:700px;margin:auto;padding:18px;background:#f5f6f9;color:#17243a}button{font-size:17px;padding:14px;border:0;border-radius:8px;margin:5px;background:#1765c1;color:white;min-height:46px}.card{background:white;padding:16px;margin:12px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:10px 5px;text-align:center;border-bottom:1px solid #e5e8ed}th{background:#edf2f8}.good{color:#16713a;font-weight:700}.bad{color:#ae2b2b;font-weight:700}.muted{color:#667085;font-size:13px}.tablewrap{overflow-x:auto}
</style></head><body><h2>加拿大3D｜A/B连续验证</h2><p>点击开始后，服务运行期间每30秒检查开奖；只有点击停止才主动暂停。网页关闭或切到后台不会主动停止验证，但免费服务器休眠、重启或断网可能造成漏期。</p><button type="button" id="start">开始连续验证</button><button type="button" id="stop">停止验证</button><p id="msg">正在连接服务器…</p><div class="card" id="summary"></div><div class="card"><b>A组：历史最低50期</b><pre id="low"></pre></div><div class="card"><b>B组：历史最高15期</b><pre id="high"></pre></div><div class="card"><h3>最近15期真实验证记录</h3><p class="muted">只列出开奖前已保存预测的期号。未预测或尚未开奖不计入覆盖率；空白表示该组无提前预测。</p><div class="tablewrap"><table><thead><tr><th>期号</th><th>A组是否覆盖</th><th>B组是否覆盖</th></tr></thead><tbody id="recent"><tr><td colspan="3">读取中…</td></tr></tbody></table></div></div>
<script>
const $=id=>document.getElementById(id);
let busy=false;
async function cmd(s){if(busy)return;busy=true;try{let r=await fetch('/api/'+s,{method:'POST',cache:'no-store'});let j=await r.json();if(!r.ok)throw Error(j.error||'HTTP '+r.status);$('msg').textContent=j.message||'操作完成';await refresh(false)}catch(e){$('msg').textContent='操作失败：'+e.message}finally{busy=false}}
function outcome(x){if(!x)return '<span class="muted">未预测</span>';if(x.actual===null)return '<span class="muted">待开奖</span>';return x.covered===true?'<span class="good">覆盖</span>':'<span class="bad">未覆盖</span>'}
async function refresh(showMessage=true){try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);let j=await r.json();if(showMessage)$('msg').textContent='状态读取成功（'+new Date().toLocaleTimeString()+'）';$('summary').textContent='状态：'+(j.running?'连续验证中':'已停止')+'；检查次数：'+(j.checks||0)+'；最近检查：'+(j.last_run||'无')+'；错误：'+(j.last_error||'无');for(let k of ['low','high']){let x=j[k]||{},s=x.stats||{},pending=(x.records||[]).find(r=>r.actual===null);$(k).textContent='已核对 '+(s.settled||0)+' 期；覆盖 '+(s.hits||0)+' 期；覆盖率 '+(s.rate??'—')+'%\n最新开奖：'+(x.last_fetch?.issue||'无')+' / '+(x.last_fetch?.num||'')+'\n待验证期号：'+(pending?.issue||'无')+'\n排除百/十/个：'+(pending?['百位','十位','个位'].map(p=>pending.excluded[p].join(',')).join(' / '):'无')+'\n已保存记录数：'+(x.records||[]).length}
let low=new Map((j.low?.records||[]).map(x=>[String(x.issue),x]));let high=new Map((j.high?.records||[]).map(x=>[String(x.issue),x]));let issues=[...new Set([...low.keys(),...high.keys()])].sort((a,b)=>Number(b)-Number(a));let done=issues.filter(i=>low.get(i)?.actual!==null&&low.get(i)?.actual!==undefined||high.get(i)?.actual!==null&&high.get(i)?.actual!==undefined).slice(0,15);let body=$('recent');body.replaceChildren();if(!done.length){let tr=body.insertRow();let td=tr.insertCell();td.colSpan=3;td.textContent='暂无已开奖的前瞻记录'}else for(let i of done){let tr=body.insertRow();tr.insertCell().textContent=i;for(let map of [low,high]){let td=tr.insertCell();let rec=map.get(i);td.textContent=!rec?'未预测':rec.actual===null?'待开奖':rec.covered===true?'覆盖':'未覆盖';td.className=rec?.actual!==null&&rec?.actual!==undefined?(rec.covered===true?'good':'bad'):'muted'}}
}catch(e){$('msg').textContent='网络异常：'+e.message}}
$('start').addEventListener('click',()=>cmd('start'));$('stop').addEventListener('click',()=>cmd('stop'));refresh();setInterval(()=>refresh(),20000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
</script></body></html>"""
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
        if path=='/api/start':
            started=start_background()
            return self.send(200,json.dumps({'message':'已开启连续验证，首次抓取正在后台执行' if started else '连续验证已在启动中'},ensure_ascii=False))
        with LOCK:
            state['running']=False
            persist()
        return self.send(200,'{"message":"已停止连续验证"}')
if __name__=='__main__':
    port=int(os.environ.get('PORT','10000'))
    print('连续验证服务启动，端口',port,flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
