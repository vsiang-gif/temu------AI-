import { clientIp, heartbeat, signedError } from '@/lib/license'

export async function POST(req: Request) {
  const body = await req.json().catch(() => null)
  const nonce = typeof body?.nonce === 'string' ? body.nonce.slice(0, 64) : ''
  const token = typeof body?.token === 'string' ? body.token : ''
  const machineId = typeof body?.machine_id === 'string' ? body.machine_id.slice(0, 128) : ''

  if (!nonce || !token || !machineId) {
    return Response.json({ ok: false, error: 'bad_request', message: '请求参数不完整' }, { status: 400 })
  }

  try {
    return Response.json(await heartbeat({ token, machineId, nonce, ip: clientIp(req) }))
  } catch (error) {
    return signedError(error, nonce)
  }
}
