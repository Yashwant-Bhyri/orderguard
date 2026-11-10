// Synthetic WebAuthn authenticator used by the bridge, the quickstart flow and the tests.
// It is a software passkey: a throw-away P-256 key that signs standards-shaped assertions.
// It stands in for the human owner's device and is never a real credential.
import { createHash, generateKeyPairSync, randomBytes, sign } from "node:crypto";

const b64url = (value) => Buffer.from(value).toString("base64url");

function cborHead(major, value) {
  if (value < 24) return Buffer.from([(major << 5) | value]);
  if (value <= 0xff) return Buffer.from([(major << 5) | 24, value]);
  if (value <= 0xffff) return Buffer.from([(major << 5) | 25, value >> 8, value & 0xff]);
  return Buffer.from([(major << 5) | 26, value >>> 24, (value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff]);
}

function cbor(value) {
  if (typeof value === "number") return cborHead(value >= 0 ? 0 : 1, value >= 0 ? value : -1 - value);
  if (typeof value === "string") { const bytes = Buffer.from(value); return Buffer.concat([cborHead(3, bytes.length), bytes]); }
  if (Buffer.isBuffer(value)) return Buffer.concat([cborHead(2, value.length), value]);
  if (Array.isArray(value)) return Buffer.concat([cborHead(4, value.length), ...value.map(cbor)]);
  if (value instanceof Map) {
    return Buffer.concat([cborHead(5, value.size), ...[...value].flatMap(([key, item]) => [cbor(key), cbor(item)])]);
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    return Buffer.concat([cborHead(5, entries.length), ...entries.flatMap(([key, item]) => [cbor(key), cbor(item)])]);
  }
  throw new TypeError("unsupported synthetic WebAuthn value");
}

export function virtualPasskey() {
  const pair = generateKeyPairSync("ec", { namedCurve: "prime256v1" });
  return { credentialId: randomBytes(32).toString("base64url"), publicKey: pair.publicKey, signingHandle: pair.privateKey, counter: 0 };
}

export function registrationResponse(passkey, challenge, origin) {
  const jwk = passkey.publicKey.export({ format: "jwk" });
  const credentialId = Buffer.from(passkey.credentialId, "base64url");
  const coseKey = cbor(new Map([[1, 2], [3, -7], [-1, 1], [-2, Buffer.from(jwk.x, "base64url")], [-3, Buffer.from(jwk.y, "base64url")]]));
  const rpIdHash = createHash("sha256").update(new URL(origin).hostname).digest();
  const idLength = Buffer.alloc(2); idLength.writeUInt16BE(credentialId.length);
  const authData = Buffer.concat([rpIdHash, Buffer.from([0x45]), Buffer.alloc(4), Buffer.alloc(16), idLength, credentialId, coseKey]);
  return {
    id: passkey.credentialId, rawId: passkey.credentialId, type: "public-key", clientExtensionResults: {},
    response: {
      clientDataJSON: b64url(JSON.stringify({ type: "webauthn.create", challenge, origin, crossOrigin: false })),
      attestationObject: b64url(cbor({ fmt: "none", attStmt: {}, authData })), transports: ["internal"],
    },
  };
}

export function authenticationResponse(passkey, challenge, origin) {
  passkey.counter += 1;
  const authData = Buffer.concat([
    createHash("sha256").update(new URL(origin).hostname).digest(),
    Buffer.from([0x05, 0, 0, 0, passkey.counter & 0xff]),
  ]);
  const clientDataJSON = Buffer.from(JSON.stringify({ type: "webauthn.get", challenge, origin, crossOrigin: false }));
  const signedData = Buffer.concat([authData, createHash("sha256").update(clientDataJSON).digest()]);
  return {
    id: passkey.credentialId, rawId: passkey.credentialId, type: "public-key", clientExtensionResults: {},
    response: { clientDataJSON: b64url(clientDataJSON), authenticatorData: b64url(authData), signature: b64url(sign("sha256", signedData, passkey.signingHandle)) },
  };
}
