import { activate, clientIp, signedError } from '@/lib/license'

export async function POST(req: Request) {
  const body = await req.json().catch(() => null)
  const nonce = typeof body?.nonce === 'string' ? body.nonce.slice(0, 64) : ''
  const code = typeof body?.code === 'string' ? body.code.trim().toUpperCase() : ''
  const machineId = typeof body?.machine_id === 'string' ? body.machine_id.slice(0, 128) : ''
  const machineName = typeof body?.machine_name === 'string' ? body.machine_name.slice(0, 100) : ''

  if (!nonce || !code || machineId.length < 16) {
    return Response.json({ ok: false, error: 'bad_request', message: '请求参数不完整' }, { status: 400 })
  }

  try {
    return Response.json(await activate({ code, machineId, machineName, nonce, ip: clientIp(req) }))
  } catch (error) {
    return signedError(error, nonce)
  }
}
