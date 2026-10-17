"""Global Admin table ordering retains source identity and bounded pagination."""

import subprocess
from pathlib import Path

import pytest
from test_knx_file_comparison import load, setup, xml

from mcpserver.knx.correction_projection import project_draft
from mcpserver.knx.model import KnxError
from mcpserver.knx.read_model import table_order
from mcpserver.knx.store import KnxStore


@pytest.mark.parametrize(
    "value",
    [
        [],
        "address",
        {},
        {"field": "address", "direction": "up"},
        {"field": "arbitrary SQL", "direction": "ascending"},
        {"field": "address", "direction": "ascending", "extra": True},
    ],
)
def test_table_order_rejects_non_allowlisted_presentations(value):
    with pytest.raises(KnxError):
        table_order(value, ("address", "name"))


@pytest.mark.parametrize(
    "field", ["address", "imported_name", "manual_name", "description", "sources"]
)
@pytest.mark.parametrize("direction", ["ascending", "descending"])
def test_catalog_global_order_and_json_exchange_use_same_page(tmp_path, field, direction):
    store = KnxStore(tmp_path / "knx.sqlite3")
    records = [
        dict(
            address_id=n,
            address=f"0/0/{n}",
            address_format="three_level",
            imported={"name": f"Imported {80 - n:03d}", "description": f"D {n:03d}"},
            overrides={"name": f"Manual {60 - n:03d}"} if n % 2 else {},
        )
        for n in range(60)
    ]
    store.restore("target", 0, {"schema_version": 1, "records": records})
    order = {"field": field, "direction": direction}
    first = store.page("target", 0, table_sort=order)
    second = store.page("target", 50, table_sort=order)
    rows = first["items"] + second["items"]
    assert len(rows) == 60 and len({row["address_id"] for row in rows}) == 60

    def value(row):
        return (
            row["address_id"]
            if field == "address"
            else (
                row["overrides"].get("name", "")
                if field == "manual_name"
                else row["imported"]["name"]
                if field == "imported_name"
                else row["effective"]["description"]
                if field == "description"
                else 2 + bool(row["overrides"])
            )
        )

    values = [value(row) for row in rows]
    expected = sorted(
        [v for v in values if field != "manual_name" or v], reverse=direction == "descending"
    )
    if field == "manual_name":
        expected += [""] * values.count("")
    assert values == expected
    exported = store.export("target", 50, table_sort=order)
    assert [row["address_id"] for row in exported["records"]] == [
        row["address_id"] for row in second["items"]
    ]


@pytest.mark.parametrize("field", ["address", "change", "before", "after", "manual"])
@pytest.mark.parametrize("direction", ["ascending", "descending"])
def test_file_comparison_sorts_before_pagination(tmp_path, field, direction):
    _, _, service = setup(tmp_path)
    left = load(service, xml(""), "left", fmt="three_level")
    right = load(
        service,
        xml("".join(f'<GroupAddress Address="0/0/{n}" Name="N{80 - n:03d}"/>' for n in range(60))),
        "right",
    )
    args = dict(
        left_id=left["draft_id"],
        right_id=right["draft_id"],
        revision=right["revision"],
        taxonomy_revision=right["taxonomy_revision"],
        sort={"field": field, "direction": direction},
    )
    first = service.page(args)
    last = service.page({**args, "offset": 50})
    assert first["has_more"] and not last["has_more"]
    assert first["counts"] == last["counts"]
    rows = first["rows"] + last["rows"]
    assert len(rows) == 60 and len({row["identity"] for row in rows}) == 60
    if field in {"address", "after"}:
        values = [row["address_id"] if field == "address" else row["after"]["name"] for row in rows]
        assert values == sorted(values, reverse=direction == "descending")


def test_sorted_correction_projection_exposes_original_detail_offsets():
    changes = []
    for n, name in enumerate(["Zebra", "Alpha" + "x" * 130]):
        changes.append(
            dict(
                change_id=str(n),
                destination="local_metadata",
                kind="address",
                address_format="three_level",
                address=f"1/2/{n}",
                field="name",
                operation="set",
                value=name,
                sources={"imported": {}, "manual": {}},
                decision="pending",
            )
        )
    draft = dict(
        changes=changes,
        draft_id="draft",
        catalog_revision=1,
        manual_revision="manual",
        draft_revision=1,
        expires_at=100,
        created_at=1,
        project_binding=None,
        catalog_stale=False,
        manual_stale=False,
        project_status="not_required",
    )
    raw = {"target_id": "target", "draft": draft}
    result = project_draft(raw, 0, 1, False, {"field": "proposed", "direction": "ascending"})
    assert result["changes"][0]["change_id"] == "1"
    assert result["change_offsets"] == [1] and result["next_offset"] == 1
    detail = project_draft(raw, result["change_offsets"][0], 1, True)
    assert detail["changes"][0]["proposed"]["value"] == changes[1]["value"]
    assert not detail["changes"][0]["proposed"]["truncated"]
    assert "change_offsets" not in detail  # Public/default projection is unchanged.


def test_table_headers_keep_nodes_preferences_and_global_catalog_request():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const saved=new Map(),calls=[];
const setup=()=>{
 const w=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}).window;
 Object.defineProperty(w,'sessionStorage',{value:{getItem:k=>saved.get(k)||null,
   setItem:(k,v)=>saved.set(k,v)}});
 w.fetch=async(_url,o)=>{const action=o.body.get('action');
   const payload=JSON.parse(o.body.get('payload'));
   calls.push({action,payload});return{ok:true,json:async()=>({ok:true,data:{target:'a'.repeat(64),
     revision:1,total:0,offset:0,items:[],taxonomy:[],imported_labels:[]}})};};
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx.js','utf8'));return w;
};
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
(async()=>{
 let w=setup();await settle();
 const body=w.document.getElementById('knx-corrections-list'),table=body.closest('table');
 const records=[10,2,1].map(n=>{const row=w.document.createElement('tr');
   for(const text of ['id'+n,1,'date',n]){const td=w.document.createElement('td');
     td.textContent=text;row.append(td);}
   const td=w.document.createElement('td'),input=w.document.createElement('input');
   input.type='checkbox';input.checked=n===2;td.append(input);row.append(td);return row;});
 body.append(...records);await settle();
 const sort=table.querySelectorAll('th button')[3];sort.click();await settle();
 assert.deepEqual([...body.rows].map(r=>r.cells[3].textContent),['1','2','10']);
 assert.equal(table.querySelector('th:last-child button'),null);
 assert.equal(table.querySelectorAll('th')[3].getAttribute('aria-sort'),'ascending');
 assert.equal(records[1].querySelector('input').checked,true);
 assert.equal(body.rows[1],records[1]);sort.click();await settle();
 assert.equal(body.rows[0],records[0]);
 const address=w.document.getElementById('knx-addresses').closest('table');
 address.querySelectorAll('th button')[3].click();await settle();
 assert.equal(calls.at(-1).payload.sort.field,'imported_name');
 assert.equal(calls.at(-1).payload.offset,0);
 w.close();w=setup();await settle();
 assert.equal(calls.at(-1).payload.include_sections,true);
 assert.equal(calls.at(-1).payload.sort.field,'imported_name');
 assert.equal(w.document.querySelector('#knx-addresses').closest('table')
   .querySelectorAll('th')[3].getAttribute('aria-sort'),'ascending');
 assert(![...saved.values()].join('').includes('id10'));
 w.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_project_reload_reads_fresh_pages_and_uncertain_reads_keep_stale_view():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const saved=new Map(),calls=[],target='a'.repeat(64);let version=1,fail=false,sort=null;
const create=()=>{
 const w=new JSDOM(html,{url:'https://local.example/knx.cgi',runScripts:'outside-only'}).window;
 Object.defineProperty(w,'sessionStorage',{value:{getItem:k=>saved.get(k)||null,
  setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)}});
 const page=w.document.getElementById('knx-page');page.removeAttribute('aria-busy');
 let handler;w.MCPKnx={snapshot:()=>({target,revision:1}),
  tables:{selection:()=>sort,bind:(_id,h)=>handler=h}};
 w.changeSort=()=>{sort={field:'observation',direction:'descending'};handler();};
 for(const file of ['explorer-core.js','explorer-state.js'])
   w.eval(fs.readFileSync('webfrontend/htmlauth/'+file,'utf8'));
 w.McpExplorerAuth={create:o=>({discover:async()=>({authorizationMetadata:{},resourceMetadata:{resource:'local'}}),
  refreshAccessToken:async()=>o.explorerState.updateToken({access_token:'synthetic',scope:'loxone:read',
   expires_in:60,expires_at:Date.now()/1000+60}),accessToken:async()=>'synthetic',
  fetchWithTimeout:async(_url,o)=>{const args=JSON.parse(o.body.get('payload'));calls.push(args);
   if(fail)throw Error('Transient');
   const item={group_address:'1/2/'+args.offset,comparison:{relation:'common',project_objects:[],
    local_metadata:{imported:{name:'PrivateName'+version},manual:{},import_info:{}},
    names_differ:version===2,name_comparison:'compared',project_names_complete:true}};
   return{ok:true,json:async()=>({ok:true,data:{ok:true,stale:false,observed_at:'now',data:{
    findings:[item],next_cursor:args.offset===0?'more':null,project_fingerprint:'fingerprint',model_version:14,
    summaries:{ets_project_comparison:{target_binding:target,knx_revision:1,import_info:{},
     counts:{common:2,import_only:0,observed_project_only:0,name_deviations:0}}}}}})};
  }})};
 w.McpExplorerClient={create:()=>({initialize:async()=>[],
  callTool:()=>{throw Error('Unexpected public call');}})};
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx-project.js','utf8'));return w;
};
const settle=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
const click=async(w,id)=>{w.document.getElementById('knx-project-'+id).click();await settle();};
(async()=>{
 let w=create();await settle();await click(w,'run');await click(w,'next');
 assert.equal(calls.length,2);assert.equal(calls.at(-1).offset,1);
 await click(w,'previous');await click(w,'next');assert.equal(calls.length,2);
 assert(![...saved.values()].join('').includes('PrivateName'));
 assert(![...saved.values()].join('').includes('synthetic'));
 w.close();version=2;w=create();await settle();
 assert.equal(calls.length,3);assert.equal(calls.at(-1).offset,1);
 assert.match(w.document.getElementById('knx-project-rows').textContent,/PrivateName2/);
 w.changeSort();await settle();assert.equal(calls.at(-1).sort.field,'observation');
 assert.equal(calls.at(-1).offset,0);
 fail=true;await click(w,'run');
 assert.match(w.document.getElementById('knx-project-rows').textContent,/PrivateName2/);
 assert.equal(w.MCPKnxProject.snapshot(),null);
 fail=false;await click(w,'run');assert(w.MCPKnxProject.snapshot());
 w.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
