"""打包前把后台「系统设置 → 软件端配置」里的两项填到这里。"""

APP_NAME = "Temu POD 印花提取"
APP_VERSION = "1.0.0"

# 卡密登录开关。False = 跳过卡密直接进入软件（开发/自用阶段）；发给别人前改成 True
LICENSE_ENABLED = False

# 免卡密模式下 Google AI 的默认模型和代理（国内一般需要代理，例如 http://127.0.0.1:7890）
GEMINI_MODEL = "gemini-2.5-flash-image"
HTTPS_PROXY = ""

# 授权服务器地址，例如 https://your-project.vercel.app
SERVER_URL = "https://REPLACE-ME.vercel.app"

# 验签公钥（后台系统设置页可复制）
PUBLIC_KEY_B64 = "REPLACE_ME"

# 断网后允许继续使用的时长（秒），超过则锁定
OFFLINE_GRACE_SECONDS = 600

SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
