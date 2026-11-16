import { redirect } from 'next/navigation'
import { AuthForm } from '@/components/auth-form'
import { hasAnyAdmin } from '@/lib/admin-auth'

export default async function SetupPage() {
  if (await hasAnyAdmin()) redirect('/login')
  return <AuthForm mode="setup" />
}
