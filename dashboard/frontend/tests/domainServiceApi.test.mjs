import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { api } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const assessment = {
  service_id: "microsoft/365",
  label: "Microsoft 365",
  decision: "confirmed",
  effective_status: "expected",
  dns_status: "fresh",
  evidence: [],
  contradictions: [],
};

function response(body) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

test("domain service decisions encode both path segments and send only the decision", async () => {
  const previousFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (path, options) => {
    request = { path, options };
    return response(assessment);
  };
  try {
    assert.deepEqual(
      await api.setDomainServiceDecision("bücher.example", "microsoft/365", "confirmed"),
      assessment,
    );
    assert.equal(
      request.path,
      "/api/settings/domains/b%C3%BCcher.example/services/microsoft%2F365",
    );
    assert.equal(request.options.method, "PUT");
    assert.deepEqual(JSON.parse(request.options.body), { decision: "confirmed" });
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("domain service refresh uses the dedicated POST endpoint without a request body", async () => {
  const previousFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (path, options) => {
    request = { path, options };
    return response(assessment);
  };
  try {
    await api.refreshDomainServiceAssessment("example.org", "microsoft-365");
    assert.equal(
      request.path,
      "/api/settings/domains/example.org/services/microsoft-365/refresh",
    );
    assert.equal(request.options.method, "POST");
    assert.equal(request.options.body, undefined);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
