import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Exercise the shipped parser with the existing compiler; no browser or added
// dependency is needed for this portable URL contract regression suite.
const source = await readFile(new URL("../src/investigationLocation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { validDomain, validDays, validHost, readInvestigationLocation, investigationUrl } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const base = "https://dashboard.example/";

test("domain filtering preserves the observed spelling, including IDNA and historical domains", () => {
  for (const domain of ["example.org", "Old.Example.", "bücher.example", "xn--bcher-kva.example", "*"]) {
    assert.equal(validDomain(` ${domain} `), domain);
  }
  for (const domain of ["", "https://example.org", "x/y", "x@y.example", "*.example", "x..example", "example..", "x%2ey", "a".repeat(64)+".example", "x\n.example"]) {
    assert.equal(validDomain(domain), "*", domain);
  }
});

test("period accepts the full API range and safely defaults malformed values", () => {
  for (const [input, expected] of [[1,1],[730,730],[" 90 ",90],["45",45],["001",1]]) assert.equal(validDays(input), expected);
  for (const input of [null, undefined, "", "0", -1, "731", "1.5", "1e2", "Infinity", true, "0090"]) assert.equal(validDays(input), 30);
});

test("source links accept IP addresses without accepting arbitrary paths or hostnames", () => {
  for (const ip of ["192.0.2.1", "2001:db8::1", "::ffff:192.0.2.1"]) assert.equal(validHost(ip), ip);
  for (const ip of ["999.1.1.1", "example.org", "1.2.3", "2001:::1", "192.0.2.1/notes", "::1%eth0"]) assert.equal(validHost(ip), undefined);
});

test("legacy links retain their target and gain default investigation filters", () => {
  const route = readInvestigationLocation(base + "?view=alerts&alert=legacy-a_1");
  assert.equal(route.alert, "legacy-a_1");
  assert.equal(route.domain, "*");
  assert.equal(route.days, 30);
  const query = new URL(investigationUrl(route, base)).searchParams;
  assert.equal(query.get("alert"), "legacy-a_1");
  assert.equal(query.get("domain"), "*");
  assert.equal(query.get("days"), "30");
});

test("host investigation round trip retains its own and its origin context", () => {
  const route = { view:"hosts", domain:"bücher.example", days:90, host:"2001:db8::1", fromAlert:"v2-a-b", fromDomain:"*", fromDays:365 };
  const url = investigationUrl(route, base);
  const recovered = readInvestigationLocation(url);
  for (const [key,value] of Object.entries(route)) assert.equal(recovered[key], value, key);
  assert.equal(recovered.alert, undefined);
});

test("changing views removes irrelevant targets but preserves unrelated URL parameters", () => {
  const url = investigationUrl({view:"alerts",domain:"example.org",days:45,alert:"a-1"}, base+"?host=192.0.2.1&from_alert=a-2&from_domain=old.example&from_days=90&custom=keep#anchor");
  const parsed = new URL(url);
  for (const key of ["host","from_alert","from_domain","from_days"]) assert.equal(parsed.searchParams.has(key),false);
  assert.equal(parsed.searchParams.get("custom"),"keep");
  assert.equal(parsed.hash,"#anchor");
});

test("invalid or irrelevant targets never survive parsing", () => {
  const route = readInvestigationLocation(base+"?view=hosts&host=attacker.example&alert=a-1&from_alert=../../settings&domain=https://bad.example&days=NaN");
  assert.equal(route.host,undefined);
  assert.equal(route.alert,undefined);
  assert.equal(route.fromAlert,undefined);
  assert.equal(route.domain,"*");
  assert.equal(route.days,30);
  assert.equal(readInvestigationLocation(base+"?view=unexpected").view,"overview");
});
