import { createHash, createHmac, createPublicKey, verify as verifySignature } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const domain = Buffer.from("OnceMesh receipt signature v1\0", "ascii");
const authorizationDomain = Buffer.from("OnceMesh authorization partition v1\0", "ascii");
const availabilityDomain = Buffer.from("OnceMesh availability manifest v1\0", "ascii");
const federationRequestDomain = Buffer.from("OnceMesh federation HTTP request v1\0", "ascii");
const checks = [];

function fail(message) {
  throw new Error(message);
}

function scalarValues(text) {
  const values = [];
  for (let index = 0; index < text.length; index += 1) {
    const first = text.charCodeAt(index);
    if (first >= 0xd800 && first <= 0xdbff) {
      if (index + 1 >= text.length) fail("unicode_surrogate");
      const second = text.charCodeAt(index + 1);
      if (second < 0xdc00 || second > 0xdfff) fail("unicode_surrogate");
      values.push(0x10000 + ((first - 0xd800) << 10) + second - 0xdc00);
      index += 1;
    } else if (first >= 0xdc00 && first <= 0xdfff) {
      fail("unicode_surrogate");
    } else {
      values.push(first);
    }
  }
  return values;
}

function compareKeys(left, right) {
  const a = scalarValues(left);
  const b = scalarValues(right);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function canonicalJson(value) {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "string") {
    scalarValues(value);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value)) fail("floating_point");
    if (!Number.isSafeInteger(value)) fail("unsafe_integer");
    return String(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort(compareKeys).map((key) => {
      scalarValues(key);
      return `${JSON.stringify(key)}:${canonicalJson(value[key])}`;
    }).join(",")}}`;
  }
  fail("unsupported_type");
}

function digest(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function load(name) {
  return JSON.parse(readFileSync(join(root, name), "utf8"));
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) fail(`${label}: expected ${expected}, received ${actual}`);
  checks.push(label);
}

for (const vector of load("canonical-json-v0.json").vectors) {
  const encoded = canonicalJson(vector.value);
  assertEqual(encoded, vector.canonical_json, `canonical-json:${vector.name}:canonical`);
  assertEqual(digest(Buffer.from(encoded, "utf8")), vector.digest, `canonical-json:${vector.name}:digest`);
}

for (const vector of load("authorization-partitions-v1.json").vectors) {
  const key = Buffer.from(vector.partition_key_hex, "hex");
  const mac = createHmac("sha256", key)
    .update(Buffer.concat([authorizationDomain, Buffer.from(canonicalJson(vector.claims), "utf8")]))
    .digest("hex");
  assertEqual(`hmac-sha256:${mac}`, vector.authorization_partition, `authorization:${vector.name}`);
}

for (const [file, valueField, digestField] of [
  ["action-digests-v0.json", "action", "action_digest"],
  ["pdf-actions-v0.json", "action", "action_digest"],
  ["source-validations-v0.json", "record", "validation_digest"],
]) {
  for (const vector of load(file).vectors) {
    const encoded = canonicalJson(vector[valueField]);
    assertEqual(encoded, vector.canonical_json, `${file}:${vector.name}:canonical`);
    assertEqual(digest(Buffer.from(encoded, "utf8")), vector[digestField], `${file}:${vector.name}:digest`);
  }
}

for (const vector of load("derived-lineage-v0.json").vectors) {
  const manifest = canonicalJson(vector.manifest);
  assertEqual(manifest, vector.manifest_canonical_json, `lineage:${vector.name}:manifest-canonical`);
  assertEqual(digest(Buffer.from(manifest, "utf8")), vector.manifest_digest, `lineage:${vector.name}:manifest-digest`);
  const invalidation = canonicalJson(vector.invalidation);
  assertEqual(invalidation, vector.invalidation_canonical_json, `lineage:${vector.name}:invalidation-canonical`);
  assertEqual(digest(Buffer.from(invalidation, "utf8")), vector.invalidation_digest, `lineage:${vector.name}:invalidation-digest`);
}

for (const vector of load("canonicalization-negative-v0.json").vectors) {
  let rejected = false;
  try {
    canonicalJson(vector.value);
  } catch (error) {
    rejected = error.message === vector.reason;
  }
  if (!rejected) fail(`negative:${vector.name}:not rejected as ${vector.reason}`);
  checks.push(`negative:${vector.name}`);
}

for (const vector of load("receipt-signatures-v1.json").vectors) {
  const receipt = vector.signed_receipt;
  assertEqual(digest(Buffer.from(canonicalJson(receipt), "utf8")), vector.receipt_digest, `receipt:${vector.name}:digest`);
  const publicBytes = Buffer.from(vector.public_key_hex, "hex");
  assertEqual(digest(publicBytes), receipt.signature.key_id, `receipt:${vector.name}:key-id`);
  const publicKey = createPublicKey({
    key: { kty: "OKP", crv: "Ed25519", x: publicBytes.toString("base64url") },
    format: "jwk",
  });
  const unsigned = { ...receipt, signature: null };
  const signingInput = Buffer.concat([domain, Buffer.from(canonicalJson(unsigned), "utf8")]);
  const signature = Buffer.from(receipt.signature.value, "base64url");
  if (!verifySignature(null, signingInput, publicKey, signature)) fail(`receipt:${vector.name}:signature`);
  checks.push(`receipt:${vector.name}:signature`);

  const tampered = { ...unsigned, producer: `${unsigned.producer}:tampered` };
  const tamperedInput = Buffer.concat([domain, Buffer.from(canonicalJson(tampered), "utf8")]);
  if (verifySignature(null, tamperedInput, publicKey, signature)) fail(`receipt:${vector.name}:tamper accepted`);
  checks.push(`receipt:${vector.name}:tamper-rejected`);
}

for (const vector of load("availability-signatures-v0.json").vectors) {
  const manifest = vector.signed_manifest;
  assertEqual(digest(Buffer.from(canonicalJson(manifest), "utf8")), vector.manifest_digest, `availability:${vector.name}:digest`);
  const publicBytes = Buffer.from(vector.public_key_hex, "hex");
  assertEqual(digest(publicBytes), manifest.signature.key_id, `availability:${vector.name}:key-id`);
  const publicKey = createPublicKey({
    key: { kty: "OKP", crv: "Ed25519", x: publicBytes.toString("base64url") }, format: "jwk",
  });
  const unsigned = { ...manifest, signature: null };
  const signingInput = Buffer.concat([availabilityDomain, Buffer.from(canonicalJson(unsigned), "utf8")]);
  const signature = Buffer.from(manifest.signature.value, "base64url");
  if (!verifySignature(null, signingInput, publicKey, signature)) fail(`availability:${vector.name}:signature`);
  checks.push(`availability:${vector.name}:signature`);
  const tampered = { ...unsigned, peer_id: "attacker" };
  const tamperedInput = Buffer.concat([availabilityDomain, Buffer.from(canonicalJson(tampered), "utf8")]);
  if (verifySignature(null, tamperedInput, publicKey, signature)) fail(`availability:${vector.name}:tamper accepted`);
  checks.push(`availability:${vector.name}:tamper-rejected`);
}

for (const vector of load("federation-request-signatures-v0.json").vectors) {
  const request = vector.request;
  const encoded = Buffer.from(canonicalJson(request), "utf8");
  assertEqual(digest(encoded), vector.request_digest, `federation-request:${vector.name}:digest`);
  const publicBytes = Buffer.from(vector.public_key_hex, "hex");
  assertEqual(digest(publicBytes), vector.key_id, `federation-request:${vector.name}:key-id`);
  const publicKey = createPublicKey({
    key: { kty: "OKP", crv: "Ed25519", x: publicBytes.toString("base64url") }, format: "jwk",
  });
  const signature = Buffer.from(vector.signature, "base64url");
  const signingInput = Buffer.concat([federationRequestDomain, encoded]);
  if (!verifySignature(null, signingInput, publicKey, signature)) fail(`federation-request:${vector.name}:signature`);
  checks.push(`federation-request:${vector.name}:signature`);
  const tamperedInput = Buffer.concat([
    federationRequestDomain,
    Buffer.from(canonicalJson({ ...request, path: "/v0/bundles/sha256:" + "0".repeat(64) }), "utf8"),
  ]);
  if (verifySignature(null, tamperedInput, publicKey, signature)) fail(`federation-request:${vector.name}:tamper accepted`);
  checks.push(`federation-request:${vector.name}:tamper-rejected`);
}

process.stdout.write(`${JSON.stringify({
  spec_version: "oncemesh.cross-language-report/v0",
  implementation: `node/${process.version}`,
  checks: checks.length,
  passed: true,
}, null, 2)}\n`);
