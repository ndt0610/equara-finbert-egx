"""Check pure frontend portfolio maths against backend, including comparison weights."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest
from backend.upgrades.coverage import HoldingScore, summarize_portfolio

def test_frontend_matches_backend_on_observed_and_missing_holdings():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for frontend arithmetic parity')
    source = (Path(__file__).parents[1] / 'frontend/app.js').read_text(encoding='utf-8')
    pure = source[source.index('function portfolioView('):source.index('function close(')]
    cases = [([50,30,20],[.6,-.2,.1]), ([50,30,20],[.6,-.2,None]),
             ([20,60,20],[.6,-.2,None]), ([1,99],[.4,None]),
             ([50,50],[.4,-.4]), ([50,50],[None,None]), ([0,100],[.4,None])]
    inputs=[]; expected=[]
    for weights,scores in cases:
        rows=[HoldingScore(str(i),w,None if v is None else {'n':1,'score':v,'label':'Neutral'})
              for i,(w,v) in enumerate(zip(weights,scores))]
        expected.append(summarize_portfolio(rows))
        inputs.append({'weights':weights,'holdings':[{'has_news':v is not None,'score':v,'n':int(v is not None)} for v in scores]})
    script=pure+'\nconst cases='+json.dumps(inputs)+'; console.log(JSON.stringify(cases.map(c=>portfolioView(c.holdings,c.weights))));'
    result=subprocess.run([node,'-e',script],capture_output=True,text=True,check=True,encoding='utf-8')
    actual=json.loads(result.stdout)
    for a,b in zip(actual,expected):
        assert a['score'] == pytest.approx(b['score']) if b['score'] is not None else a['score'] is None
        assert a['coverage'] == pytest.approx(b['coverage'])
        assert a['direction'] == b['direction']
        assert 'bound' not in a and 'bound' not in b


def test_same_batch_equal_and_changed_capital():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required')
    source = (Path(__file__).parents[1] / 'frontend/app.js').read_text(encoding='utf-8')
    pure = source[source.index('function portfolioView('):source.index('function close(')]
    script = pure + """
    const holdings = [{has_news:true, score:.6,n:2}, {has_news:true,score:-.2,n:15}];
    const before = JSON.stringify(holdings);
    const result = weights => [equalWeightView(holdings,weights).score, portfolioView(holdings,weights).score];
    console.log(JSON.stringify([result([50,50]),result([80,20]), before === JSON.stringify(holdings), result([100,0]), result([0,0])]));
    """
    result = subprocess.run([node,'-e',script],capture_output=True,text=True,check=True)
    a,b,unchanged,zero,empty=json.loads(result.stdout)
    assert a == pytest.approx([.2,.2])
    assert b == pytest.approx([.2,.44])
    assert unchanged
    assert zero == pytest.approx([.6,.6])
    assert empty == [None,None]
