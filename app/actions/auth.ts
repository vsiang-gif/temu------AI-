'use server'

import { eq } from 'drizzle-orm'
import { redirect } from 'next/navigation'
import { createAdminSession, destroyAdminSession, hasAnyAdmin } from '@/lib/admin-auth'
import { hashPassword, verifyPassword } from '@/lib/crypto'
import { db } from '@/lib/db'
import { admins } from '@/lib/db/schema'

export type FormState = { error?: string } | undefined

export async function setupAdmin(_: FormState, formData: FormData): Promise<FormState> {
  if (await hasAnyAdmin()) return { error: '管理员已存在，请直接登录' }
  const username = String(formData.get('username') ?? '').trim()
  const password = String(formData.get('password') ?? '')
  const confirm = String(formData.get('confirm') ?? '')
  if (!/^[a-zA-Z0-9_]{3,32}$/.test(username)) return { error: '用户名需为 3-32 位字母、数字或下划线' }
  if (password.length < 8) return { error: '密码至少 8 位' }
  if (password !== confirm) return { error: '两次输入的密码不一致' }

  const [admin] = await db
    .insert(admins)
    .values({ username, passwordHash: hashPassword(password) })
    .returning({ id: admins.id })
  await createAdminSession(admin.id)
  redirect('/')
}

export async function login(_: FormState, formData: FormData): Promise<FormState> {
  const username = String(formData.get('username') ?? '').trim()
  const password = String(formData.get('password') ?? '')
  const [admin] = await db.select().from(admins).where(eq(admins.username, username)).limit(1)
  if (!admin || !verifyPassword(password, admin.passwordHash)) return { error: '用户名或密码错误' }
  await createAdminSession(admin.id)
  redirect('/')
}

export async function logout() {
  await destroyAdminSession()
  redirect('/login')
}
