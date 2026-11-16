import { AdminHeader } from '@/components/admin/admin-header'
import { requireAdmin } from '@/lib/admin-auth'

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const admin = await requireAdmin()
  return (
    <div className="flex min-h-svh flex-col">
      <AdminHeader username={admin.username} />
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-4 py-6 md:px-6">{children}</main>
    </div>
  )
}
