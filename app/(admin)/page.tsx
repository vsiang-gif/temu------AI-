import { and, count, desc, eq, gt, ilike, isNotNull, isNull, lte, or, sql, type SQL } from 'drizzle-orm'
import { GenerateDialog } from '@/components/admin/generate-dialog'
import { LicenseFilters } from '@/components/admin/license-filters'
import { LicenseTable, type LicenseRow } from '@/components/admin/license-table'
import { StatsCards } from '@/components/admin/stats-cards'
import { db } from '@/lib/db'
import { devices, licenseKeys } from '@/lib/db/schema'

const ONLINE_WINDOW = sql`now() - interval '10 minutes'`

function statusFilter(status: string): SQL | undefined {
  const notExpired = or(isNull(licenseKeys.expiresAt), gt(licenseKeys.expiresAt, sql`now()`))
  switch (status) {
    case 'unused':
      return and(eq(licenseKeys.status, 'active'), isNull(licenseKeys.activatedAt))
    case 'active':
      return and(eq(licenseKeys.status, 'active'), isNotNull(licenseKeys.activatedAt), notExpired)
    case 'expired':
      return and(eq(licenseKeys.status, 'active'), lte(licenseKeys.expiresAt, sql`now()`))
    case 'disabled':
      return eq(licenseKeys.status, 'disabled')
    default:
      return undefined
  }
}

export default async function LicensesPage({ searchParams }: { searchParams: Promise<{ q?: string; status?: string }> }) {
  const { q = '', status = 'all' } = await searchParams
  const search = q.trim()
  const where = and(
    statusFilter(status),
    search ? or(ilike(licenseKeys.code, `%${search}%`), ilike(licenseKeys.note, `%${search}%`)) : undefined,
  )

  const deviceCounts = db
    .select({ licenseId: devices.licenseId, total: count().as('total') })
    .from(devices)
    .groupBy(devices.licenseId)
    .as('device_counts')

  const [rows, [stats]] = await Promise.all([
    db
      .select({
        license: licenseKeys,
        deviceCount: sql<number>`coalesce(${deviceCounts.total}, 0)`.mapWith(Number),
      })
      .from(licenseKeys)
      .leftJoin(deviceCounts, eq(deviceCounts.licenseId, licenseKeys.id))
      .where(where)
      .orderBy(desc(licenseKeys.createdAt))
      .limit(500),
    db
      .select({
        total: count(),
        unused: sql<number>`count(*) filter (where ${licenseKeys.activatedAt} is null and ${licenseKeys.status} = 'active')`.mapWith(Number),
        disabled: sql<number>`count(*) filter (where ${licenseKeys.status} = 'disabled')`.mapWith(Number),
        online: sql<number>`count(*) filter (where ${licenseKeys.lastSeenAt} > ${ONLINE_WINDOW} and ${licenseKeys.status} = 'active')`.mapWith(Number),
      })
      .from(licenseKeys),
  ])

  const data: LicenseRow[] = rows.map(({ license, deviceCount }) => ({
    id: license.id,
    code: license.code,
    note: license.note,
    status: license.status,
    durationDays: license.durationDays,
    maxDevices: license.maxDevices,
    deviceCount,
    geminiEnabled: license.geminiEnabled,
    geminiDailyLimit: license.geminiDailyLimit,
    activatedAt: license.activatedAt?.toISOString() ?? null,
    expiresAt: license.expiresAt?.toISOString() ?? null,
    lastSeenAt: license.lastSeenAt?.toISOString() ?? null,
    createdAt: license.createdAt.toISOString(),
  }))

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">卡密管理</h1>
          <p className="text-sm text-muted-foreground">生成卡密、控制使用时间、随时停用或踢下线</p>
        </div>
        <GenerateDialog />
      </div>
      <StatsCards total={stats.total} unused={stats.unused} online={stats.online} disabled={stats.disabled} />
      <LicenseFilters q={search} status={status} />
      <LicenseTable rows={data} />
    </>
  )
}
