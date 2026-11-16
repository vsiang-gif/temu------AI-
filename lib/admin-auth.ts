import 'server-only'
import { and, count, eq, gt } from 'drizzle-orm'
import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { randomToken, sha256 } from './crypto'
import { db } from './db'
import { admins, adminSessions } from './db/schema'

const COOKIE_NAME = 'pod_admin_session'
const SESSION_DAYS = 7

export async function hasAnyAdmin() {
  const [row] = await db.select({ value: count() }).from(admins)
  return row.value > 0
}

export async function createAdminSession(adminId: number) {
  const token = randomToken()
  const expiresAt = new Date(Date.now() + SESSION_DAYS * 86400_000)
  await db.insert(adminSessions).values({ tokenHash: sha256(token), adminId, expiresAt })
  const isDev = process.env.NODE_ENV === 'development'
  ;(await cookies()).set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: true,
    // The v0 preview renders inside a cross-site iframe, which drops SameSite=Lax cookies.
    sameSite: isDev ? 'none' : 'lax',
    path: '/',
    expires: expiresAt,
  })
}

export async function destroyAdminSession() {
  const store = await cookies()
  const token = store.get(COOKIE_NAME)?.value
  if (token) await db.delete(adminSessions).where(eq(adminSessions.tokenHash, sha256(token)))
  store.delete(COOKIE_NAME)
}

export async function getAdmin() {
  const token = (await cookies()).get(COOKIE_NAME)?.value
  if (!token) return null
  const rows = await db
    .select({ id: admins.id, username: admins.username })
    .from(adminSessions)
    .innerJoin(admins, eq(admins.id, adminSessions.adminId))
    .where(and(eq(adminSessions.tokenHash, sha256(token)), gt(adminSessions.expiresAt, new Date())))
    .limit(1)
  return rows[0] ?? null
}

export async function requireAdmin() {
  const admin = await getAdmin()
  if (!admin) redirect('/login')
  return admin
}
