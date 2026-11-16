import 'server-only'
import { and, count, eq, gt, gte, sql } from 'drizzle-orm'
import { randomToken, sha256, signPayload } from './crypto'
import { db } from './db'
import { clientSessions, devices, licenseKeys, usageLogs, type LicenseKey } from './db/schema'
import { getPublicSettings } from './settings'

const CLIENT_SESSION_HOURS = 12
export const HEARTBEAT_SECONDS = 300

export class LicenseError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

export function clientIp(req: Request) {
  return req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? ''
}

function assertUsable(license: LicenseKey | undefined, loginEnabled: boolean): asserts license is LicenseKey {
  if (!loginEnabled) throw new LicenseError('service_closed', '软件已暂停使用，请联系管理员')
  if (!license) throw new LicenseError('invalid_code', '卡密不存在')
  if (license.status !== 'active') throw new LicenseError('disabled', '卡密已被停用')
  if (license.expiresAt && license.expiresAt.getTime() <= Date.now()) {
    throw new LicenseError('expired', '卡密已过期')
  }
}

async function buildStatus(license: LicenseKey, nonce: string, extra: Record<string, unknown> = {}) {
  const settings = await getPublicSettings()
  return signPayload({
    ok: true,
    nonce,
    server_time: Date.now(),
    license_id: license.id,
    expires_at: license.expiresAt?.getTime() ?? null,
    gemini_enabled: license.geminiEnabled,
    heartbeat_seconds: HEARTBEAT_SECONDS,
    notice: settings.notice,
    latest_version: settings.latestVersion,
    ...extra,
  })
}

export async function activate(input: {
  code: string
  machineId: string
  machineName: string
  nonce: string
  ip: string
}) {
  const { loginEnabled } = await getPublicSettings()
  const [found] = await db.select().from(licenseKeys).where(eq(licenseKeys.code, input.code)).limit(1)
  assertUsable(found, loginEnabled)
  let license = found

  if (!license.activatedAt) {
    const now = new Date()
    const expiresAt =
      license.expiresAt ?? (license.durationDays ? new Date(now.getTime() + license.durationDays * 86400_000) : null)
    ;[license] = await db
      .update(licenseKeys)
      .set({ activatedAt: now, expiresAt })
      .where(eq(licenseKeys.id, license.id))
      .returning()
  }

  let [device] = await db
    .select()
    .from(devices)
    .where(and(eq(devices.licenseId, license.id), eq(devices.machineId, input.machineId)))
    .limit(1)

  if (!device) {
    const [{ value: bound }] = await db
      .select({ value: count() })
      .from(devices)
      .where(eq(devices.licenseId, license.id))
    if (bound >= license.maxDevices) {
      throw new LicenseError('device_limit', `该卡密已绑定 ${bound} 台电脑，已达上限`)
    }
    ;[device] = await db
      .insert(devices)
      .values({ licenseId: license.id, machineId: input.machineId, machineName: input.machineName, lastIp: input.ip })
      .returning()
  } else {
    await db
      .update(devices)
      .set({ lastSeenAt: new Date(), lastIp: input.ip, machineName: input.machineName })
      .where(eq(devices.id, device.id))
  }

  const token = randomToken()
  await db.insert(clientSessions).values({
    tokenHash: sha256(token),
    licenseId: license.id,
    deviceId: device.id,
    expiresAt: new Date(Date.now() + CLIENT_SESSION_HOURS * 3600_000),
  })
  await db.update(licenseKeys).set({ lastSeenAt: new Date() }).where(eq(licenseKeys.id, license.id))
  await db.insert(usageLogs).values({ licenseId: license.id, kind: 'login', detail: `${input.machineName} ${input.ip}` })

  return buildStatus(license, input.nonce, { token })
}

export async function authenticateSession(token: string, machineId: string) {
  const rows = await db
    .select({ license: licenseKeys, device: devices })
    .from(clientSessions)
    .innerJoin(licenseKeys, eq(licenseKeys.id, clientSessions.licenseId))
    .innerJoin(devices, eq(devices.id, clientSessions.deviceId))
    .where(and(eq(clientSessions.tokenHash, sha256(token)), gt(clientSessions.expiresAt, new Date())))
    .limit(1)
  const row = rows[0]
  if (!row || row.device.machineId !== machineId) {
    throw new LicenseError('session_invalid', '登录已失效，请重新登录')
  }
  const { loginEnabled } = await getPublicSettings()
  assertUsable(row.license, loginEnabled)
  return row
}

export async function heartbeat(input: { token: string; machineId: string; nonce: string; ip: string }) {
  const { license, device } = await authenticateSession(input.token, input.machineId)
  const now = new Date()
  await db.update(devices).set({ lastSeenAt: now, lastIp: input.ip }).where(eq(devices.id, device.id))
  await db.update(licenseKeys).set({ lastSeenAt: now }).where(eq(licenseKeys.id, license.id))
  return buildStatus(license, input.nonce)
}

export async function assertGeminiQuota(license: LicenseKey) {
  if (!license.geminiEnabled) throw new LicenseError('gemini_disabled', '该卡密未开通 Google AI 抠图')
  if (license.geminiDailyLimit == null) return
  const startOfDay = sql`date_trunc('day', now())`
  const [{ value: used }] = await db
    .select({ value: count() })
    .from(usageLogs)
    .where(and(eq(usageLogs.licenseId, license.id), eq(usageLogs.kind, 'gemini'), gte(usageLogs.createdAt, startOfDay)))
  if (used >= license.geminiDailyLimit) {
    throw new LicenseError('gemini_quota', `今日 Google AI 次数已用完（${license.geminiDailyLimit} 次）`)
  }
}

export async function signedError(error: unknown, nonce: string) {
  const known = error instanceof LicenseError
  if (!known) console.error('[license] unexpected error', error)
  const body = await signPayload({
    ok: false,
    nonce,
    server_time: Date.now(),
    error: known ? error.code : 'server_error',
    message: known ? error.message : '服务器错误，请稍后重试',
  })
  return Response.json(body, { status: known ? 403 : 500 })
}
