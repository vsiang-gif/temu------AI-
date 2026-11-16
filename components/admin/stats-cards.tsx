const items = [
  { key: 'total', label: '卡密总数' },
  { key: 'unused', label: '未激活' },
  { key: 'online', label: '10 分钟内在线' },
  { key: 'disabled', label: '已停用' },
] as const

export function StatsCards(props: { total: number; unused: number; online: number; disabled: number }) {
  return (
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {items.map((item) => (
        <div key={item.key} className="flex flex-col gap-1 rounded-xl border bg-background p-4">
          <dt className="text-sm text-muted-foreground">{item.label}</dt>
          <dd className="text-2xl font-semibold tabular-nums">{props[item.key]}</dd>
        </div>
      ))}
    </dl>
  )
}
