"""严格按85期真实覆盖次数升序选择；不使用综合评分替代排名。"""
import itertools,threading
from datetime import datetime
CACHE_LOCK=threading.Lock()
_CACHE={}

def choose(rows,formulas,unique_exclusions,positions):
    rows=rows[-100:]
    if len(rows)<100:
        raise RuntimeError('需要100期有效开奖（15期预热＋85期检验），实际'+str(len(rows)))
    fingerprint=tuple((x['issue'],x['num']) for x in rows)
    with CACHE_LOCK:
        if fingerprint in _CACHE:return _CACHE[fingerprint]
        train=[(rows[:i],rows[i]['num'],formulas(rows[:i],rows[i]['issue'])) for i in range(15,100)]
        groups=[]
        for idx,pos in enumerate(positions):
            opts=[]
            for triple in itertools.combinations(train[0][2][pos],3):
                mask=0
                for i,(history,actual,pred) in enumerate(train):
                    excluded,_=unique_exclusions(pred[pos],triple,history)
                    if int(actual[idx]) not in excluded:mask|=1<<i
                opts.append((triple,mask))
            groups.append(opts)
        recent_mask=((1<<35)-1)<<50
        older_mask=(1<<25)-1
        middle_mask=((1<<25)-1)<<25
        candidates=[]
        for aa in groups[0]:
            for bb in groups[1]:
                partial=aa[1]&bb[1]
                for cc in groups[2]:
                    mask=partial&cc[1]
                    names=(aa[0],bb[0],cc[0])
                    hits=mask.bit_count()
                    recent=(mask&recent_mask).bit_count()
                    middle=(mask&middle_mask).bit_count()
                    older=(mask&older_mask).bit_count()
                    candidates.append((hits,recent,middle,older,names,mask))
        # 第一排序条件是85期真实覆盖次数，最近35期仅用于同分比较。
        candidates.sort(key=lambda x:(x[0],x[1],x[2],x[3],x[4]))
        a=candidates[0]
        # B也按实际覆盖次数最少选择，但要求至少两个位置的三种公式完全不重合。
        # 这比只要求组合名称不同更严格，防止两组几乎复制。
        def distinct(x,y):
            return sum(not(set(x[4][i])&set(y[4][i])) for i in range(3))>=2
        b=next((x for x in candidates[1:] if distinct(a,x)),None)
        if b is None:
            raise RuntimeError('找不到与A组至少两个位置公式不重合的B组')
        rank_b=candidates.index(b)+1
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        joint=(a[5]|b[5]).bit_count()
        def pack(x,role,rank):
            hits,recent,middle,older,names,mask=x
            return {'pairs':{p:list(names[i]) for i,p in enumerate(positions)},
                'hits':hits,'total':85,'combos':len(candidates),
                'range':[rows[15]['issue'],rows[-1]['issue']],
                'selected_at':now,'strategy':role,'rank':rank,
                'windows':{'recent35':recent,'middle25':middle,'older25':older},
                'total85':hits,'joint85':joint,'score':hits,
                'selection_rule':'85期覆盖次数升序；同分按最近35期、中间25期、较早25期排序'}
        result=(pack(a,'85期真实覆盖次数最低',1),pack(b,'85期低覆盖且至少两位置公式与A不重合',rank_b))
        _CACHE.clear();_CACHE[fingerprint]=result
        return result
