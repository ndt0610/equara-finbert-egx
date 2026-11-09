import json, shutil, subprocess
from pathlib import Path
import pytest

SOURCE=Path(__file__).parents[1]/'frontend/original-capital.js'
def node_run(tail):
    node=shutil.which('node')
    if not node: pytest.skip('Node required')
    p=subprocess.run([node,'-e',SOURCE.read_text(encoding='utf-8')+'\n'+tail],capture_output=True,text=True,check=True)
    return json.loads(p.stdout)

def test_original_equal_capital_with_macro_and_missing_stock():
    got=node_run("""
    const data={symbols:['COMI.EGX','ETEL.EGX'],headlines:[
      {kind:'micro',symbol:'COMI.EGX',probabilities:{positive:.8,negative:.1}},
      {kind:'micro',symbol:'COMI.EGX',probabilities:{positive:.4,negative:.1}},
      {kind:'macro',probabilities:{positive:.05,negative:.85}}]};
    const before=JSON.stringify(data);
    const a=capitalFromOriginal(data,[{symbol:'COMI',weight:50},{symbol:'ETEL',weight:50}]);
    const b=capitalFromOriginal(data,[{symbol:'COMI',weight:80},{symbol:'ETEL',weight:20}]);
    console.log(JSON.stringify({a,b,unchanged:before===JSON.stringify(data)}));
    """)
    assert got['a']['score']==pytest.approx((.7+.3-.8)/3)
    assert got['a']['score']==pytest.approx(got['a']['baseline'])
    assert got['b']['score']==pytest.approx((1.6*(.7+.3)-.8)/4.2)
    assert got['a']['groups'][1]['rows']==[]
    assert got['unchanged']
    for result in [got['a'],got['b']]:
        assert sum(r['contribution'] for r in result['rows'])==pytest.approx(result['score'])
        assert sum(r['share'] for r in result['rows'])==pytest.approx(1)

def test_five_equal_holdings_unequal_counts_and_no_macro():
    got=node_run("""
    const symbols=['A','B','C','D','E'].map(s=>s+'.EGX');
    const data={symbols,headlines:symbols.flatMap((s,i)=>Array.from({length:i+1},()=>({kind:'micro',symbol:s,probabilities:{positive:i/10,negative:.1}})))};
    console.log(JSON.stringify(capitalFromOriginal(data,symbols.map(symbol=>({symbol,weight:20})))));
    """)
    assert got['score']==pytest.approx(got['baseline'])
    assert all(r['multiplier']==1 for r in got['rows'])

def test_original_snapshot_reused_without_refetch_and_explicit_refresh():
    got=node_run("""
    let calls=0;
    async function submitAnalysis(url,body,button,render){calls++;render({symbols:['COMI.EGX','ETEL.EGX'],headlines:[],score:.1});}
    function renderError(e){throw Error(JSON.stringify(e));}
    (async()=>{
      let first,second;
      await useOriginalPortfolio(['COMI','ETEL'],{},d=>first=d);
      await useOriginalPortfolio(['ETEL.EGX','COMI'],{},d=>second=d);
      const reused=calls===1 && first===second;
      await useOriginalPortfolio(['COMI','ETEL'],{},()=>{},true);
      console.log(JSON.stringify({reused,calls}));
    })();
    """)
    assert got=={'reused':True,'calls':2}

def test_empty_scored_weight_and_invalid_weights():
    got=node_run("""
    const d={symbols:['A.EGX','B.EGX'],headlines:[{kind:'micro',symbol:'A.EGX',probabilities:{positive:.8,negative:.1}}]};
    const empty=capitalFromOriginal(d,[{symbol:'A',weight:0},{symbol:'B',weight:1}]);
    let rejected=0;
    for(const w of [[0,0],[-1,2],[Infinity,1]]) {try{capitalFromOriginal(d,[{symbol:'A',weight:w[0]},{symbol:'B',weight:w[1]}]);}catch(e){rejected++;}}
    console.log(JSON.stringify({score:empty.score,rejected}));
    """)
    assert got=={'score':None,'rejected':3}
