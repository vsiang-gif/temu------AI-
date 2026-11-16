import Link from 'next/link'
import { KeyRound, LogOut } from 'lucide-react'
import { logout } from '@/app/actions/auth'
import { Button } from '@/components/ui/button'
import { AdminNav } from './admin-nav'

export function AdminHeader({ username }: { username: string }) {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4 md:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="flex size-7 items-center justify-center rounded-md bg-foreground text-background">
            <KeyRound className="size-4" aria-hidden="true" />
          </span>
          <span className="hidden sm:inline">POD 抠图授权后台</span>
        </Link>
        <AdminNav />
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-sm text-muted-foreground sm:inline">{username}</span>
          <form action={logout}>
            <Button type="submit" variant="ghost" size="sm">
              <LogOut aria-hidden="true" />
              退出
            </Button>
          </form>
        </div>
      </div>
    </header>
  )
}
