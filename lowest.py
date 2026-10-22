#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, itertools, urllib.request, threading, time
from urllib.parse import urlsplit
from collections import Counter
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'8793_验证记录.json'
POS=('百位','十位','个位')
LOCK=threading.RLock()
ACTION_LOCK=threading.Lock()
POLL_SECONDS=30

def load():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding='utf-8'))
        except Exception as e: raise RuntimeError('状态文件读取失败，为避免覆盖记录已停止：'+str(e))
    return {'selection':None,'selection_history':[],'records':{},'last_fetch':None,'running':False,'last_error':None,'last_check':None}
S=load()
def save():
    tmp=STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(S,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(STATE)

def fetch():
    url='https://pc28.world/api/v1/draws?limit=100'
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://pc28.world/'})
    with urllib.request.urlopen(req,timeout=20) as resp: j=json.load(resp)
    if not j.get('ok'): raise RuntimeError('开奖接口未返回成功标记')
    raw=j.get('data',{}).get('items',[])
    rows={}
    for x in raw:
        try:
            issue=int(x['nbr']); ns=[int(x[k]) for k in ('n1','n2','n3')]
            if all(0<=v<=9 for v in ns): rows[issue]={'issue':str(issue),'num':''.join(map(str,ns))}
        except (ValueError,TypeError,KeyError): continue
    result=[rows[k] for k in sorted(rows)]
    if len(result)<65: raise RuntimeError('有效历史开奖不足65期，实际'+str(len(result)))
    return result

def formulas(history,next_issue):
    a,b,c=map(int,history[-1]['num']); span=max(a,b,c)-min(a,b,c); total=a+b+c
    def hotcold(pos):
        cnt=Counter(int(x['num'][pos]) for x in history[-15:])
        return max(range(10),key=lambda n:(cnt[n],-n)),min(range(10),key=lambda n:(cnt[n],n))
    h0,c0=hotcold(0); h1,c1=hotcold(1); h2,c2=hotcold(2)
    hundred={'百位×3＋3':(a*3+3)%10,'百位×7＋7':(a*7+7)%10,'跨度＋百位':(span+a)%10,'上期个位':c,'上期十位':b,'百位＋十位':(a+b)%10,'百位－十位':(a-b)%10,'15期热号':h0,'15期冷号':c0}
    tens={'十位×6＋6':(b*6+6)%10,'和值＋跨度':(total+span)%10,'十位对码':(b+5)%10,'上期跨度':span,'15期热号':h1,'15期冷号':c1}
    units={'和尾＋4':(total+4)%10,'上期跨度':span,'上期十位':b,'个位平方':(c*c)%10,'个位＋7':(c+7)%10,'个位对码':(c+5)%10,'15期热号':h2,'15期冷号':c2}
    if len(history)>=2: units['前两期个位相加']=(int(history[-2]['num'][2])+c)%10
    if str(next_issue).isdigit():
        n=int(next_issue); hundred['期号尾－百位']=(n-a)%10; tens['期号尾＋4']=(n+4)%10
        tens['期号末两位相加']=(n//10+n%10)%10; units['期号数字和尾']=sum(map(int,str(n)))%10
    return {'百位':hundred,'十位':tens,'个位':units}

def unique_exclusions(fmap, selected, history):
    """优先三种选定方法；撞号时依次尝试其他未选方法，直到有3个不同数字。"""
    used=[]; source=[]
    for name in list(selected)+[n for n in fmap if n not in selected]:
        digit=fmap[name]
        if digit not in used:
            used.append(digit);source.append(name)
            if len(used)==3:return used,source
    # 极端情况下所有现有公式只能产生不足3个不同数字：启用确定性备用公式。
    a,b,c=map(int,history[-1]['num'])
    for k in range(10):
        digit=(a+3*b+7*c+k)%10
        if digit not in used:
            used.append(digit);source.append('备用位置变换'+str(k))
            if len(used)==3:return used,source
    raise RuntimeError('无法生成3个不同排除数字')

def backtest(rows):
    rows=rows[-65:]
    train=[(rows[:i],rows[i]['num'],formulas(rows[:i],rows[i]['issue'])) for i in range(15,65)]
    opts=[]
    for pidx,pos in enumerate(POS):
        names=list(train[0][2][pos]); group=[]
        for triple in itertools.combinations(names,3):
            mask=0
            for i,(history,actual,pred) in enumerate(train):
                excluded,_=unique_exclusions(pred[pos],triple,history)
                if int(actual[pidx]) not in excluded:mask|=1<<i
            group.append((triple,mask))
        opts.append(group)
    count=len(opts[0])*len(opts[1])*len(opts[2])
    best=None
    for a in opts[0]:
        for b in opts[1]:
            ab=a[1]&b[1]
            for c in opts[2]:
                hits=(ab&c[1]).bit_count()
                names=(a[0],b[0],c[0]);key=(hits,tuple(z for triple in names for z in triple))
                if best is None or key<best[0]:best=(key,names)
    return {'pairs':{p:list(best[1][i]) for i,p in enumerate(POS)},'hits':best[0][0],
            'total':50,'combos':count,'range':[rows[15]['issue'],rows[-1]['issue']],
            'selected_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

def predict(rows,sel):
    issue=str(int(rows[-1]['issue'])+1)
    f=formulas(rows,issue);excluded={};allowed={};sources={}
    for pos in POS:
        nums,used=unique_exclusions(f[pos],sel['pairs'][pos],rows)
        excluded[pos]=nums;sources[pos]=used
        allowed[pos]=[i for i in range(10) if i not in nums]
    return {'issue':issue,'based_on':rows[-1]['issue'],'selection_at':sel['selected_at'],
            'pairs':sel['pairs'],'excluded':excluded,'sources':sources,'allowed':allowed,
            'tickets':343,'created_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'actual':None,'covered':None}

def stats():
    records=S['records']; settled=sorted((v for v in records.values() if v.get('actual') is not None),key=lambda x:int(x['issue']))
    hit=sum(x['covered'] is True for x in settled); longest=run=0; last=None
    for x in settled:
        num=int(x['issue'])
        if last is not None and num!=last+1: run=0
        run=0 if x['covered'] else run+1
        longest=max(longest,run); last=num
    return {'settled':len(settled),'hits':hit,'rate':round(100*hit/len(settled),2) if settled else None,
            'longest_miss':longest,'current_miss':run,'pending':sum(v.get('actual') is None for v in records.values())}

def action(mode):
    with ACTION_LOCK:
        return _action(mode)

def _action(mode):
    rows=fetch(); latest=rows[-1]; drawn={r['issue']:r['num'] for r in rows}
    with LOCK:
        # 核对先前真正保存的预测；不补造历史预测
        settled_new=0
        for issue,rec in S['records'].items():
            if rec['actual'] is None and issue in drawn:
                rec['actual']=drawn[issue]
                rec['covered']=all(int(drawn[issue][i]) in rec['allowed'][pos] for i,pos in enumerate(POS))
                settled_new+=1
        if mode=='retest' or S['selection'] is None:
            selected=backtest(rows)
            S['selection']=selected
            S['selection_history'].append(selected)
        next_issue=str(int(latest['issue'])+1)
        if next_issue not in S['records']:
            S['records'][next_issue]=predict(rows,S['selection'])
        # 已有预测不能改写，重新回测选出的新公式从下一个未生成预测的期号开始生效
        S['last_fetch']={'issue':latest['issue'],'num':latest['num'],'at':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        S['last_check']=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        S['last_error']=None
        save()
        return {'message':f'成功：本次核对{settled_new}期；当前最新{latest["issue"]}期；待验证{next_issue}期。'+(' 重新回测已完成，已有待验证预测保持原样。' if mode=='retest' else '')}

def snapshot():
    with LOCK:
        recs=sorted(S['records'].values(),key=lambda x:int(x['issue']),reverse=True)
        return {'selection':S['selection'],'history':S['selection_history'][-10:],
                'records':recs[:200],'last_fetch':S['last_fetch'],'stats':stats(),
                'running':S.get('running',False),'last_error':S.get('last_error'),
                'last_check':S.get('last_check'),'poll_seconds':POLL_SECONDS}

HTML='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>加拿大3D 三方法最高覆盖对照验证</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f6fa;color:#172438;max-width:980px;margin:auto;padding:14px}h1{font-size:22px}button{padding:13px 20px;border:0;border-radius:9px;color:white;background:#1767c5;font-size:16px;margin:4px;cursor:pointer}button:nth-child(2){background:#b65b1b}.box{background:white;border-radius:12px;padding:14px;margin:12px 0;box-shadow:0 1px 7px #d8deeb}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid #e5eaf0;text-align:left}th{background:#edf2f8}.scroll{overflow-x:auto}.muted{color:#627187;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.good{color:green}.bad{color:#b52d2d}</style></head><body>
<h1>加拿大3D｜三方法最高覆盖对照验证</h1><p class="muted">点击开始验证后，后台每30秒自动检查新开奖、核对并生成下一期预测；使用前15期预热、最近15期回测；只有点击重新回测才重新选择公式。关闭网页不影响运行，但 Termux 进程必须保持运行。历史最高覆盖率不代表未来优势。</p>
<button onclick="run('start')">开始验证</button><button onclick="run('retest')">重新回测</button><button onclick="run('stop')">暂停自动验证</button><p id="msg">读取中……</p>
<div class="box"><h3>最新开奖与真实前瞻统计</h3><div id="summary"></div></div>
<div class="box"><h3>当前选定九种公式（最近15期回测最高）</h3><div id="selection"></div></div>
<div class="box"><h3>下一期已保存预测</h3><div id="pending"></div></div>
<div class="box"><h3>历史验证记录</h3><div class="scroll"><table><thead><tr><th>期号</th><th>排除百/十/个</th><th>注数</th><th>开奖号码</th><th>覆盖</th><th>预测创建时间</th></tr></thead><tbody id="records"></tbody></table></div></div>
<div class="box"><h3>最近重新回测记录</h3><div id="history"></div></div>
<script>
const $=id=>document.getElementById(id); const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function posPairs(x){return ['百位','十位','个位'].map(p=>`${p}：${(x[p]||[]).map(esc).join(' ＋ ')}`).join('<br>')}
function excl(x){return ['百位','十位','个位'].map(p=>(x[p]||[]).join('、')).join(' / ')}
async function refresh(){try{let r=await fetch('/api/status');let j=await r.json();let s=j.stats,latest=j.last_fetch;
$('summary').innerHTML=`自动验证：<b>${j.running?'运行中（每'+j.poll_seconds+'秒检查）':'未启动/已暂停'}</b>；上次检查：${esc(j.last_check||'—')}<br>${j.last_error?'最近错误：'+esc(j.last_error)+'<br>':''}最近抓取：${latest?esc(latest.issue+'期，开奖号码'+latest.num+'（'+latest.at+'）'):'尚未抓取'}<br>已核对：${s.settled}期；覆盖：${s.hits}期；覆盖率：${s.rate===null?'—':s.rate+'%'}；最长连续未覆盖：${s.longest_miss}期；当前连续未覆盖：${s.current_miss}期；待核对：${s.pending}期`;
let a=j.selection;$('selection').innerHTML=a?`${posPairs(a.pairs)}<br>历史回测：${a.hits}/${a.total}（${(a.hits/a.total*100).toFixed(2)}%），组合数：${a.combos}，回测期号：${a.range.join('～')}<br>选定时间：${esc(a.selected_at)}`:'尚未选择，点击“开始验证”';
let pending=j.records.find(x=>x.actual===null);$('pending').innerHTML=pending?`期号：<b>${pending.issue}</b><br>固定方法：<br>${posPairs(pending.pairs)}<br>实际使用（含撞号补位）：<br>${posPairs(pending.sources||pending.pairs)}<br>排除号码（百/十/个）：<b>${excl(pending.excluded)}</b><br>可用号码：${['百位','十位','个位'].map(p=>p+': '+pending.allowed[p].join('')).join('<br>')}<br>直选注数：<b>${pending.tickets}</b><br>预测时间：${esc(pending.created_at)}`:'暂无待验证预测';
$('records').innerHTML=j.records.map(x=>`<tr><td>${esc(x.issue)}</td><td>${excl(x.excluded)}</td><td>${x.tickets}</td><td>${x.actual??'待开奖'}</td><td class="${x.covered===true?'good':'bad'}">${x.covered===null?'待验证':x.covered?'覆盖':'未覆盖'}</td><td>${esc(x.created_at)}</td></tr>`).join('');
$('history').innerHTML=j.history.slice().reverse().map(x=>`<p>${esc(x.selected_at)}：${x.hits}/${x.total}；${posPairs(x.pairs)}</p>`).join('')||'暂无';
}catch(e){$('msg').textContent='读取失败：'+e}}
async function run(mode){$('msg').textContent='正在抓取并计算，请稍候……';document.querySelectorAll('button').forEach(x=>x.disabled=true);try{let r=await fetch('/api/'+mode,{method:'POST'}),j=await r.json();$('msg').textContent=j.error?'失败：'+j.error:j.message;await refresh()}catch(e){$('msg').textContent='请求失败：'+e}finally{document.querySelectorAll('button').forEach(x=>x.disabled=false)}}refresh();setInterval(refresh,10000);
</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def send(self,status,data,typ='application/json; charset=utf-8'):
        b=data.encode('utf-8');self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if urlsplit(self.path).path=='/': self.send(200,HTML,'text/html; charset=utf-8')
        elif urlsplit(self.path).path=='/api/status': self.send(200,json.dumps(snapshot(),ensure_ascii=False))
        else:self.send(404,'{"error":"not found"}')
    def do_POST(self):
        if urlsplit(self.path).path not in ('/api/start','/api/retest','/api/stop'):return self.send(404,'{"error":"not found"}')
        try:
            mode=urlsplit(self.path).path.rsplit('/',1)[-1]
            if mode=='stop':
                with LOCK:
                    S['running']=False
                    save()
                result={'message':'已暂停自动验证。'}
            else:
                result=action('retest' if mode=='retest' else 'start')
                if mode=='start':
                    with LOCK:
                        S['running']=True
                        save()
            self.send(200,json.dumps(result,ensure_ascii=False))
        except Exception as e:self.send(500,json.dumps({'error':str(e)},ensure_ascii=False))
def auto_worker():
    while True:
        time.sleep(POLL_SECONDS)
        with LOCK:
            running=S.get('running',False)
        if not running:
            continue
        try:
            action('start')
        except Exception as e:
            with LOCK:
                S['last_error']=str(e)
                S['last_check']=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                save()
            print('自动验证检查失败：',repr(e),flush=True)

if __name__=='__main__':
    threading.Thread(target=auto_worker,daemon=True).start()
    print('加拿大3D独立验证服务启动：http://127.0.0.1:8793',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8793),Handler).serve_forever()
