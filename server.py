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
UPDATE_LOCK=threading.Lock()
RETEST_SECONDS=30*60
modules={}
for key,name in [('low','lowest'),('high','rank9')]:
    m=importlib.import_module(name)
    m.STATE=DATA/('rank9.json' if key=='high' else key+'.json')
    m.S=m.load()
    modules[key]=m
control=DATA/'control.json'
try:state=json.loads(control.read_text())
except Exception:state={}
# 进程重启后不自动继续：需要用户重新点开始
state.update({'running':False,'starting':False,'manual_busy':False,'last_run':None,'last_error':None,'checks':0})
state.setdefault('last_retest',None)
state.setdefault('next_retest',None)
def persist():
    tmp=control.with_suffix('.tmp');tmp.write_text(json.dumps(state,ensure_ascii=False));tmp.replace(control)
def update(force_retest=False):
    # 串行执行，防止手动启动和定时线程同时读写同一份验证记录。
    with UPDATE_LOCK:
        with LOCK:
            last=state.get('last_retest')
            try:
                due=force_retest or not last or time.time()-datetime.fromisoformat(last).timestamp()>=RETEST_SECONDS
            except (TypeError,ValueError,OverflowError):
                due=True
        results={}
        success_retests=0
        for key,m in modules.items():
            try:
                # 第一次仍按原算法初始化；以后每30分钟重新选择公式。
                mode='retest' if due and m.S.get('selection') is not None else 'start'
                results[key]=m.action(mode)['message']
                if due: success_retests+=1
            except Exception as e:
                results[key]='错误：'+str(e)
        now=datetime.now(timezone.utc)
        with LOCK:
            if due and success_retests==len(modules):
                state['last_retest']=now.isoformat()
                state['next_retest']=datetime.fromtimestamp(now.timestamp()+RETEST_SECONDS,timezone.utc).isoformat()
            state['last_run']=now.isoformat()
            state['last_error']='；'.join(v for v in results.values() if v.startswith('错误：')) or None
            state['checks']+=1
            state['results']=results
            persist()
        return results
def manual_retest():
    # 单独线程执行耗时回测；不改变自动验证的运行/暂停状态。
    with LOCK:
        if state.get('starting') or state.get('manual_busy'):
            return False
        state['manual_busy']=True
        persist()
    def job():
        try:
            update(force_retest=True)
        finally:
            with LOCK:
                state['manual_busy']=False
                persist()
    threading.Thread(target=job,daemon=True).start()
    return True

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
PAGE=r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>加拿大3D连续验证</title><style>body{font:16px system-ui;max-width:700px;margin:auto;padding:18px;background:#f5f6f9;color:#17243a}button{font-size:17px;padding:14px;border:0;border-radius:8px;margin:5px;background:#1765c1;color:white}.card{background:white;padding:16px;margin:12px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:10px 7px;text-align:center;border-bottom:1px solid #e5e8ee}th{background:#edf2fa}.ok{color:#16803c;font-weight:bold}.no{color:#b42318;font-weight:bold}.muted{color:#667085;font-size:13px}.detailtable{width:100%;min-width:0}.detailtable td{white-space:normal}.detailtable th{white-space:normal}.detailtable td:nth-child(3){text-align:left}.detailtable th:nth-child(3){text-align:left}.detailtable td{vertical-align:top}.groupdetail{display:block;padding:5px 0;white-space:nowrap}.groupdetail+.groupdetail{border-top:1px dashed #e5e8ee}.groupname{font-weight:700;display:inline-block;min-width:22px}.tablewrap{overflow-x:auto}.triple{display:inline-block}.sep{color:#98a2b3;margin:0 2px}#realstats{line-height:1.7}</style><h2>加拿大3D｜A/B连续验证</h2><p>网页打开期间自动保活，每30秒检查一次开奖；每30分钟重新回测并更新A/B公式。免费服务器休眠或重启时会中断，不保证零漏期。</p><button onclick="cmd('start')">开始连续验证</button><button onclick="cmd('stop')">停止验证</button><button id="retestbtn" onclick="cmd('retest')">手动更新A/B方法</button><p id="msg">正在连接服务器…</p><div class="card" id="summary"></div><div class="card"><b>A组：历史覆盖最低（50期）</b><pre id="low"></pre></div><div class="card"><b>B组：历史覆盖倒数第9低（50期）</b><pre id="high"></pre></div><div class="card"><h3>实际提前推荐核对记录</h3><p id="realstats">正在统计…</p><p class="muted">仅统计提前保存并已核对的预测；最近30期从新到旧排列；每期A组、B组上下两行完整显示，可上下滑动查看。✓ 表示开奖号码未被排除，× 表示被排除。每组百十个三位均为 ✓ 才算覆盖。</p><div class="tablewrap"><table class="detailtable"><thead><tr><th>期号</th><th>开奖号</th><th>A/B组百十个排除3码（上下排列）</th></tr></thead><tbody id="comparison"><tr><td colspan="3">正在读取…</td></tr></tbody></table></div></div><script>const $=id=>document.getElementById(id);async function cmd(s){try{let r=await fetch('/api/'+s,{method:'POST'});let j=await r.json();$('msg').textContent=j.message||j.error;await refresh()}catch(e){$('msg').textContent=e}}async function refresh(){try{let r=await fetch('/api/status',{cache:'no-store'}),j=await r.json();$('msg').textContent='状态读取成功（'+new Date().toLocaleTimeString()+'）';$('summary').textContent='状态：'+(j.running?'连续验证中':'已停止')+'；手动重算：'+(j.manual_busy?'正在计算':'空闲')+'；检查次数：'+j.checks+'；最近检查：'+(j.last_run||'无')+'；上次重算：'+(j.last_retest||'尚未')+'；下次重算：'+(j.next_retest||'待首次完成')+'；错误：'+(j.last_error||'无');$('retestbtn').disabled=!!j.manual_busy;for(let k of ['low','high']){let x=j[k]||{},s=x.stats||{},pending=(x.records||[]).find(r=>r.actual===null);$(k).textContent='已核对 '+(s.settled||0)+' 期；覆盖 '+(s.hits||0)+' 期；覆盖率 '+(s.rate??'—')+'%\n最新开奖：'+(x.last_fetch?.issue||'无')+' / '+(x.last_fetch?.num||'')+'\n待验证期号：'+(pending?.issue||'无')+'\n排除百/十/个：'+(pending?['百位','十位','个位'].map(p=>pending.excluded[p].join(',')).join(' / '):'无')+'\n已保存记录数：'+(x.records||[]).length}renderComparison(j);}catch(e){$('msg').textContent='网络异常：'+e}}function renderComparison(j){
const ar=(j.low?.records||[]),br=(j.high?.records||[]);
const a=new Map(ar.map(x=>[String(x.issue),x]));
const b=new Map(br.map(x=>[String(x.issue),x]));
const valid=r=>r&&r.actual!==null&&r.actual!==undefined;
const all=[...new Set([...a.keys(),...b.keys()])].filter(i=>valid(a.get(i))||valid(b.get(i))).sort((x,y)=>Number(y)-Number(x));
const issues=all.slice(0,30);
const count=(rows)=>{let done=rows.filter(valid);return [done.length,done.filter(x=>x.covered===true).length]};
const [an,ah]=count(ar),[bn,bh]=count(br);
$('realstats').textContent='真实已核对：A组 '+an+' 期，三位均安全 '+ah+' 期；B组 '+bn+' 期，三位均安全 '+bh+' 期。';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const digits=v=>String(v??'').replace(/[^0-9]/g,'').padStart(3,'0').slice(-3);
function detail(rec){
if(!rec)return '<span class="muted">未预测</span>';
if(!valid(rec))return '<span class="muted">待验证</span>';
const num=digits(rec.actual);
const keys=['百位','十位','个位'];
if(!rec.excluded||num.length!==3)return '<span class="muted">记录不完整</span>';
return keys.map((p,i)=>{
const ex=rec.excluded[p];if(!Array.isArray(ex))return '<span class="muted">无排除记录</span>';
const safe=!ex.map(Number).includes(Number(num[i]));
return '<span class="triple">'+esc(ex.join(''))+' <b class="'+(safe?'ok':'no')+'">'+(safe?'✓':'×')+'</b></span>';
}).join('<span class="sep"> / </span>');
}
$('comparison').innerHTML=issues.length?issues.map(issue=>{
const x=a.get(issue),y=b.get(issue),n=valid(x)?x.actual:y?.actual;
return '<tr><td>'+esc(issue)+'</td><td>'+esc(digits(n))+'</td><td><div class="groupdetail"><span class="groupname">A</span> '+detail(x)+'</div><div class="groupdetail"><span class="groupname">B</span> '+detail(y)+'</div></td></tr>';
}).join(''):'<tr><td colspan="3">暂无已核对的提前预测记录</td></tr>';
}
refresh();setInterval(refresh,20000);</script></html>"""
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
        if path not in ('/api/start','/api/stop','/api/retest'):return self.send(404,'{"error":"not found"}')
        if path=='/api/start':
            started=start_background()
            return self.send(200,json.dumps({'message':'已开启连续验证，首次抓取正在后台执行' if started else '连续验证已在启动中'},ensure_ascii=False))
        if path=='/api/retest':
            started=manual_retest()
            return self.send(200,json.dumps({'message':'已开始手动重新回测A/B两组，完成后自动显示新方法' if started else '已有计算任务进行中，请稍后再试'},ensure_ascii=False))
        with LOCK:
            state['running']=False
            persist()
        return self.send(200,'{"message":"已停止连续验证"}')
if __name__=='__main__':
    port=int(os.environ.get('PORT','10000'))
    print('连续验证服务启动，端口',port,flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
