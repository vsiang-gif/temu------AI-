'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const statuses = [
  { value: 'all', label: '全部' },
  { value: 'unused', label: '未激活' },
  { value: 'active', label: '使用中' },
  { value: 'expired', label: '已过期' },
  { value: 'disabled', label: '已停用' },
]

export function LicenseFilters({ q, status }: { q: string; status: string }) {
  const router = useRouter()
  const [query, setQuery] = useState(q)
  const [pending, startTransition] = useTransition()

  function navigate(next: { q?: string; status?: string }) {
    const params = new URLSearchParams()
    const nq = next.q ?? query
    const ns = next.status ?? status
    if (nq) params.set('q', nq)
    if (ns !== 'all') params.set('status', ns)
    startTransition(() => router.replace(params.size ? `/?${params}` : '/'))
  }

  return (
    <div className={cn('flex flex-wrap items-center gap-3', pending && 'opacity-70')}>
      <form
        className="relative w-full sm:w-72"
        onSubmit={(e) => {
          e.preventDefault()
          navigate({ q: query.trim() })
        }}
      >
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索卡密或备注，回车确认"
          aria-label="搜索卡密或备注"
          className="pl-8 bg-background"
        />
      </form>
      <div role="group" aria-label="按状态筛选" className="flex flex-wrap gap-1 rounded-lg border bg-background p-1">
        {statuses.map((s) => (
          <button
            key={s.value}
            type="button"
            aria-pressed={status === s.value}
            onClick={() => navigate({ status: s.value })}
            className={cn(
              'rounded-md px-3 py-1 text-sm transition-colors',
              status === s.value ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  )
}
