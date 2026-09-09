import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/domainMonitoringView.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { domainSearchIndex, domainSearchTerms, initialDomainDraft, reconcileDomainDraft, storedDomainDraft, domainPage } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("single-label domains never read inherited properties as saved drafts", () => {
  assert.equal(storedDomainDraft({}, "constructor"), undefined);
  assert.equal(storedDomainDraft({}, "toString"), undefined);
  const draft = initialDomainDraft(3);
  const stored = {constructor:draft};
  assert.equal(storedDomainDraft(stored, "constructor"), draft);
  assert.equal(storedDomainDraft({...stored, other:initialDomainDraft(8)}, "constructor"), draft);
});

test("search finds canonical, observed and alias spellings, including complete IDNA names", () => {
  const [entry] = domainSearchIndex([{ domain: "xn--bcher-kva.example", query_domain: "BÜCHER.Example.", aliases: ["Old.Name.Example"] }]);
  for (const query of ["BÜCHER.example", "xn--bcher-kva.example", " OLD.name ", "bu\u0308cher.example", "bücher"]) {
    assert.ok(domainSearchTerms(query).some(term => entry.text.includes(term)), query);
  }
  const [asciiOnly] = domainSearchIndex([{ domain: "xn--bcher-kva.example", query_domain: "xn--bcher-kva.example", aliases: [] }]);
  assert.ok(domainSearchTerms("bücher.example").some(term => asciiOnly.text.includes(term)));
  assert.deepEqual(domainSearchTerms("  "), []);
  assert.deepEqual(domainSearchTerms("old/name"), ["old/name"]);
});

test("last-page bounds stay valid after a query or inventory shrinks", () => {
  assert.deepEqual(domainPage(1000, 39), {page:39,start:975,end:1000});
  assert.deepEqual(domainPage(26, 39), {page:1,start:25,end:26});
  assert.deepEqual(domainPage(1, 39), {page:0,start:0,end:1});
  assert.deepEqual(domainPage(0, 39), {page:0,start:0,end:0});
});

test("a save response keeps edits made during the request, including reverting to the old baseline", () => {
  const original = initialDomainDraft(3);
  const submitted = {...original, grace:"5", revision:1, busy:true};
  assert.equal(reconcileDomainDraft(submitted, 5, 1, true).grace, "5");
  const newer = {...submitted, grace:"3", revision:2};
  const saved = reconcileDomainDraft(newer, 5, 1, true);
  assert.equal(saved.grace, "3");
  assert.equal(saved.baselineGrace, 5);
  assert.equal(saved.revision, 2);
});

test("reloads reconcile clean values while retaining dirty and newly typed drafts on other pages", () => {
  const clean = initialDomainDraft(3);
  assert.equal(reconcileDomainDraft(clean, 8, 0).grace, "8");
  const dirty = {...clean, grace:"12", revision:1};
  assert.equal(reconcileDomainDraft(dirty, 8, 1).grace, "12");
  const editedDuringLoad = {...clean, grace:"3", revision:2, error:"Keep the failed attempt"};
  const loaded = reconcileDomainDraft(editedDuringLoad, 8, 1);
  assert.equal(loaded.grace, "3");
  assert.equal(loaded.error, "Keep the failed attempt");
  assert.equal(reconcileDomainDraft(dirty, 8, undefined).grace, "12");
});
