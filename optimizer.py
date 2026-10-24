"""Walk-forward multi-window selection; no future draw is used in a forecast."""
import itertools, threading
from datetime import datetime
CACHE_LOCK=threading.Lock()
_CACHE={}

def choose(rows, formulas, unique_exclusions, positions):
    # 15 draws warm-up + 85 non-overlapping validation draws.
    rows=rows[-100:]
    if len(rows)<100:
        raise RuntimeError('多窗口回测需要至少100期有效历史数据（15期预热＋85期检验），实际'+str(len(rows)))
    fingerprint=tuple((x['issue'],x['num']) for x in rows)
    with CACHE_LOCK:
        if fingerprint in _CACHE:return _CACHE[fingerprint]
        train=[(rows[:i], rows[i]['num'], formulas(rows[:i],rows[i]['issue'])) for i in range(15,100)]
        groups=[]
        for idx,pos in enumerate(positions):
            opts=[]
            for triple in itertools.combinations(train[0][2][pos],3):
                mask=0
                for i,(history,actual,pred) in enumerate(train):
                    ex,_=unique_exclusions(pred[pos],triple,history)
                    if int(actual[idx]) not in ex:mask|=1<<i
                opts.append((triple,mask))
            groups.append(opts)
        # newest 35 / previous 25 / previous 25. No window overlaps.
        w0=(1<<25)-1
        w1=((1<<25)-1)<<25
        w2=((1<<35)-1)<<50
        def metrics(mask):
            recent=(mask&w2).bit_count()
            middle=(mask&w1).bit_count()
            older=(mask&w0).bit_count()
            # Balanced low coverage across windows; penalize poor stability.
            rates=(recent/35,middle/25,older/25)
            score=(sum(rates)/3)+0.30*(max(rates)-min(rates))
            return score,recent,middle,older
        candidates=[]
        for a in groups[0]:
            for b in groups[1]:
                ab=a[1]&b[1]
                for c in groups[2]:
                    mask=ab&c[1]
                    names=(a[0],b[0],c[0])
                    score,recent,middle,older=metrics(mask)
                    candidates.append((score,recent,middle,older,names,mask))
        candidates.sort(key=lambda x:(x[0],x[1],x[2],x[3],x[4]))
        a=candidates[0]
        # Select B from low-coverage candidates, prioritizing low joint coverage.
        # Joint low-coverage means both groups are rarely covered; do not maximize complementarity.
        shortlist=candidates[1:1001]
        b=min(shortlist,key=lambda x:(
            (x[5]|a[5]).bit_count()/85 + 0.25*x[0],
            (x[5]|a[5]).bit_count(),x[0],x[4]))
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        def pack(entry,role):
            score,recent,middle,older,names,mask=entry
            return {'pairs':{p:list(names[i]) for i,p in enumerate(positions)},
                'hits':recent,'total':35,'combos':len(candidates),
                'range':[rows[-35]['issue'],rows[-1]['issue']],
                'selected_at':now,'strategy':role,'windows':{'recent35':recent,'previous25':middle,'older25':older},
                'total85':recent+middle+older,'score':round(score,5),
                'joint85':(a[5]|b[5]).bit_count()}
        result=(pack(a,'多窗口稳定低覆盖'),pack(b,'低覆盖候选中最小联合覆盖'))
        _CACHE.clear();_CACHE[fingerprint]=result
        return result
