"""Verify presentation numbers and declarative label table against executable code."""
import json,math,itertools,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from backend.upgrades.coverage import HoldingScore,summarize_portfolio
from backend.upgrades.tin_gia.rules import classify,quantile
def close(a,b):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10),(a,b)
h=[HoldingScore(k,w,{'n':1,'score':s,'label':'Neutral'}) for k,w,s in [('A',50,.6),('B',30,-.2),('C',20,.1)]]
close(summarize_portfolio(h)['score'],.26)
weights=[2**(-a/7) for a in [7,14]];ss=sum(w*s for w,s in zip(weights,[.8,-.2]))/sum(weights);f=sum(weights)/2
close(ss,7/15);close(f,.375);close(ss*f,.175)
count=0
for d,r,b,n in itertools.product([-.8,-.600001,-.6,-.599999,-.200001,-.2,-.199999,0,.199999,.2,.200001,.599999,.6,.600001,.8],[-.11,-.050001,-.05,-.049999,0,.049999,.05,.050001,.11],[.05],[1,2.99999,3,4]):
    strongbuy=d>=.6 and 0<r<=b and n>=3
    strongsell=d<=-.6 and r<-b and n>=3
    buy=d>=.2 and -b<=r<=b and not strongbuy
    sell=d<=-.2 and r<-b and not strongsell
    hold=(-.2<d<.2) or (d>=.2 and (r>b or r<-b)) or (d<=-.2 and r>=-b)
    labels=[l for l,v in zip(['buy_strong','sell_strong','buy','sell','hold'],[strongbuy,strongsell,buy,sell,hold]) if v]
    assert len(labels)==1,(d,r,b,n,labels)
    assert classify(d,r,b,.1,n)[0]==labels[0],(d,r,b,n)
    count+=1
live=json.loads((root/'artifacts/observed_scope_live_check.json').read_text(encoding='utf-8'))
close(sum(h['contribution'] for h in live['holdings']),live['portfolio']['score'])
for h,w in zip(live['holdings'],[.5,.3,.2]):close(h['score']*w,h['contribution'])
tg=json.loads((root/'artifacts/rules_v2_live_check.json').read_text(encoding='utf-8'))['inputs']
close(tg['raw_sentiment']*tg['freshness'],tg['sentiment'])
assert classify(tg['sentiment'],tg['five_session_return'],tg['normal_move'],tg['extreme_move'],tg['effective_groups'])[0]=='hold'
assert tg['normal_move']<abs(tg['five_session_return'])<tg['extreme_move']
report={'portfolio_example':.26,'news_example':{'S':ss,'F':f,'D':ss*f},'label_boundary_combinations':count,'live_portfolio_sum':live['portfolio']['score'],'ETEL_D':tg['sentiment'],'ETEL_label':'Giữ','limits':'Archived aggregate records checked for arithmetic; news/model outputs and historical B/E not independently recomputed from raw archive in this audit.'}
(root/'artifacts/slide_formula_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
