"""
تنظیمات و مسیرهای برنامه — «وی پی ان شخصی مهراس».

منابع زیر در تاریخ ۲۰۲۶-۱۰-۲۶ با اجرای واقعی از همین شبکه تست شدند؛
منابع ۴۰۴ و مرده‌ی نسخه‌ی قبلی حذف شدند و منابعی که امروز فعال‌اند اضافه شدند.
منابع «تست‌شده» (گره‌هایی که صاحب مخزن خودش تست کرده) اول لیست هستند تا نسبت
موفقیت بالا برود و وقت کاربر تلف نشود.
"""
from pathlib import Path

APP_NAME = "وی پی ان شخصی مهراس"
APP_NAME_EN = "Mehras VPN"
APP_VERSION = "2.0"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SB_DIR = DATA_DIR / "singbox"
LOG_DIR = DATA_DIR / "logs"
FONTS_DIR = BASE_DIR / "fonts"
ASSETS_DIR = BASE_DIR / "assets"

for _p in (DATA_DIR, SB_DIR, LOG_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# --- فایل‌ها ---------------------------------------------------------------
SB_EXE = SB_DIR / "sing-box.exe"
SB_LOG = LOG_DIR / "singbox.log"
LOG_FILE = LOG_DIR / "app.log"

SERVERS_FILE = DATA_DIR / "servers.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
WORKING_CACHE_FILE = DATA_DIR / "working_cache.json"
SOURCE_HEALTH_FILE = DATA_DIR / "source_health.json"
PROXY_BACKUP_FILE = DATA_DIR / "proxy_backup.json"
HISTORY_FILE = DATA_DIR / "history.json"
IR_CIDR_FILE = DATA_DIR / "ir-cidr.txt"
# اشتراک‌ها و لینک‌های شخصی کاربر (اولویت بالاتر از منابع عمومی)
CUSTOM_SOURCES_FILE = DATA_DIR / "custom_sources.json"

# ---------------------------------------------------------------------------
# منابع کانفیگ — تست زنده‌شده در ۲۰۲۶-۱۰-۲۶
# kind: "tested" = گره‌های از پیش تست‌شده، "bulk" = حجم بالا، "raw" = متن ساده
# ---------------------------------------------------------------------------
SOURCES = [
    # --- گره‌های تست‌شده (نسبت موفقیت بسیار بالاتر) ---
    {"url": "https://raw.githubusercontent.com/RichTiTAN/V2rayTested/main/working_configs_general.txt",
     "kind": "tested", "note": "تست‌شده‌ی خود مخزن"},
    {"url": "https://raw.githubusercontent.com/RichTiTAN/V2rayTested/main/working_configs.txt",
     "kind": "tested", "note": "تست‌شده"},
    {"url": "https://raw.githubusercontent.com/RichTiTAN/V2rayTested/main/working_configs_phase6.txt",
     "kind": "tested", "note": "تست‌شده"},
    {"url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/top100.txt",
     "kind": "tested", "note": "۱۰۰ گره‌ی برتر"},
    {"url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/verified/configs.txt",
     "kind": "tested", "note": "تأییدشده"},
    {"url": "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity.txt",
     "kind": "tested", "note": "گزیده‌ی Eternity"},
    {"url": "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt",
     "kind": "tested", "note": "لیست تست‌شده"},
    {"url": "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/super-sub.txt",
     "kind": "tested", "note": "سوپر‌ساب"},
    {"url": "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub1.txt",
     "kind": "tested", "note": "بارفار"},
    {"url": "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
     "kind": "tested", "note": "ermaozi"},

    # --- منابع حجیم و به‌روز ---
    {"url": "https://raw.githubusercontent.com/MohammadBahemmat/V2ray-Collector/main/all_servers.txt",
     "kind": "bulk", "note": "کلکتور تلگرام"},
    {"url": "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/mix_sub.txt",
     "kind": "bulk", "note": "Freedom-V2Ray"},
    {"url": "https://raw.githubusercontent.com/Danialsamadi/v2go/main/AllConfigsSub.txt",
     "kind": "bulk", "note": "v2go"},
    {"url": "https://raw.githubusercontent.com/kasesm/Free-Config/main/all_sub.txt",
     "kind": "bulk", "note": "Free-Config"},
    {"url": "https://raw.githubusercontent.com/Alirewa/V2ray-Configs/main/config.txt",
     "kind": "bulk", "note": "Alirewa"},
    {"url": "https://raw.githubusercontent.com/nyeinkokoaung404/V2ray-Configs/main/All_Configs_Sub.txt",
     "kind": "bulk", "note": "V2ray-Configs"},
    {"url": "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt",
     "kind": "bulk", "note": "VLESS (٣٣٠٠ ستاره)"},
    {"url": "https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/splitted/mixed",
     "kind": "bulk", "note": "TGParse"},
    {"url": "https://raw.githubusercontent.com/mheidari98/.proxy/main/all",
     "kind": "bulk", "note": ".proxy — بزرگ‌ترین مخزن"},
    {"url": "https://raw.githubusercontent.com/Delta-Kronecker/V2ray-Config/main/config/all_configs.txt",
     "kind": "bulk", "note": "Delta-Kronecker"},
    {"url": "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/all/configs.txt",
     "kind": "bulk", "note": "همه‌ی گره‌ها (حجیم)"},
]

SUBSCRIPTION_SOURCES = [s["url"] for s in SOURCES]
SOURCE_KIND = {s["url"]: s["kind"] for s in SOURCES}

# آینه‌های دانلود/دریافت (برای وقتی که دسترسی مستقیم به GitHub کند یا قطع است)
SB_MIRROR_PREFIXES = [
    "",
    "https://gh-proxy.com/",
    "https://gh.llkk.cc/",
    "https://ghfast.top/",
]
RAW_MIRRORS = [
    {},                                          # مستقیم
    {"prefix": "https://gh-proxy.com/"},
    {"prefix": "https://gh.llkk.cc/"},
]
SB_FALLBACK_VERSIONS = ["v1.14.4", "v1.13.12", "v1.12.15"]

# ---------------------------------------------------------------------------
# پیش‌فرض‌های کاربر
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "mixed_port": 10808,
    "http_port": 10809,
    # حالت اتصال: proxy = پروکسی سیستم/مرورگر، tun = کل سیستم (نیازمند مدیر)
    "mode": "proxy",
    "set_system_proxy": True,
    "bypass_iran": True,
    "auto_connect": True,
    "auto_switch": True,
    "health_check_seconds": 20,
    "refresh_interval_minutes": 60,
    "max_test_nodes": 180,
    "batch_size": 28,
    "test_timeout_sec": 6.0,
    "speed_test_sec": 2.0,
    "theme": "dark",
    "ui_scale": 1.0,
    "concurrency": 2,
    # سایت‌هایی که کاربر می‌خواهد مطمئن شود داخل تونل باز می‌شوند
    "target_sites": [
        {"name": "تلگرام", "url": "https://t.me/", "probe": "https://api.telegram.org/"},
        {"name": "اینستاگرام", "url": "https://www.instagram.com/", "probe": "https://www.instagram.com/"},
        {"name": "یوتیوب", "url": "https://www.youtube.com/", "probe": "https://www.youtube.com/generate_204"},
    ],
    "connectivity_probe": "https://www.gstatic.com/generate_204",
    "speed_test_url": "https://speed.cloudflare.com/__down?bytes=5000000",
}
