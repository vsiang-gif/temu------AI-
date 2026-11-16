'use server'

import { revalidatePath } from 'next/cache'
import { requireAdmin } from '@/lib/admin-auth'
import { db } from '@/lib/db'
import { clientSessions } from '@/lib/db/schema'
import { DEFAULT_GEMINI_MODEL, setSetting } from '@/lib/settings'

export type SettingsState = { error?: string; saved?: boolean } | undefined

export async function saveSettings(_: SettingsState, formData: FormData): Promise<SettingsState> {
  await requireAdmin()
  const loginEnabled = formData.get('loginEnabled') === 'on'
  const notice = String(formData.get('notice') ?? '').slice(0, 500)
  const geminiModel = String(formData.get('geminiModel') ?? '').trim() || DEFAULT_GEMINI_MODEL
  const latestVersion = String(formData.get('latestVersion') ?? '').trim().slice(0, 32)
  if (!/^[a-zA-Z0-9.\-_]+$/.test(geminiModel)) return { error: '模型名称格式不正确' }

  await setSetting('login_enabled', loginEnabled ? 'true' : 'false')
  await setSetting('notice', notice)
  await setSetting('gemini_model', geminiModel)
  await setSetting('latest_version', latestVersion)
  if (!loginEnabled) await db.delete(clientSessions)
  revalidatePath('/', 'layout')
  return { saved: true }
}
