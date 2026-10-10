"""Exercise the shipped Admin guard display without any Miniserver request."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_guard_display_and_explicit_probe_confirmation() -> None:
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node is not None, "Node.js is required for Admin DOM tests"
    script = r"""
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const dom = new JSDOM(`<details id="sessions"><p id="remote-cleanup-warning"
 data-cooldown-label="Paused" data-public-cooldown-label="Public passwords paused"
 data-uncertain-label="Unavailable"></p>
 <button id="miniserver-auth-probe" data-confirm="Risk warning" hidden></button>
 <div id="session-list"></div></details>`, {runScripts:'outside-only'});
const w = dom.window;
w.McpAdmin = {};
w.eval(fs.readFileSync('webfrontend/htmlauth/admin/sessions.js', 'utf8'));
let guard = {available:true, failure_guard_state:'cooldown',
 next_auth_attempt_at: Math.floor(Date.now()/1000)+120,
 manual_probe_at:Math.floor(Date.now()/1000)+60};
let requests = [], confirmed = false, notices = [];
w.confirm = message => { assert.equal(message,'Risk warning'); return confirmed; };
const sessions = w.McpAdmin.createSessions({
 label: key => key, updateExpiry(){}, setSummaryBadge(){},
 setAjaxStatus: (...args)=>notices.push(args),
 postAjax: async body => {
   requests.push(body.get('action'));
   return {data:{remote_cleanup:guard,status:'available'}};
 }
});
(async()=>{
 const button = w.document.getElementById('miniserver-auth-probe');
 const warning = w.document.getElementById('remote-cleanup-warning');
 await sessions.pollSessions({initial:true}); sessions.stopPoll();
 assert.equal(button.hidden,false); assert.equal(button.disabled,true);
 assert.match(warning.textContent,/Paused/);
 guard.manual_probe_at = Math.floor(Date.now()/1000)-1;
 await sessions.pollSessions({initial:true}); sessions.stopPoll();
 assert.equal(button.disabled,false);
 button.click(); await new Promise(resolve=>setImmediate(resolve));
 assert.equal(requests.filter(action=>action==='miniserver_auth_probe').length,0);
 confirmed = true;
 button.click(); await new Promise(resolve=>setImmediate(resolve)); sessions.stopPoll();
 assert.equal(requests.filter(action=>action==='miniserver_auth_probe').length,1);
 assert.equal(notices[0][0],'success');
 guard = {available:true,failure_guard_state:'persistence_uncertain'};
 await sessions.pollSessions({initial:true}); sessions.stopPoll();
 assert.equal(button.hidden,true); assert.match(warning.textContent,/Unavailable/);
 guard = {available:true,failure_guard_state:'closed',public_failure_guard_state:'cooldown',
 next_public_login_at:Math.floor(Date.now()/1000)+180,manual_probe_at:Math.floor(Date.now()/1000)+60};
 await sessions.pollSessions({initial:true}); sessions.stopPoll();
 assert.equal(button.hidden,false); assert.equal(button.disabled,true);
 assert.match(warning.textContent,/Public passwords paused/);
 assert.match(warning.textContent,/180 s/);
 guard = {available:true,failure_guard_state:'closed',public_failure_guard_state:'closed'};
 await sessions.pollSessions({initial:true}); sessions.stopPoll();
 assert.equal(button.hidden,true); assert.equal(warning.hidden,true);
 dom.window.close();
})().catch(error=>{console.error(error);process.exit(1);});
"""
    result = subprocess.run(
        [node, "-e", script], cwd=root, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
