// Actual browser interactions against the caller's isolated CPU gateway.
// Keys stay in environment/page memory. No screenshots or raw keys are saved.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const args = process.argv.slice(2);
const base = args[args.indexOf('--base-url') + 1];
const out = args[args.indexOf('--out') + 1];
const started = new Date().toISOString();
const checks = [];
let chromiumVersion=null;
(async () => {
  const browser = await chromium.launch({headless:true});
  chromiumVersion=browser.version();
  try {
    const page = await browser.newPage();
    const click = async id => {
      await page.click('#'+id);
      await page.waitForFunction(() => document.getElementById('status').textContent === '完成', null, {timeout:5000});
    };
    const record = (id, evidence={}) => checks.push({test_id:id, expected:'real console/backend assertions', actual:'passed', passed:true, evidence});
    const api = async (path,key,body) => fetch(base+path,{method:body?'POST':'GET',
      headers:{Authorization:'Bearer '+key,'Content-Type':'application/json'},
      body:body?JSON.stringify(body):undefined});
    await page.goto(base+'/console');
    assert((await page.textContent('#tenants')).includes('尚未连接'));
    record('anonymous_console_shell');
    await page.fill('#secret',process.env.ADMIN_API_KEY); await click('connect');
    assert.equal(await page.inputValue('#secret'),''); record('admin_connect_memory_only');
    const name='Browser Alice '+Date.now();
    await page.fill('#name',name); await page.fill('#balance','100000');
    await page.fill('#tokens','100000');await page.fill('#rpm','60');await page.fill('#concurrency','4');
    await click('create'); const alice=await page.inputValue('#tenant');
    assert((await page.textContent('#tenants')).includes(name)); record('tenant_create');
    await page.fill('#tokens','12345');await page.fill('#rpm','12');await page.fill('#concurrency','2');
    await click('limits'); assert.equal(await page.inputValue('#tokens'),'12345'); record('shared_quota_update');
    await page.fill('#keyname','browser agent');await click('issue');
    const key=JSON.parse(await page.textContent('#once'));
    assert(key.api_key && !(await page.textContent('#keys')).includes(key.api_key));record('key_issue_masked_list');
    await click('clear');assert(!(await page.textContent('#once')).includes(key.api_key));
    await click('rotate');const rotated=JSON.parse(await page.textContent('#once'));
    assert.notEqual(rotated.key_id,key.key_id);
    assert.equal((await api('/v1/models',key.api_key)).status,401);
    assert.equal((await api('/v1/models',rotated.api_key)).status,200);record('key_rotate');
    await click('clear');await page.selectOption('#key',rotated.key_id);await click('revoke');
    assert.equal((await api('/v1/models',rotated.api_key)).status,401);record('key_revoke');
    await page.fill('#delta','1000');await page.fill('#reason','browser synthetic credit');await click('credit');
    const tenants=JSON.parse(await page.textContent('#tenants')).items;
    assert.equal(tenants.find(t=>t.tenant_id===alice).balance_micro_usd,101000);record('credit_adjustment');
    await page.fill('#inputprice','4');await page.fill('#outputprice','8');await click('price');
    assert.equal(JSON.parse(await page.textContent('#prices')).items[0].input_micro_usd_per_token,4);
    await page.fill('#inputprice','2');await page.fill('#outputprice','6');await click('price');record('price_versioning');
    await click('issue');const billingKey=JSON.parse(await page.textContent('#once'));await click('clear');
    const response=await api('/v1/chat/completions',billingKey.api_key,{model:process.env.MODEL_ID,
      messages:[{role:'user',content:'browser billing fixture'}],max_tokens:80});
    assert.equal(response.status,200);await click('usage');
    assert.equal(JSON.parse(await page.textContent('#bills')).summary.cost_micro_usd,500);record('real_bill_display');
    await page.selectOption('#tenantstatus','disabled');await click('limits');
    assert.equal((await api('/v1/models',billingKey.api_key)).status,403);record('tenant_disable');
    assert((await page.textContent('#audit')).includes('credit_adjustment'));record('audit_display');
    await click('logout');assert.equal(await page.textContent('#bills'),'');
    assert.equal(await page.textContent('#keys'),'');assert.equal(await page.evaluate(()=>credential),'');record('logout_clears_identity_and_data');
  } finally { await browser.close(); }
})().catch(error => {
  checks.push({test_id:'browser_failure',expected:'all console flows complete',actual:error.name,passed:false,evidence:{}});
  process.exitCode=1;
}).finally(() => {
  const result={schema:'llm-console-browser/1',suite:'mock',execution:'actual_headless_chromium_real_gateway_sqlite',
    commit_sha:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
    working_tree_dirty:!!execFileSync('git',['status','--porcelain'],{encoding:'utf8'}).trim(),
    started_at:started,finished_at:new Date().toISOString(),official_score:false,gpu_used:false,
    chromium_version:chromiumVersion,node_version:process.version,
    browser_binary_target:process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE||'detected',
    host_kernel:require('node:os').release(),checks};
  fs.writeFileSync(out,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({console_checks:checks.length,passed:checks.filter(c=>c.passed).length,failed:checks.filter(c=>!c.passed).length}));
});
