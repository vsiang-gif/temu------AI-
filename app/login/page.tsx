import { redirect } from 'next/navigation'
import { AuthForm } from '@/components/auth-form'
import { getAdmin, hasAnyAdmin } from '@/lib/admin-auth'

export default async function LoginPage() {
  if (!(await hasAnyAdmin())) redirect('/setup')
  if (await getAdmin()) redirect('/')
  return <AuthForm mode="login" />
}
