"""Export UI requires explicit values, fresh project checks and HTML confirmation."""

import subprocess


def test_explicit_choices_preview_and_fresh_download_confirmation():
    script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('templates/knx.html', 'utf8').replace(/<TMPL_VAR[^>]*>/g, 'label');
const w = new JSDOM(html, {url: 'https://example.invalid/knx.cgi',
  runScripts: 'outside-only'}).window;
const page = w.document.getElementById('knx-page'), requests = [], pending = [], errors = [];
const el = id => w.document.getElementById('knx-xml-'+id);
let source = null, fresh = true, checks = 0, downloads = 0;
const objects = [{loxone_name: 'First', name_complete: true, project_node_id: 'one',
  project_description: 'Description one', truncated_fields: []},
  {loxone_name: '<img src=x>', name_complete: true, project_node_id: 'two',
   project_description: 'Truncated', truncated_fields: ['description']}];
const saved = {target: 'target', revision: 1};
w.MCPKnx = {snapshot: () => saved,
  run: operation => {
    const task = operation().catch(error => errors.push(error.message))
      .finally(() => page.dispatchEvent(new w.CustomEvent('knx-idle')));
    pending.push(task); return task;
  },
  api: async (action, payload) => {
    requests.push({action,payload});
    if (action === 'knx_xml_preview') return {...saved, draft_id: 'draft',
      project_binding: payload.project_binding, bytes: 100, groups: {}, root_attributes: {},
      rows: [{address_id: 1, address: '0/0/1', before: {Name: 'ETS'},
              after: {Name: payload.choices[0].fields.name || 'ETS'}}]};
    if (action === 'knx_xml_download')
      return {...saved,content: '<xml/>',filename: 'experimental.xml'};
    assert.equal(action, 'knx_xml_discard'); return {discarded:true};
  }};
w.MCPKnxProject = {snapshot: () => source, validate: async binding => {
  checks++;
  if (!fresh || !source || source.binding !== binding) throw new Error('permission_denied');
}};
w.confirm = w.alert = w.prompt = () => {throw new Error('Native dialog forbidden');};
w.URL.createObjectURL = () => 'blob:synthetic'; w.URL.revokeObjectURL = () => {};
w.HTMLAnchorElement.prototype.click = function() {downloads++;};
w.eval(fs.readFileSync('webfrontend/htmlauth/knx-xml-export.js', 'utf8'));
const click = async id => {el(id).click(); await Promise.all(pending.splice(0));};
(async () => {
  assert(el('preview').disabled);
  source = {...saved,binding:'project-1',items:[{address_id:1,project_objects:objects,
    local_metadata:{address:'0/0/1',imported:{name:'ETS'}}}]};
  page.dispatchEvent(new w.CustomEvent('knx-project-state'));
  const selects = el('rows').querySelectorAll('select');
  assert.equal(selects[0].value,'keep');
  assert.equal(selects[0].options.length,4);
  assert.equal(selects[1].options.length,3); // Truncated description is never proposed.
  assert.equal(el('rows').querySelectorAll('img').length,0);
  el('rows').querySelector('input[type="checkbox"]').click();
  selects[0].value='object:1'; selects[0].dispatchEvent(new w.Event('change'));
  await click('preview');
  assert.equal(requests[0].payload.choices[0].fields.name,'<img src=x>');
  assert(!Object.hasOwn(requests[0].payload.choices[0].fields,'description'));
  assert.equal(checks,1); assert(el('download').disabled);
  assert.match(el('result').textContent,/ETS.*<img src=x>/);
  assert.equal(el('result').querySelectorAll('img').length,0);
  el('confirm').click(); assert(!el('download').disabled);
  fresh=false; await click('download');
  assert.equal(errors.at(-1),'permission_denied'); assert.equal(downloads,0);
  assert.equal(requests.filter(x=>x.action==='knx_xml_download').length,0);
  fresh=true; await click('download');
  assert.equal(checks,3); assert.equal(downloads,1);
  assert.equal(requests.at(-1).payload.confirmed_experimental,true);
  source={...source,binding:'project-2'};
  page.dispatchEvent(new w.CustomEvent('knx-project-state'));
  assert(el('download').disabled); assert(!el('confirm').checked);
  await click('clear'); assert.equal(requests.at(-1).action,'knx_xml_discard');
  assert(requests.every(x=>x.action.startsWith('knx_xml_')));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
