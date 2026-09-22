"""Build results/viewer.html: click a stroke, read what Jev partitioned it into.

    python -m src.make_viewer

The page is one self-contained file (no CDN, no build step) so it still opens
next week with nothing running. It reads the same dumps analyze.py reads, so a
disagreement in the table can be traced to the exact element and question.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .serialize import CONDITIONS
from .svggeom import load_svg

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures"
RESULTS = ROOT / "results"

CHOICE_FAM = ("scene_layer", "nesting_layer", "role", "region", "group")
SCORE_FAM = ("extent", "structural_weight")
TRUTH_KEY = {"scene_layer": "layer", "nesting_layer": "nesting", "role": "role",
             "region": "region", "group": "object",
             "extent": "extent_bin", "structural_weight": "structure_bin"}


def strip_truth(svg_text: str) -> str:
    """Drop the answer key from the markup the browser will render."""
    return re.sub(r'\s+data-truth-[a-z]+="[^"]*"', '', svg_text)


def build() -> dict[str, Any]:
    data: dict[str, Any] = {"order": [], "fixtures": {}, "conditions": list(CONDITIONS)}
    for path in sorted((RESULTS / "raw").glob("*.json")):
        dump = json.loads(path.read_text(encoding="utf-8"))
        fx, cond = dump["fixture"], dump["condition"]
        slot = data["fixtures"].setdefault(fx, {
            "svg": "", "elements": [], "grid": {}, "rel": {}, "truth": {}})
        if not slot["svg"]:
            svg_text = (FIXTURE_DIR / f"{fx}.svg").read_text(encoding="utf-8")
            slot["svg"] = strip_truth(svg_text)
            d = load_svg(str(FIXTURE_DIR / f"{fx}.svg"))
            slot["elements"] = [{"id": e.eid, "cx": round(e.centroid[0], 1),
                                 "cy": round(e.centroid[1], 1),
                                 "bbox": [round(v, 1) for v in e.bbox]}
                                for e in d.elements]
            slot["truth"] = {k: {kk: v.get(kk) for kk in TRUTH_KEY.values()}
                             for k, v in dump["truth"].items()}
        ids = dump["id_map"]                       # state id -> fixture id
        grid: dict[str, Any] = slot["grid"].setdefault(cond, {})
        rel: dict[str, Any] = slot["rel"].setdefault(cond, {})
        for qid, ans in dump["answers"].items():
            fam, _, rest = qid.partition("::")
            if "|" in rest:
                a, _, b = rest.partition("|")
                rel.setdefault(fam, {})["%s|%s" % (ids.get(a, a), ids.get(b, b))] = {
                    "p": ans.get("noul"), "prob": ans.get("probabilities")}
                continue
            eid = ids.get(rest, rest)
            if fam in CHOICE_FAM:
                grid.setdefault(fam, {})[eid] = {"pred": ans.get("choice"),
                                                 "conf": ans.get("confidence"),
                                                 "probs": ans.get("probabilities")}
            elif fam in SCORE_FAM:
                probs = ans.get("probabilities") or {}
                top = max(probs, key=probs.get) if probs else None
                grid.setdefault(fam, {})[eid] = {"pred": top, "score": ans.get("score"),
                                                 "conf": ans.get("confidence"),
                                                 "probs": probs,
                                                 "legend": ans.get("legend")}
    data["order"] = sorted(data["fixtures"])
    return data


HTML = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>线条划分查看器 · Jev</title>
<style>
:root{--bg:#14161a;--fg:#e8eaf0;--mut:#9aa3b2;--line:#2a2f38;--hi:#ffd166}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:14px/1.5 "Segoe UI",system-ui,sans-serif;display:grid;
 grid-template-columns:minmax(0,1fr) 380px;grid-template-rows:auto 1fr;height:100vh;gap:0}
header{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:10px;align-items:center;
 padding:10px 14px;border-bottom:1px solid var(--line)}
header b{font-size:15px}
select,button{background:#1d2127;color:var(--fg);border:1px solid var(--line);
 border-radius:6px;padding:5px 9px;font:inherit}
main{overflow:auto;padding:14px}
aside{border-left:1px solid var(--line);overflow:auto;padding:14px;background:#171a1f}
svg{max-width:100%;height:auto;background:#f7f5ef;border-radius:8px}
svg [id]{transition:stroke .12s,fill .12s}
.dim{opacity:.18}
.pick{stroke:var(--hi)!important;stroke-width:3!important}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:14px 0 6px}
.row{display:grid;grid-template-columns:74px 1fr 40px;gap:8px;align-items:center;margin:3px 0}
.bar{height:9px;background:#22262e;border-radius:5px;overflow:hidden}
.bar i{display:block;height:100%;background:#5aa9ff}
table{border-collapse:collapse;width:100%;font-size:12.5px}
td,th{border-bottom:1px solid var(--line);padding:3px 5px;text-align:left}
th{color:var(--mut);font-weight:500}
.ok{color:#7ee081}.no{color:#ff8d8d}.soft{color:var(--mut)}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--mut);font-size:12px}
.sw{width:13px;height:13px;border-radius:3px;display:inline-block;vertical-align:-2px}
code{font-family:ui-monospace,Consolas,monospace;font-size:12px}
#tip{position:fixed;pointer-events:none;background:#0d0f12;border:1px solid var(--line);
 border-radius:6px;padding:6px 9px;font-size:12px;display:none;z-index:9;max-width:320px}
</style></head><body>
<header>
<b>Jev 线条划分查看器</b>
<select id="fx"></select>
<select id="fam"></select>
<select id="mode">
 <option value="conf">按置信度着色</option>
 <option value="agree">按五种文本化是否一致着色</option>
 <option value="correct">按对错着色（对照真值）</option>
</select>
<label class="soft"><input type="checkbox" id="onlylow"> 只看低置信(&lt;0.85)</label>
<span class="legend" id="legend"></span>
</header>
<main><div id="art"></div></main>
<aside id="side"></aside>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const CN = {features_named:'几何+命名',features_anon:'只有几何',named_nogeo:'只有命名',
 raw_paths:'原始路径串',scrambled:'几何错位(对照)'};
const FAMS = ['scene_layer','nesting_layer','role','region','group','extent','structural_weight'];
const FAMCN = {scene_layer:'场景层级',nesting_layer:'嵌套层级',role:'线条职责',region:'区域',
 group:'归属分组',extent:'跨度(graded)',structural_weight:'结构权重(graded)'};
let sel = {fx:DATA.order[0], fam:'scene_layer', mode:'conf'}, picked=null;

const $ = s=>document.querySelector(s);
function opts(el, items, label){ el.innerHTML = items.map(v=>`<option value="${v[0]}">${label?label(v[0]):v[1]}</option>`).join(''); }
opts($('#fx'), DATA.order.map(f=>[f,f]), f=>f+'（'+DATA.fixtures[f].elements.length+' 笔）');
opts($('#fam'), FAMS.map(f=>[f,f]), f=>FAMCN[f]);

function grad(t){ // 0 -> red, 1 -> blue-green
  const c1=[214,69,73], c2=[63,166,124];
  const m=c1.map((v,i)=>Math.round(v+(c2[i]-v)*t));
  return `rgb(${m.join(',')})`;
}
function cell(fx,cond,fam,eid){ return ((DATA.fixtures[fx].grid[cond]||{})[fam]||{})[eid]; }

function colorFor(eid){
  const cur=cell(sel.fx,c0(),sel.fam,eid);
  if(!cur) return null;
  if(sel.mode==='conf') return grad(Math.max(0,Math.min(1,(cur.conf??0.5))));
  if(sel.mode==='correct'){
    const t=truthFor(eid); if(t===null) return null;
    return String(cur.pred)===String(t) ? 'rgb(63,166,124)' : 'rgb(214,69,73)';
  }
  const preds = DATA.conditions.map(cd=>{const q=cell(sel.fx,cd,sel.fam,eid);return q?q.pred:null;})
                              .filter(v=>v!==null&&v!==undefined).map(String);
  const uniq = new Set(preds).size;
  return ['#3fa77c','#e8b93a','#d64549'][Math.min(2,uniq-1)];
}
const c0=()=>$('#cond')?$('#cond').value:DATA.conditions[0];

function truthFor(eid){
  const map={scene_layer:'layer',nesting_layer:'nesting',role:'role',region:'region',
   group:'object',extent:'extent_bin',structural_weight:'structure_bin'};
  const t=DATA.fixtures[sel.fx].truth[eid];
  return t? t[map[sel.fam]] : null;
}

function render(){
  const f=DATA.fixtures[sel.fx];
  $('#art').innerHTML=f.svg;
  const svg=$('#art svg'); if(!svg) return;
  svg.style.height='auto';
  svg.querySelectorAll('[id]').forEach(node=>{
    const eid=node.id, col=colorFor(eid);
    if(!col) return;                       // groups and unprobed strokes stay as drawn
    node.dataset.eid=eid;
    node.setAttribute('stroke',col);
    node.style.cursor='pointer';
    node.addEventListener('click',()=>{picked=eid;paint();sidebar();});
    node.addEventListener('mousemove',ev=>{
      const cur=cell(sel.fx,c0(),sel.fam,eid);
      const t=truthFor(eid);
      $('#tip').style.display='block';
      $('#tip').style.left=(ev.clientX+12)+'px';$('#tip').style.top=(ev.clientY+12)+'px';
      $('#tip').innerHTML=`<code>${eid}</code> · 真值 <b>${t??'-'}</b><br>答 <b>${cur.pred}</b> · 置信 ${((cur.conf??0)*100).toFixed(0)}%`;
    });
    node.addEventListener('mouseleave',()=>{$('#tip').style.display='none';});
  });
  paintLegend();
}
function paint(){
  const svg=$('#art svg'); if(!svg) return;
  const low=$('#onlylow').checked;
  svg.querySelectorAll('[id]').forEach(n=>{
    const cur=cell(sel.fx,c0(),sel.fam,n.dataset.eid);
    n.classList.toggle('dim', low && cur && (cur.conf??1)>=0.85);
    n.classList.toggle('pick', n.dataset.eid===picked);
  });
}
function paintLegend(){
  const el=$('#legend');
  if(sel.mode==='correct')
    el.innerHTML='<span><i class="sw" style="background:#3fa77c"></i>与真值一致</span>'
               + '<span><i class="sw" style="background:#d64549"></i>不一致</span>';
  else if(sel.mode==='agree')
    el.innerHTML='<span><i class="sw" style="background:#3fa77c"></i>五种文本化完全一致</span>'
               + '<span><i class="sw" style="background:#e8b93a"></i>部分不同</span>'
               + '<span><i class="sw" style="background:#d64549"></i>各不相同</span>';
  else
    el.innerHTML='<span><i class="sw" style="background:#d64549"></i>置信 0</span>'
               + '<span><i class="sw" style="background:#3fa77c"></i>置信 1</span>'
               + '<span class="soft">保持原色=该笔画在此维度没有判断题</span>';
}

function sidebar(){
  const eid=picked; const side=$('#side');
  if(!eid){ side.innerHTML='<h2>用法</h2><p class="soft">点一条笔画看它在五种文本化条件下的全部判断。蓝绿=置信高，红=置信低；「按对错着色」会直接对照几何内核的真值。</p>'+
    '<h2>全部元素</h2>'+tableFor(null); return; }
  const f=DATA.fixtures[sel.fx], tr=f.truth[eid]||{};
  let h=`<h2>${eid}</h2><p class="soft">真值：层 ${tr.layer??'-'} · 嵌套 ${tr.nesting??'-'} · 职责 ${tr.role??'-'} · 区域 ${tr.region??'-'} · 物体 ${tr.object??'-'}</p>`;
  h+=`<h2>当前维度 ${FAMCN[sel.fam]}</h2><table><tr><th>条件</th><th>答</th><th>置信</th><th>对</th></tr>`;
  for(const cd of DATA.conditions){
    const q=cell(sel.fx,cd,sel.fam,eid); if(!q) continue;
    const t=truthFor(eid), ok=String(q.pred)===String(t);
    h+=`<tr><td>${CN[cd]}</td><td><code>${q.pred}</code>${q.score!==undefined?' / '+q.score.toFixed(2):''}</td>`+
       `<td>${((q.conf??0)*100).toFixed(0)}%</td><td class="${ok?'ok':'no'}">${ok?'✓':'✗'}</td></tr>`;
  }
  h+='</table>';
  for(const cd of DATA.conditions){
    const q=cell(sel.fx,cd,sel.fam,eid); if(!q||!q.probs) continue;
    const items=Object.entries(q.probs).sort((a,b)=>b[1]-a[1]).slice(0,6);
    h+=`<h2>${CN[cd]} 的分布</h2>`+items.map(([k,v])=>
      `<div class="row"><code>${k}</code><span class="bar"><i style="width:${(v*100).toFixed(0)}%"></i></span><span>${v.toFixed(2)}</span></div>`).join('');
  }
  const rel=[];
  for(const cd of DATA.conditions){
    for(const [fam,pairs] of Object.entries((f.rel||{})[cd]||{})){
      for(const [k,v] of Object.entries(pairs||{})){
        const parts=k.split('|');
        if(parts[0]===eid||parts[1]===eid) rel.push({cd,fam,k,p:v.p,other:parts[0]===eid?parts[1]:parts[0]});
      }
    }
  }
  if(rel.length){
    h+='<h2>涉及这条笔画的关系（几何+命名）</h2><table><tr><th>关系</th><th>另一端</th><th>p(是)</th></tr>';
    rel.filter(r=>r.cd==='features_named').sort((a,b)=>(b.p||0)-(a.p||0)).slice(0,14).forEach(r=>{
      h+=`<tr><td>${r.fam.replace('rel_','')}</td><td><code>${r.other}</code></td><td class="${(r.p||0)>=0.5?'ok':'soft'}">${(r.p||0).toFixed(2)}</td></tr>`;});
    h+='</table>';
  }
  side.innerHTML=h;
}
function tableFor(){
  const f=DATA.fixtures[sel.fx];
  let h='<table><tr><th>笔画</th><th>答</th><th>置信</th><th>真值</th></tr>';
  for(const e of f.elements){
    const q=cell(sel.fx,c0(),sel.fam,e.id); if(!q) continue;
    const t=truthFor(e.id);
    h+=`<tr><td><code>${e.id}</code></td><td>${q.pred}</td><td>${((q.conf??0)*100).toFixed(0)}%</td><td class="${String(q.pred)===String(t)?'ok':'no'}">${t??'-'}</td></tr>`;
  }
  return h+'</table>';
}

// condition picker lives inside the header once we know the fixture
function addCond(){
  const s=document.createElement('select'); s.id='cond';
  s.innerHTML=DATA.conditions.map(c=>`<option value="${c}">${CN[c]}</option>`).join('');
  $('#fam').after(s);
  s.onchange=()=>{paint();sidebar();};
}
$('#fx').onchange=e=>{sel.fx=e.target.value;picked=null;render();sidebar();};
$('#fam').onchange=e=>{sel.fam=e.target.value;render();sidebar();};
$('#mode').onchange=e=>{sel.mode=e.target.value;render();sidebar();};
$('#onlylow').onchange=paint;
addCond();render();sidebar();
</script></body></html>
"""


def main() -> int:
    data = build()
    html = HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = RESULTS / "viewer.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KiB, "
          f"{len(data['fixtures'])} fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
