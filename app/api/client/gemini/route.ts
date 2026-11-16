import { db } from '@/lib/db'
import { usageLogs } from '@/lib/db/schema'
import { assertGeminiQuota, authenticateSession, LicenseError, signedError } from '@/lib/license'
import { getPublicSettings } from '@/lib/settings'

export const maxDuration = 120

const MAX_IMAGE_BASE64 = 3_000_000
const ALLOWED_MIME = new Set(['image/jpeg', 'image/png', 'image/webp'])

const HEX_COLOR = /^#[0-9A-F]{6}$/i

function buildPrompt(background: string, shirt: string, colors: string[]) {
  return [
    `This is a product photo of a ${shirt} T-shirt (it may be worn by a model, laid flat, or a mockup).`,
    'Extract ONLY the printed graphic/artwork on the shirt and output it as a flat, front-facing, print-ready design.',
    'Remove the shirt fabric, wrinkles, folds, shadows, perspective distortion, the model, and the background.',
    'Keep every element of the original print exactly: the same text and spelling, fonts, line shapes, layout and proportions.',
    'COLOR ACCURACY IS CRITICAL: reproduce the exact original ink colors of the print. Do not change hue, do not add saturation, do not recolor.',
    'Gray, white, black and other neutral inks must stay perfectly neutral (no green, pink or other tint).',
    ...(colors.length ? [`The print's measured ink colors are approximately: ${colors.join(', ')}. Use these colors.`] : []),
    'Do NOT add, invent, redraw, stylize, or omit any element.',
    `Place the design centered on a perfectly flat, solid ${background} background with no gradient, no texture, no shadow and no border.`,
    'The background color is only a removable keying color: it must NOT tint, reflect on, or blend into any part of the design.',
    'Output a single image.',
  ].join(' ')
}

const SUPPORTED_RATIOS = new Set(['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9'])

function buildMaskPrompt(shirt: string) {
  return [
    `This is a product photo of a ${shirt} T-shirt with a printed graphic.`,
    'Generate a black-and-white segmentation MASK of the printed graphic only. Do NOT output the design itself.',
    'The mask must have exactly the same framing, aspect ratio and composition as the input photo:',
    'do not crop, zoom, shift, rotate, flatten, straighten or redraw anything.',
    'Every white pixel must sit exactly on top of the corresponding print pixel in the input photo.',
    'Paint every pixel that belongs to the printed artwork pure white #FFFFFF, including all text, letters,',
    'punctuation, small dots, thin lines and the distressed/vintage texture of the print.',
    'Paint everything else pure black #000000: the shirt fabric (including fabric showing through gaps and',
    "holes in the print), wrinkles, folds, shadows, collar, neck labels and tags, the model's skin and hair, and the background.",
    'Use only pure black and pure white. No gray, no colors, no text, no border, no added or missing elements.',
    'Output a single image.',
  ].join(' ')
}

const KEY_COLORS: Record<string, string> = { magenta: '#FF00FF', green: '#00FF00', blue: '#0000FF' }

function buildCutoutPrompt(shirt: string, key: string, strict: boolean) {
  const hex = KEY_COLORS[key] ?? KEY_COLORS.magenta
  const name = KEY_COLORS[key] ? key : 'magenta'
  const parts = [
    'Context: we are a Temu print-on-demand seller of plain black and white T-shirts.',
    'We need ONLY the printed artwork from this photo, so we can print it again onto blank T-shirts in our factory.',
    'The T-shirt itself is the blank garment and is NOT part of the artwork.',
    `This is a product photo of a ${shirt} T-shirt with a printed graphic on the chest.`,
    'Task: extract only the complete printed graphic (every part of the design: all text, lines, details).',
    'Strictly keep the original pixel colors, grayscale and vintage/distressed texture of the print;',
    'no AI redrawing, no color shift, no hue adjustment, no filter enhancement.',
    `Paint EVERYTHING that is not the print with flat solid pure ${name} (${hex}), including:`,
    'the whole T-shirt body, sleeves, collar, neckline, seams, hem, wrinkles, folds and shadows;',
    'the plain fabric between and around the design and fabric showing through gaps inside it;',
    'neck labels, tags, hangers, mannequins, models, hands, props and the entire background.',
    `The shirt outline must NOT appear: the result must not look like a T-shirt on a ${name} background,`,
    'it must look like only the artwork floating on a flat key color.',
    'No gradient, no checkerboard, no texture, no shadow, no border.',
    'Keep exactly the same framing, aspect ratio, position and size as the input photo:',
    'do not crop, zoom, shift, rotate, flatten, center or redraw anything.',
    'Output a single image.',
  ]
  if (strict) {
    parts.unshift('IMPORTANT: a previous attempt wrongly kept the whole T-shirt. Remove the entire shirt this time; keep only the print.')
  }
  return parts.join(' ')
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null)
  const nonce = typeof body?.nonce === 'string' ? body.nonce.slice(0, 64) : ''
  const token = typeof body?.token === 'string' ? body.token : ''
  const machineId = typeof body?.machine_id === 'string' ? body.machine_id : ''
  const image = typeof body?.image_base64 === 'string' ? body.image_base64 : ''
  const mime = typeof body?.mime === 'string' ? body.mime : 'image/jpeg'
  const background = body?.background === 'magenta' ? 'pure magenta (#FF00FF)' : 'pure green (#00FF00)'
  const shirt = body?.shirt === 'white' ? 'white' : body?.shirt === 'black' ? 'black' : ''
  const fileName = typeof body?.file_name === 'string' ? body.file_name.slice(0, 200) : ''
  const colors: string[] = Array.isArray(body?.colors)
    ? body.colors.filter((c: unknown): c is string => typeof c === 'string' && HEX_COLOR.test(c)).slice(0, 6)
    : []
  const isMask = body?.mode === 'mask' || body?.mode === 'cutout'
  const aspect = typeof body?.aspect === 'string' ? body.aspect : ''
  const key = typeof body?.key === 'string' ? body.key : 'magenta'
  const prompt =
    body?.mode === 'cutout'
      ? buildCutoutPrompt(shirt || 'black or white', key, body?.strict === true)
      : body?.mode === 'mask'
        ? buildMaskPrompt(shirt || 'black or white')
        : buildPrompt(background, shirt || 'black or white', colors)

  if (!nonce || !token || !machineId || !image) {
    return Response.json({ ok: false, error: 'bad_request', message: '请求参数不完整' }, { status: 400 })
  }
  if (image.length > MAX_IMAGE_BASE64 || !ALLOWED_MIME.has(mime)) {
    return Response.json({ ok: false, error: 'bad_image', message: '图片过大或格式不支持' }, { status: 400 })
  }

  try {
    const { license } = await authenticateSession(token, machineId)
    await assertGeminiQuota(license)

    const apiKey = process.env.GEMINI_API_KEY
    if (!apiKey) throw new LicenseError('gemini_not_configured', '管理员尚未配置 Google AI 密钥')

    const { geminiModel } = await getPublicSettings()
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(geminiModel)}:generateContent`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }, { inline_data: { mime_type: mime, data: image } }] }],
          generationConfig: {
            responseModalities: ['IMAGE'],
            ...(isMask && SUPPORTED_RATIOS.has(aspect) && geminiModel.includes('image')
              ? { imageConfig: { aspectRatio: aspect } }
              : {}),
          },
        }),
      },
    )

    if (!res.ok) {
      console.error('[gemini] upstream error', res.status, (await res.text()).slice(0, 500))
      throw new LicenseError('gemini_upstream', `Google AI 调用失败（${res.status}）`)
    }

    const data = await res.json()
    const parts: Array<{ inlineData?: { mimeType: string; data: string } }> = data?.candidates?.[0]?.content?.parts ?? []
    const out = parts.find((p) => p.inlineData?.data)?.inlineData
    if (!out) throw new LicenseError('gemini_empty', 'Google AI 未返回图片，请重试或改用本地模型')

    await db.insert(usageLogs).values({ licenseId: license.id, kind: 'gemini', detail: fileName })

    return Response.json({ ok: true, nonce, mime: out.mimeType, image_base64: out.data })
  } catch (error) {
    return signedError(error, nonce)
  }
}
