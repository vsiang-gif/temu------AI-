'use server'

import { eq, inArray } from 'drizzle-orm'
import { revalidatePath } from 'next/cache'
import { requireAdmin } from '@/lib/admin-auth'
import { generateLicenseCode } from '@/lib/crypto'
import { db } from '@/lib/db'
import { clientSessions, devices, licenseKeys, usageLogs } from '@/lib/db/schema'

function optionalPositiveInt(value: FormDataEntryValue | null) {
  const n = Number(value)
  return Number.isInteger(n) && n > 0 ? n : null
}

export type GenerateState = { error?: string; codes?: string[] } | undefined

export async function generateLicenses(_: GenerateState, formData: FormData): Promise<GenerateState> {
  await requireAdmin()
  const amount = Number(formData.get('amount'))
  if (!Number.isInteger(amount) || amount < 1 || amount > 500) return { error: '生成数量需为 1-500' }
  const maxDevices = optionalPositiveInt(formData.get('maxDevices'))
  if (!maxDevices || maxDevices > 20) return { error: '每卡设备数需为 1-20' }

  const durationRaw = String(formData.get('durationDays') ?? '')
  const durationDays = durationRaw === 'forever' ? null : optionalPositiveInt(durationRaw)
  if (durationRaw !== 'forever' && !durationDays) return { error: '请填写有效的使用天数' }

  const note = String(formData.get('note') ?? '').trim().slice(0, 100)
  const geminiEnabled = formData.get('geminiEnabled') === 'on'
  const geminiDailyLimit = optionalPositiveInt(formData.get('geminiDailyLimit'))

  const codes = Array.from({ length: amount }, generateLicenseCode)
  await db
    .insert(licenseKeys)
    .values(codes.map((code) => ({ code, note, durationDays, maxDevices, geminiEnabled, geminiDailyLimit })))
  revalidatePath('/')
  return { codes }
}

async function endSessions(licenseIds: number[]) {
  await db.delete(clientSessions).where(inArray(clientSessions.licenseId, licenseIds))
}

export async function setLicenseStatus(id: number, status: 'active' | 'disabled') {
  await requireAdmin()
  await db.update(licenseKeys).set({ status }).where(eq(licenseKeys.id, id))
  if (status === 'disabled') await endSessions([id])
  revalidatePath('/')
}

export async function setLicenseExpiry(id: number, expiresAt: string | null) {
  await requireAdmin()
  let date: Date | null = null
  if (expiresAt) {
    date = new Date(expiresAt)
    if (Number.isNaN(date.getTime())) throw new Error('时间格式错误')
  }
  await db.update(licenseKeys).set({ expiresAt: date }).where(eq(licenseKeys.id, id))
  revalidatePath('/')
}

export async function extendLicense(id: number, days: number) {
  await requireAdmin()
  if (!Number.isInteger(days) || days === 0 || Math.abs(days) > 3650) throw new Error('天数无效')
  const [license] = await db.select().from(licenseKeys).where(eq(licenseKeys.id, id)).limit(1)
  if (!license) return

  if (!license.activatedAt && !license.expiresAt) {
    const base = license.durationDays ?? 0
    await db.update(licenseKeys).set({ durationDays: Math.max(1, base + days) }).where(eq(licenseKeys.id, id))
  } else {
    const base = Math.max(license.expiresAt?.getTime() ?? Date.now(), days > 0 ? Date.now() : 0)
    await db
      .update(licenseKeys)
      .set({ expiresAt: new Date(base + days * 86400_000) })
      .where(eq(licenseKeys.id, id))
  }
  revalidatePath('/')
}

export async function updateLicense(
  id: number,
  input: { note: string; maxDevices: number; geminiEnabled: boolean; geminiDailyLimit: number | null },
) {
  await requireAdmin()
  if (!Number.isInteger(input.maxDevices) || input.maxDevices < 1 || input.maxDevices > 20) {
    throw new Error('设备数需为 1-20')
  }
  await db
    .update(licenseKeys)
    .set({
      note: input.note.trim().slice(0, 100),
      maxDevices: input.maxDevices,
      geminiEnabled: input.geminiEnabled,
      geminiDailyLimit: input.geminiDailyLimit && input.geminiDailyLimit > 0 ? input.geminiDailyLimit : null,
    })
    .where(eq(licenseKeys.id, id))
  revalidatePath('/')
}

export async function unbindDevice(licenseId: number, deviceId: number) {
  await requireAdmin()
  await db.delete(clientSessions).where(eq(clientSessions.deviceId, deviceId))
  await db.delete(devices).where(eq(devices.id, deviceId))
  revalidatePath('/')
  return getLicenseDevices(licenseId)
}

export async function kickLicense(id: number) {
  await requireAdmin()
  await endSessions([id])
  revalidatePath('/')
}

export async function deleteLicense(id: number) {
  await requireAdmin()
  await endSessions([id])
  await db.delete(devices).where(eq(devices.licenseId, id))
  await db.delete(usageLogs).where(eq(usageLogs.licenseId, id))
  await db.delete(licenseKeys).where(eq(licenseKeys.id, id))
  revalidatePath('/')
}

export async function getLicenseDevices(licenseId: number) {
  await requireAdmin()
  return db.select().from(devices).where(eq(devices.licenseId, licenseId))
}
