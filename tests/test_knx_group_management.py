"""Private group management preserves immutable sources and taxonomy conflicts."""

import hashlib
import subprocess
from dataclasses import replace

import pytest

from mcpserver.admin import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.knx.admin import dispatch_knx
from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.model import KnxError
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml


@pytest.mark.parametrize("changed", [False, True])
def test_initial_group_bundle_is_reused_only_for_current_revisions(changed):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const w=new JSDOM(html,{url:'https://group.example/knx.cgi',runScripts:'outside-only'}).window;
const el=id=>w.document.getElementById(id);let resume,reads=0;
w.localStorage.setItem('mcpserver.knx.sections.v1',JSON.stringify({'knx-group-management':true}));
const state={target:'a'.repeat(64),revision:1,total:0,offset:0,items:[],taxonomy:[],
 taxonomy_revision:'old',imported_labels:[]};
const group=(value)=>({...value,total:1,groups:[{
 prefix:'1',level:'main',address_format:'three_level',
 imported_name:value.revision===1?'Original':'Current',manual_label:null,address_count:0}]});
w.fetch=async(_,o)=>{
 const action=o.body.get('action');let data;
 if(action==='knx_page'){
  assert(JSON.parse(o.body.get('payload')).initial_groups);
  await new Promise(resolve=>resume=resolve);
  data={...state,sections:{knx_groups_page:{ok:true,data:group(state)}}};
 }else{assert.equal(action,'knx_groups_page');reads++;data=group({...state,revision:2,taxonomy_revision:'new'});}
 return{ok:true,json:async()=>({ok:true,data})};
};
const settle=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx.js','utf8'));await settle();
 el('knx-group-management').open=false;await settle();resume();await settle();assert.equal(reads,0);
 if(CHANGED)w.MCPKnx.render({...state,revision:2,taxonomy_revision:'new'});
 el('knx-group-management').open=true;await settle();
 assert.equal(reads,CHANGED?1:0);
 assert.match(el('knx-group-rows').textContent,CHANGED?/Current/:/Original/);w.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
""".replace("CHANGED", "true" if changed else "false")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_groups_include_empty_and_local_groups_with_preserved_source_counts(tmp_path):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    document = parse_xml(
        (
            f'<GroupAddress-Export xmlns="{NAMESPACE}">'
            '<GroupRange Name="Main" RangeStart="2048" RangeEnd="4095">'
            '<GroupRange Name="Middle" RangeStart="2560" RangeEnd="2815">'
            '<GroupAddress Address="1/2/3" Name="Function"/></GroupRange></GroupRange>'
            '<GroupRange Name="Empty" RangeStart="4096" RangeEnd="6143"/>'
            "</GroupAddress-Export>"
        ).encode()
    )
    ImportRepository(store).apply("target", 0, document, select_candidates(document), set(), {})
    store.put(
        "target", 1, dict(address="1/515", address_format="two_level", fields={"name": "Local"})
    )
    manual = [
        dict(address_format="three_level", prefix=prefix, label=label)
        for prefix, label in [("1", "Override"), ("3/2", "Local empty"), ("1/2/3", "Address label")]
    ]
    page = store.admin_groups("target", manual)
    groups = {row["prefix"]: row for row in page["groups"]}
    assert list(groups) == ["1", "1/2", "2", "3/2"]
    assert groups["1"]["imported_name"] == "Main"
    assert groups["1"]["manual_label"] == "Override"
    assert groups["1/2"]["address_count"] == 1
    assert groups["2"]["address_count"] == groups["3/2"]["address_count"] == 0
    assert store.admin_groups("target", [], query="middle")["total"] == 1
    assert store.admin_groups("other", manual)["groups"][0]["imported_name"] is None


@pytest.mark.parametrize(
    "field", ["prefix", "format", "imported_name", "manual_label", "address_count"]
)
def test_group_order_is_global_before_pagination(tmp_path, field):
    store = KnxStore(tmp_path / "metadata.sqlite3")
    manual = [
        dict(
            address_format="three_level",
            prefix=f"{main}/{middle}",
            label=f"N{71 - (main * 8 + middle):03}",
        )
        for main in range(9)
        for middle in range(8)
    ]
    order = {"field": field, "direction": "ascending"}
    first = store.admin_groups("target", manual, table_sort=order)
    second = store.admin_groups("target", manual, offset=50, table_sort=order, expected=0)
    rows = first["groups"] + second["groups"]
    assert len(rows) == 72 and len({row["prefix"] for row in rows}) == 72
    if field == "manual_label":
        assert [row["manual_label"] for row in rows] == sorted(row["manual_label"] for row in rows)
    if field == "prefix":
        assert [row["prefix"] for row in rows][:2] == ["0/0", "0/1"]
    with pytest.raises(KnxError, match="knx_revision_conflict"):
        store.admin_groups("target", manual, offset=50, expected=1)


def test_admin_group_labels_reuse_taxonomy_revision_without_deleting_addresses(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    target = "https://group.example"
    configs = AtomicConfigStore(tmp_path / "config.json")
    configs.save(replace(PluginConfig.defaults(), loxone_endpoint=target))
    store = KnxStore(tmp_path / "knx" / "metadata.sqlite3")
    store.put(
        target, 0, dict(address="1/2/3", address_format="three_level", fields={"name": "Keep"})
    )
    token = hashlib.sha256(target.encode()).hexdigest()
    page = dispatch_knx("knx_groups_page", dict(target=token), configs)
    entries = [dict(address_format="three_level", prefix="1/2", label="Middle")]
    saved = dispatch_knx(
        "knx_taxonomy",
        dict(target=token, taxonomy_revision=page["taxonomy_revision"], entries=entries),
        configs,
    )
    with pytest.raises(AdminError) as conflict:
        dispatch_knx(
            "knx_taxonomy",
            dict(target=token, taxonomy_revision=page["taxonomy_revision"], entries=[]),
            configs,
        )
    assert conflict.value.code == "knx_revision_conflict"
    dispatch_knx(
        "knx_taxonomy",
        dict(target=token, taxonomy_revision=saved["taxonomy_revision"], entries=[]),
        configs,
    )
    assert store.page(target)["items"][0]["effective"]["name"] == "Keep"
    assert dispatch_knx("knx_groups_page", dict(target=token), configs)["groups"] == []
    with pytest.raises(AdminError):
        dispatch_knx("knx_groups_page", dict(target=token, offset=50), configs)


@pytest.mark.parametrize("fail_refresh", [False, True])
def test_group_ui_lazy_loads_preserves_editor_and_uses_saved_revision(fail_refresh):
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const w=new JSDOM(html,{url:'https://group.example/knx.cgi',runScripts:'outside-only'}).window;
const el=id=>w.document.getElementById(id),calls=[];
el('knx-group-management').dataset.savedRefreshFailed='Saved; reload failed';
let failRefresh=false;
const state={target:'a'.repeat(64),revision:1,total:0,offset:0,items:[],
 taxonomy:[],taxonomy_revision:'original',imported_labels:[]};
let revision='original';
w.fetch=async(_,o)=>{
 const action=o.body.get('action'),p=JSON.parse(o.body.get('payload'));calls.push({action,p});
 let data={...state};
 if(action==='knx_groups_page'){
   if(failRefresh){failRefresh=false;
     return{ok:false,json:async()=>({ok:false,error:{code:'failure'}})};}
   data={...state,total:60,taxonomy_revision:revision,groups:[{
   prefix:'1/2',address_format:'three_level',level:'middle',imported_name:'<img> source',
   manual_label:state.taxonomy[0]?.label ?? null,address_count:0}]};
 }
 if(action==='knx_taxonomy'){
   assert.equal(p.taxonomy_revision,p.entries.length?'original':'external');
   if(p.entries.length)assert.equal(p.entries[0].label,'New label');
   state.taxonomy=p.entries;failRefresh=FAIL_REFRESH;
   data={...state,taxonomy:p.entries,taxonomy_revision:'saved'};
 }
 return{ok:true,json:async()=>({ok:true,data})};
};
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx.js','utf8'));await settle();
 assert.equal(calls.filter(c=>c.action==='knx_groups_page').length,0);
 el('knx-group-management').open=true;await settle();
 assert.equal(calls.filter(c=>c.action==='knx_groups_page').length,1);
 assert.equal(el('knx-group-rows').querySelector('img'),null);
 el('knx-group-rows').querySelector('button').click();
 assert.equal(el('knx-group-prefix').readOnly,true);
 el('knx-group-label').value='New label';el('knx-group-label').dispatchEvent(new w.Event('input'));
 const dialog=el('knx-confirm');
 dialog.showModal=()=>{dialog.open=true;};
 dialog.close=value=>{dialog.returnValue=value;dialog.open=false;
   dialog.dispatchEvent(new w.Event('close'));};
 el('knx-group-form').reset();assert.equal(dialog.open,true);
 dialog.close('cancel');await settle();
 assert.equal(el('knx-group-label').value,'New label');
 el('knx-back').click();assert.equal(dialog.open,true);dialog.close('cancel');await settle();
 revision='external';el('knx-group-refresh').click();await settle();
 assert.equal(el('knx-group-label').value,'New label');
 el('knx-group-query').value='Unsubmitted search';
 el('knx-group-next').click();await settle();
 assert.equal(calls.at(-1).p.query,'');assert.equal(calls.at(-1).p.offset,50);
 el('knx-group-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
 await settle();
 assert.equal(calls.filter(c=>c.action==='knx_taxonomy').length,1);
 assert.equal(el('knx-group-prefix').readOnly,false);
 if(FAIL_REFRESH){
   assert.equal(el('knx-group-status').textContent,'Saved; reload failed');
   assert.equal(el('knx-status').textContent,'Saved; reload failed');
   el('knx-group-refresh').click();await settle();
 }
 el('knx-group-rows').querySelectorAll('button')[1].click();await settle();
 assert.equal(dialog.open,true);
 assert.equal(el('knx-confirm').querySelector('button[value="continue"]').disabled,false);
 dialog.close('cancel');await settle();
 assert.equal(calls.filter(c=>c.action==='knx_taxonomy').length,1);
 assert.equal(el('knx-advanced-labels').open,false);
 w.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    script = script.replace("FAIL_REFRESH", "true" if fail_refresh else "false")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
