"""
رتبه‌بندی، کش و سلامت منابع.

هدف: همیشه بهترین گره‌ی «واقعاً کارکننده» انتخاب شود و در نوبت‌های بعد
منابعی که گره‌ی مرده تحویل می‌دهند خودکار عقب بیفتند.
"""
import json
import time

from app.config import (SERVERS_FILE, SETTINGS_FILE, WORKING_CACHE_FILE,
                        SOURCE_HEALTH_FILE, DEFAULT_SETTINGS)
from app.utils.logger import log


# ---------------------------------------------------------------------------
# امتیازدهی
# ---------------------------------------------------------------------------
def score(node: dict) -> float:
    """امتیاز ۰..۱۰۰ برای انتخاب بهترین گره."""
    if not node.get("working"):
        return -1.0
    latency = node.get("latency") or 2500.0
    latency = max(20.0, float(latency))
    lat_part = max(0.0, 1.0 - (latency - 60.0) / 2400.0) * 60.0
    speed = node.get("speed_kbps")
    if speed is None:
        speed = 1200.0          # تست سرعت انجام نشده → امتیاز متوسط
    speed_part = min(float(speed), 15000.0) / 15000.0 * 40.0
    stability = node.get("success_rate")
    stability = 1.0 if stability is None else float(stability)
    value = (lat_part + speed_part) * (0.35 + 0.65 * min(1.0, stability))
    # اگر گره با سایت‌های هدف آزموده شده، نتیجه‌ی آن‌ها وزن جدی می‌گیرد
    targets_ok = node.get("targets_ok")
    if targets_ok is not None:
        value *= {0: 0.30, 1: 0.55, 2: 0.90}.get(int(targets_ok), 1.15)
    # گره‌های اشتراک شخصی کاربر قابل‌اعتمادترند
    if node.get("custom"):
        value *= 1.30
    return round(value, 2)


def rank(nodes: list) -> list:
    working = [n for n in nodes if n.get("working")]
    working.sort(key=score, reverse=True)
    return working


def rank_all(nodes: list) -> list:
    """سالم‌ها به ترتیب امتیاز، سپس بقیه به ترتیب پینگ TCP."""
    working = rank(nodes)
    rest = [n for n in nodes if not n.get("working")]
    rest.sort(key=lambda n: n.get("tcp_ping") or 9e9)
    return working + rest


# ---------------------------------------------------------------------------
# ذخیره‌سازی
# ---------------------------------------------------------------------------
def _write_json(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"write {path.name} failed: {e}")
        return False


def _read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_cache() -> list:
    data = _read_json(WORKING_CACHE_FILE, [])
    if not isinstance(data, list):
        return []
    now = time.time()
    # گره‌های خیلی قدیمی (بیش از ۳ روز) ارزش امتحان کردن ندارند
    fresh = []
    for node in data:
        if not isinstance(node, dict) or not node.get("outbound"):
            continue
        ts = node.get("tested_at") or now
        if now - ts > 3 * 24 * 3600:
            continue
        fresh.append(node)
    return rank(fresh)


def save_cache(nodes: list, merge: bool = True):
    """ذخیره گره‌های سالم.

    با merge=True گره‌های سالم قبلی حفظ می‌شوند؛ این مهم است چون ممکن است یک
    اسکن در ساعت شلوغی شبکه نتیجه‌ی بد بدهد و نباید حافظه‌ی خوب را پاک کند.
    """
    working = [n for n in nodes if n.get("working")]
    if not working and not merge:
        return False
    if merge:
        previous = {n["id"]: n for n in load_cache()}
        for node in working:
            previous[node["id"]] = node
        working = list(previous.values())
    if not working:
        return False
    now = int(time.time())
    for node in working:
        node.setdefault("tested_at", now)
    ranked = rank(working)[:80]
    return _write_json(WORKING_CACHE_FILE, ranked)


def load_servers() -> list:
    data = _read_json(SERVERS_FILE, [])
    return data if isinstance(data, list) else []


def save_servers(nodes: list):
    return _write_json(SERVERS_FILE, nodes[:800])


# ---------------------------------------------------------------------------
# سلامت منابع
# ---------------------------------------------------------------------------
def load_source_health() -> dict:
    data = _read_json(SOURCE_HEALTH_FILE, {})
    return data if isinstance(data, dict) else {}


def update_source_health(nodes: list) -> dict:
    """نرخ «زنده‌بودن واقعی» هر منبع را به‌روز می‌کند."""
    health = load_source_health()
    stats = {}
    for node in nodes:
        src = node.get("src")
        if not src or "working" not in node:
            continue
        alive, total = stats.get(src, (0, 0))
        stats[src] = (alive + (1 if node.get("working") else 0), total + 1)
    now = int(time.time())
    for src, (alive, total) in stats.items():
        if total < 8:
            continue
        rate = alive / total
        prev = health.get(src) or {}
        prev_rate = prev.get("rate")
        # میانگین وزنی با نتیجه‌ی قبلی تا نوسان یک نوبت، منبع را حذف نکند
        blended = rate if prev_rate is None else round(prev_rate * 0.5 + rate * 0.5, 4)
        health[src] = {"alive": alive, "total": total,
                       "rate": round(rate, 4), "score": blended, "ts": now}
    _write_json(SOURCE_HEALTH_FILE, health)
    dead = [s for s, h in health.items()
            if (h.get("total") or 0) >= 60 and (h.get("score") or 1) < 0.005]
    if dead:
        log.info(f"{len(dead)} sources are effectively dead")
    return health


def order_by_health(nodes: list) -> list:
    """اول گره‌های منابع پربازده (نسبت زنده‌بودن بالاتر)."""
    health = load_source_health()

    def key(node):
        h = health.get(node.get("src") or "")
        if not h or not h.get("total"):
            return 1                                  # ناشناخته: وسط
        return 0 if (h.get("score") or 0) >= 0.02 else 2

    buckets = {0: [], 1: [], 2: []}
    for node in nodes:
        buckets[key(node)].append(node)
    out = []
    for i in (0, 1, 2):
        group = buckets[i]
        # داخل هر گروه اول گره‌های منابع تست‌شده
        group.sort(key=lambda n: 0 if (n.get("src") or "").endswith(
            ("top100.txt", "working_configs.txt", "working_configs_general.txt",
             "working_configs_phase6.txt", "configs.txt", "Eternity.txt",
             "V2RAY_RAW.txt", "super-sub.txt", "Sub1.txt", "v2ray.txt")) else 1)
        out.extend(group)
    return out


def settings_with_defaults(raw: dict) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        merged.update(raw)
    return merged


def load_settings() -> dict:
    return settings_with_defaults(_read_json(SETTINGS_FILE, {}))


def save_settings(settings: dict) -> bool:
    return _write_json(SETTINGS_FILE, settings)
