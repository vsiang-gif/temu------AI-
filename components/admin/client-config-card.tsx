'use client'

import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={async () => {
            await navigator.clipboard.writeText(value)
            toast.success(`已复制${label}`)
          }}
        >
          <Copy aria-hidden="true" />
          复制
        </Button>
      </div>
      <code className="break-all rounded-md bg-muted px-3 py-2 font-mono text-xs">{value}</code>
    </div>
  )
}

export function ClientConfigCard({ serverUrl, publicKey }: { serverUrl: string; publicKey: string }) {
  return (
    <div className="flex flex-col gap-5 rounded-xl border bg-background p-6">
      <div className="flex flex-col gap-1">
        <h2 className="font-semibold">软件端配置</h2>
        <p className="text-sm text-muted-foreground text-pretty">
          打包 EXE 前，把下面两项填入 <code className="font-mono">desktop/app/config.py</code>。公钥用于校验服务器签名，防止有人伪造授权服务器。
        </p>
      </div>
      <Field label="服务器地址" value={serverUrl} />
      <Field label="验签公钥" value={publicKey} />
      <p className="text-xs text-muted-foreground text-pretty">
        提示：正式使用请先点击右上角 Publish 发布，服务器地址会变成固定的正式域名。
      </p>
    </div>
  )
}
