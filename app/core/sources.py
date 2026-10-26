"""
دریافت اشتراک‌ها از اینترنت و تبدیل آن‌ها به گره‌های آماده‌ی تست.

نکات مهم:
  * ترتیب منابع حفظ می‌شود (منابع تست‌شده اول) و در حذف تکراری‌ها
    گره‌ای که از منبع باکیفیت‌تر آمده برنده است.
  * هر منبع سقف تعداد لینک دارد تا یک فایل ۸ مگابایتی کل صف تست را
    اشغال نکند.
  * علاوه بر متن ساده، اشتراک‌های base64 و آرایه‌های JSON هم پشتیبانی می‌شوند.
"""
import base64
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from app.config import CUSTOM_SOURCES_FILE, SOURCES, SOURCE_KIND
from app.core.parser import parse_link
from app.utils.logger import log

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "*/*",
}

LINK_RE = re.compile(
    r"(?:vmess|vless|trojan|ss|hysteria2|hy2|tuic|anytls)://[^\s\"'<>\\]+", re.I)

# سقف لینک هر منبع (منابع تست‌شده سقف بالاتری دارند)
MAX_LINKS_PER_SOURCE = {"tested": 800, "bulk": 2600, "custom": 4000}


# ---------------------------------------------------------------------------
# اشتراک/کانفیگ شخصی کاربر
# ---------------------------------------------------------------------------
def load_custom_entries() -> list:
    """ورودی‌های شخصی کاربر: آدرس اشتراک (http...) یا لینک مستقیم (vless://...).

    این‌ها همیشه اول لیست تست می‌شوند و امتیاز بالاتری می‌گیرند، چون معمولاً
    پایدارتر از گره‌های عمومی رایگان‌اند.
    """
    if not CUSTOM_SOURCES_FILE.exists():
        return []
    try:
        data = json.loads(CUSTOM_SOURCES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    entries = []
    for raw in data:
        value = (raw or "").strip() if isinstance(raw, str) else ""
        if not value:
            continue
        if value.startswith(("http://", "https://")):
            entries.append({"url": value, "kind": "custom",
                            "note": "اشتراک شخصی"})
        else:
            node = parse_link(value)
            if not node:
                log.warning("custom entry is not a valid config link")
                continue
            # کلید یکتا برای هر کانفیگ دستی (وگرنه چند لینک روی هم می‌افتند)
            entries.append({"link": value, "kind": "custom",
                            "url": f"custom:{node['id']}",
                            "note": "کانفیگ دستی"})
    return entries


def save_custom_lines(lines: list) -> bool:
    cleaned = []
    for line in lines:
        value = (line or "").strip()
        if not value or value.startswith("#"):
            continue
        cleaned.append(value)
    try:
        CUSTOM_SOURCES_FILE.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"save custom sources failed: {e}")
        return False


def load_custom_lines() -> list:
    if not CUSTOM_SOURCES_FILE.exists():
        return []
    try:
        data = json.loads(CUSTOM_SOURCES_FILE.read_text(encoding="utf-8"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def _mirror_urls(url: str) -> list:
    """آینه‌های جایگزین برای raw.githubusercontent (کاربر ایرانی)."""
    out = [url]
    if "raw.githubusercontent.com/" in url:
        try:
            parts = url.split("raw.githubusercontent.com/", 1)[1].split("/")
            user, repo, branch = parts[0], parts[1], parts[2]
            path = "/".join(parts[3:])
            out.append(f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}")
        except Exception:
            pass
        for prefix in ("https://gh-proxy.com/", "https://gh.llkk.cc/",
                       "https://ghfast.top/"):
            out.append(prefix + url)
    return out


def _maybe_b64(text: str) -> str:
    """اگر متن base64 است، دیکد کن (بسیاری از اشتراک‌ها base64 هستند)."""
    if "://" in text:
        return text
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 40:
        return text
    padded = cleaned.replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False).decode("utf-8", "ignore")
    except Exception:
        return text
    return decoded if "://" in decoded else text


def normalize_text(text: str) -> str:
    """تبدیل خروجی هر منبع (متن/base64/JSON) به متن خط‌به‌خط لینک‌ها."""
    if not text:
        return ""
    stripped = text.lstrip("\ufeff \r\n\t")
    if stripped.startswith(("[", "{")):
        try:
            data = json.loads(stripped)
            return "\n".join(_links_from_json(data))
        except Exception:
            pass
    return _maybe_b64(text)


def _links_from_json(data) -> list:
    """استخراج لینک/آدرس از ساختارهای JSON (sing-box یا لیست ساده)."""
    out = []

    def walk(obj):
        if isinstance(obj, str):
            if "://" in obj:
                out.append(obj.strip())
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            for key in ("url", "link", "config", "uri"):
                if isinstance(obj.get(key), str):
                    walk(obj[key])
            for key in ("outbounds", "proxies", "servers", "data"):
                if key in obj:
                    walk(obj[key])

    walk(data)
    return out


def extract_links(text: str) -> list:
    """استخراج لینک‌های معتبر از متن (با پشتیبانی از خطوط چند‌لینکی)."""
    links = []
    for line in text.splitlines():
        line = line.strip().strip(",;")
        if not line:
            continue
        if line.lower().startswith(("vmess://", "vless://", "trojan://", "ss://",
                                    "hysteria2://", "hy2://", "tuic://",
                                    "anytls://")):
            links.append(line)
            continue
        found = LINK_RE.findall(line)
        if found:
            links.extend(found)
    cleaned = []
    for ln in links:
        ln = ln.rstrip("\\\"'")
        if len(ln) > 12:
            cleaned.append(ln)
    return cleaned


def fetch_source(url: str, timeout=25, stop_fn=None) -> str:
    """دریافت متن یک منبع با fallback روی آینه‌ها."""
    errors = []
    for attempt_url in _mirror_urls(url):
        if stop_fn and stop_fn():
            return ""
        try:
            r = requests.get(attempt_url, headers=HEADERS, timeout=timeout)
            if r.status_code != 200:
                errors.append(f"{attempt_url}: HTTP {r.status_code}")
                continue
            text = normalize_text(r.text)
            if text and len(text) > 50:
                return text
            errors.append(f"{attempt_url}: empty")
        except Exception as e:
            errors.append(f"{attempt_url}: {type(e).__name__}")
    log.warning(f"source failed {url}: {'; '.join(errors[:3])}")
    return ""


def _parse_one_source(url: str, text: str, limit: int, kind: str = "bulk") -> list:
    nodes = []
    seen = set()
    for link in extract_links(text):
        if link[:40] in seen:
            continue
        node = parse_link(link)
        if not node:
            continue
        seen.add(link[:40])
        node["src"] = url
        if kind == "custom":
            node["custom"] = True
        nodes.append(node)
        if len(nodes) >= limit:
            break
    return nodes


def fetch_all(progress_cb=None, stop_fn=None, sources=None, deadline_sec=75,
              include_custom=True) -> list:
    """دریافت موازی همه‌ی منابع و برگرداندن گره‌های یکتا.

    progress_cb(done, total, message)
    """
    entries = list(sources) if sources else list(SOURCES)
    if entries and isinstance(entries[0], str):
        entries = [{"url": u, "kind": SOURCE_KIND.get(u, "bulk")} for u in entries]
    if include_custom:
        entries = load_custom_entries() + entries
    total = len(entries)
    started = time.time()
    results = {}                       # url -> nodes
    order = {}
    for idx, entry in enumerate(entries):
        order[entry["url"]] = idx

    def work(entry):
        if entry.get("link"):
            return (entry["url"],
                    _parse_one_source(entry["url"], entry["link"], 4, "custom"))
        text = fetch_source(entry["url"], stop_fn=stop_fn)
        if not text:
            return entry["url"], []
        limit = MAX_LINKS_PER_SOURCE.get(entry.get("kind", "bulk"), 2000)
        return entry["url"], _parse_one_source(
            entry["url"], text, limit, entry.get("kind", "bulk"))

    done = 0
    with ThreadPoolExecutor(max_workers=min(10, total)) as ex:
        futures = {ex.submit(work, e): e for e in entries}
        for fut in as_completed(futures):
            if stop_fn and stop_fn():
                for f in futures:
                    f.cancel()
                break
            done += 1
            try:
                url, nodes = fut.result()
                if nodes:
                    results[url] = nodes
                    log.info(f"source {url.rsplit('/', 1)[-1]} -> {len(nodes)} nodes")
            except Exception as e:
                log.warning(f"source error: {e}")
            if progress_cb:
                progress_cb(done, total, f"دریافت منابع {done}/{total}")
            if time.time() - started > deadline_sec:
                log.info("fetch deadline reached")
                for f in futures:
                    f.cancel()
                break

    # ادغام به ترتیب اولویت منابع (تست‌شده‌ها اول)
    merged = []
    by_id = {}
    for url in sorted(results, key=lambda u: order.get(u, 999)):
        for node in results[url]:
            nid = node["id"]
            if nid in by_id:
                continue
            by_id[nid] = node
            merged.append(node)

    by_type = {}
    for n in merged:
        by_type[n["protocol"]] = by_type.get(n["protocol"], 0) + 1
    log.info(f"fetched {len(merged)} unique nodes {by_type}")
    if progress_cb:
        progress_cb(total, total, f"{len(merged)} گره‌ی یکتا")
    return merged


def save_nodes(path, nodes):
    try:
        path.write_text(json.dumps(nodes, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception as e:
        log.error(f"save nodes failed: {e}")


def load_nodes(path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []
