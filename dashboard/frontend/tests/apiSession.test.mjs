import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { api } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const deferred = () => { let resolve; const promise = new Promise(done => { resolve=done; }); return {promise, resolve}; };
const response = (status, body) => new Response(JSON.stringify(body), {status,headers:{"Content-Type":"application/json"}});

async function harness(run) {
  const oldFetch = globalThis.fetch;
  const oldWindow = globalThis.window;
  let expired = 0;
  globalThis.window = { dispatchEvent: event => { assert.equal(event.type,"dmarc-read-session-expired"); expired++; } };
  try { await run(() => expired); } finally { globalThis.fetch=oldFetch; globalThis.window=oldWindow; }
}

test("a late 401 from the old session cannot end a successful new login", async () => harness(async expired => {
  const old = deferred();
  globalThis.fetch = path => path.includes("read-login") ? Promise.resolve(response(200,{read_authenticated:true})) : old.promise;
  const request = api.host("192.0.2.1","*",30);
  await api.loginRead("reader","password");
  old.resolve(response(401,{detail:"Operator login required"}));
  await assert.rejects(request, error => error.status===401);
  assert.equal(expired(),0);
  globalThis.fetch = async () => response(401,{detail:"Operator login required"});
  await assert.rejects(api.host("192.0.2.1","*",30), error => error.status===401);
  assert.equal(expired(),1);
}));

test("an aborted lookup cannot dispatch a session-expired event", async () => harness(async expired => {
  const pending = deferred();
  globalThis.fetch = () => pending.promise;
  const controller = new AbortController();
  const request = api.host("192.0.2.1","*",30,controller.signal);
  controller.abort();
  pending.resolve(response(401,{detail:"Operator login required"}));
  await assert.rejects(request, error => error.name==="AbortError");
  assert.equal(expired(),0);
}));

test("aborting while an error body loads also suppresses the old session event", async () => harness(async expired => {
  const body = deferred();
  globalThis.fetch = async () => ({ok:false,status:401,json:()=>body.promise});
  const controller = new AbortController();
  const request = api.host("192.0.2.1","*",30,controller.signal);
  await Promise.resolve();
  controller.abort();
  body.resolve({detail:"Operator login required"});
  await assert.rejects(request, error => error.name==="AbortError");
  assert.equal(expired(),0);
}));

test("old responses after explicit logout do not emit another session transition", async () => harness(async expired => {
  const old = deferred();
  globalThis.fetch = path => path.includes("read-logout") ? Promise.resolve(response(200,{read_authenticated:false})) : old.promise;
  const request = api.host("192.0.2.1","*",30);
  await api.logoutRead();
  old.resolve(response(401,{detail:"Operator login required"}));
  await assert.rejects(request, error => error.status===401);
  assert.equal(expired(),0);
}));
