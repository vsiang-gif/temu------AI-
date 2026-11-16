import 'server-only'
import {
  createHash,
  createPrivateKey,
  createPublicKey,
  generateKeyPairSync,
  randomBytes,
  randomInt,
  scryptSync,
  sign,
  timingSafeEqual,
} from 'node:crypto'
import { getSetting, setSetting } from './settings'

export function sha256(value: string) {
  return createHash('sha256').update(value).digest('hex')
}

export function randomToken() {
  return randomBytes(32).toString('base64url')
}

export function hashPassword(password: string) {
  const salt = randomBytes(16)
  const hash = scryptSync(password, salt, 64)
  return `scrypt$${salt.toString('base64')}$${hash.toString('base64')}`
}

export function verifyPassword(password: string, stored: string) {
  const [scheme, saltB64, hashB64] = stored.split('$')
  if (scheme !== 'scrypt' || !saltB64 || !hashB64) return false
  const expected = Buffer.from(hashB64, 'base64')
  const actual = scryptSync(password, Buffer.from(saltB64, 'base64'), expected.length)
  return timingSafeEqual(expected, actual)
}

const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

export function generateLicenseCode() {
  const groups = Array.from({ length: 4 }, () =>
    Array.from({ length: 5 }, () => CODE_ALPHABET[randomInt(CODE_ALPHABET.length)]).join(''),
  )
  return `POD-${groups.join('-')}`
}

async function getSigningKey() {
  const existing = await getSetting('signing_private_key')
  if (existing) return createPrivateKey({ key: Buffer.from(existing, 'base64'), format: 'der', type: 'pkcs8' })

  const { privateKey } = generateKeyPairSync('ed25519')
  const der = privateKey.export({ format: 'der', type: 'pkcs8' })
  await setSetting('signing_private_key', der.toString('base64'), { onlyIfMissing: true })
  const stored = await getSetting('signing_private_key')
  return createPrivateKey({ key: Buffer.from(stored!, 'base64'), format: 'der', type: 'pkcs8' })
}

/** 32-byte raw Ed25519 public key, base64. Embed this in the desktop client. */
export async function getPublicKeyBase64() {
  const privateKey = await getSigningKey()
  const spki = createPublicKey(privateKey).export({ format: 'der', type: 'spki' })
  return spki.subarray(spki.length - 32).toString('base64')
}

/**
 * The client verifies `signature` over the exact `payload` string, then parses it.
 * Signing the serialized string avoids JSON canonicalization differences between languages.
 */
export async function signPayload(data: Record<string, unknown>) {
  const payload = JSON.stringify(data)
  const signature = sign(null, Buffer.from(payload, 'utf8'), await getSigningKey())
  return { payload, signature: signature.toString('base64') }
}
