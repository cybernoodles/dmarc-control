import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/alertPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { isExpectedProviderPassAlert } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

test("only expected-provider DMARC-pass source alerts receive the calming context", () => {
  const expectedPass = {
    kind: "new-source-ip",
    provider_expectation: "expected",
    notification_suppressed_reason: "expected-provider-dmarc-pass",
  };
  assert.equal(isExpectedProviderPassAlert(expectedPass), true);

  for (const changed of [
    { ...expectedPass, kind: "dmarc-failure" },
    { ...expectedPass, provider_expectation: "suggested" },
    { ...expectedPass, notification_suppressed_reason: undefined },
  ]) {
    assert.equal(isExpectedProviderPassAlert(changed), false);
  }
});
