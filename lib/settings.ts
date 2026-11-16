import 'server-only'
import { eq, sql } from 'drizzle-orm'
import { db } from './db'
import { appSettings } from './db/schema'

export async function getSetting(key: string) {
  const rows = await db.select().from(appSettings).where(eq(appSettings.key, key)).limit(1)
  return rows[0]?.value ?? null
}

export async function setSetting(key: string, value: string, opts: { onlyIfMissing?: boolean } = {}) {
  const insert = db.insert(appSettings).values({ key, value })
  if (opts.onlyIfMissing) {
    await insert.onConflictDoNothing()
  } else {
    await insert.onConflictDoUpdate({ target: appSettings.key, set: { value, updatedAt: sql`now()` } })
  }
}

export const DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash-image'

export type PublicSettings = {
  loginEnabled: boolean
  notice: string
  geminiModel: string
  latestVersion: string
}

export async function getPublicSettings(): Promise<PublicSettings> {
  const rows = await db.select().from(appSettings)
  const map = new Map(rows.map((r) => [r.key, r.value]))
  return {
    loginEnabled: map.get('login_enabled') !== 'false',
    notice: map.get('notice') ?? '',
    geminiModel: map.get('gemini_model') || DEFAULT_GEMINI_MODEL,
    latestVersion: map.get('latest_version') ?? '',
  }
}
