import { headers } from 'next/headers'
import { SettingsForm } from '@/components/admin/settings-form'
import { ClientConfigCard } from '@/components/admin/client-config-card'
import { getPublicKeyBase64 } from '@/lib/crypto'
import { getPublicSettings } from '@/lib/settings'

export default async function SettingsPage() {
  const [settings, publicKey, h] = await Promise.all([getPublicSettings(), getPublicKeyBase64(), headers()])
  const host = h.get('x-forwarded-host') ?? h.get('host') ?? ''
  const proto = h.get('x-forwarded-proto') ?? 'https'
  const serverUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : `${proto}://${host}`

  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">系统设置</h1>
        <p className="text-sm text-muted-foreground">全局开关、软件公告与 Google AI 配置</p>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <SettingsForm settings={settings} geminiConfigured={Boolean(process.env.GEMINI_API_KEY)} />
        <ClientConfigCard serverUrl={serverUrl} publicKey={publicKey} />
      </div>
    </>
  )
}
