"""Draft review controls explain destinations and keep confirmation separate from effects."""

import subprocess


def test_batch_review_archive_metadata_and_ets_editor_use_distinct_controls():
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('templates/knx.html','utf8').replace(/<TMPL_VAR[^>]*>/g,'label');
const w=new JSDOM(html,{url:'https://example.invalid/knx.cgi',runScripts:'outside-only'}).window;
const el=id=>w.document.getElementById(id), section=el('knx-corrections');
Object.assign(section.dataset,{accept:'Confirm',selectExport:'Export',reviewSelect:'Review',
  localTarget:'Local',etsTarget:'ETS',set:'Set',edit:'Edit',proposed:'Proposed',accepted:'Confirmed'});
const target='b'.repeat(64),draft={draft_id:'a'.repeat(48),draft_revision:1,created_at:1000,
 expires_at:2000000000,catalog_revision:5,manual_revision:'c'.repeat(64),change_count:2,
 metadata:{title:'<script>title</script>',source_chat:'My chat'},archived:false};
const field={state:'value',value:'Name',truncated:false};
const changes=[0,1].map(i=>({change_id:String(i+1).repeat(24),identity:`1/2/${i}`,
 kind:'address',destination:'ets_export',field:'name',operation:'set',decision:'proposed',
 imported:field,manual:{state:'missing'},proposed:field,evidence_note:field}));
const calls=[],asks=[];
w.MCPKnx={ask:async text=>{asks.push(text);return true;}};
w.fetch=async(_,options)=>{
 const action=options.body.get('action'),p=JSON.parse(options.body.get('payload'));
 calls.push({action,p});
 let data;
 if(action==='knx_correction_page')data={target,drafts:[{...draft}]};
 else if(action==='knx_correction_review'){
   assert.equal(p.decisions.length,2);p.decisions.forEach(d=>changes.find(c=>c.change_id===d.change_id).decision=d.decision);
   draft.draft_revision++;data={target,draft_id:draft.draft_id,draft_revision:draft.draft_revision};
 }else if(action==='knx_correction_manage'){
   assert.equal(p.draft_revision,draft.draft_revision);assert.match(p.request_id,/^[0-9a-f]{32}$/);
   if(p.operation==='metadata')draft.metadata=p.metadata;
   if(p.operation==='archive')draft.archived=true;
   draft.draft_revision++;data={target,managed:true};
 }else data={draft:{...draft},catalog_stale:false,manual_stale:false,
   project_status:'not_required',next_offset:null,changes};
 return {ok:true,json:async()=>({ok:true,data})};
};
const tick=()=>new Promise(r=>setTimeout(r,0));
(async()=>{
 w.eval(fs.readFileSync('webfrontend/htmlauth/knx-corrections.js','utf8'));await tick();
 el('knx-corrections-list').querySelector('button').click();await tick();
 assert.equal(el('knx-draft-title').value,'<script>title</script>');
 assert.equal(el('knx-corrections-list').querySelector('script'),null);
 const row=el('knx-corrections-values').querySelector('tr');
 assert.equal(row.children[7].querySelector('input').type,'checkbox');
 assert.equal(row.children[8].querySelector('input'),null);
 row.querySelector('details summary').click();await tick();await tick();
 assert.equal(row.querySelector('select'),null);assert.ok(row.querySelector('textarea'));
 assert.equal(row.querySelector('textarea').disabled,false);
 el('knx-draft-summary').value='Unsaved reason';
 el('knx-draft-summary').dispatchEvent(new w.Event('input',{bubbles:true}));
 el('knx-draft-confirm-all').click();await tick();await tick();
 assert.equal(changes[0].decision,'accepted');assert.equal(asks.length,1);
 assert.equal(el('knx-draft-summary').value,'Unsaved reason');
 const accepted=el('knx-corrections-values').querySelector('tr');
 assert.equal(accepted.children[8].querySelector('input').type,'checkbox');
 assert.equal(accepted.lastElementChild.querySelector('input'),null);
 assert.equal(calls.some(c=>c.action==='knx_correction_apply'||c.action==='knx_correction_xml_download'),false);
 el('knx-draft-summary').value='Reason';
 el('knx-correction-metadata-form').dispatchEvent(
   new w.Event('submit',{bubbles:true,cancelable:true}));await tick();await tick();
 assert.equal(draft.metadata.summary,'Reason');
 el('knx-draft-archive').click();await tick();await tick();
 assert.equal(el('knx-draft-confirm-all').disabled,true);
 assert.equal(el('knx-corrections-values').querySelector('input'),null);
 assert.equal(el('knx-draft-restore').hidden,false);
 w.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
