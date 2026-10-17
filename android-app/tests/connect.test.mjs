import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { normalizeServerUrl } = createRequire(import.meta.url)("../www/connect-logic.js");

test("sam adres IP dostaje http i domyślny port", () => {
  assert.deepEqual(normalizeServerUrl("192.168.0.15"), { ok: true, url: "http://192.168.0.15:8765" });
});
test("zachowuje podany port i usuwa końcowy ukośnik oraz spacje", () => {
  assert.deepEqual(normalizeServerUrl("  http://10.0.0.2:9000/  "), { ok: true, url: "http://10.0.0.2:9000" });
  assert.deepEqual(normalizeServerUrl("laptop:8765"), { ok: true, url: "http://laptop:8765" });
});
test("adres https bez portu zostaje bez portu", () => {
  assert.deepEqual(normalizeServerUrl("https://asolar.example.com"), { ok: true, url: "https://asolar.example.com" });
});
test("odrzuca puste, błędne i niedozwolone schematy", () => {
  for (const value of ["", "   ", null, undefined, "ftp://192.168.0.1", "javascript://x", "http://", "http://a b"]) {
    const result = normalizeServerUrl(value);
    assert.equal(result.ok, false, String(value));
    assert.ok(result.error);
  }
});
