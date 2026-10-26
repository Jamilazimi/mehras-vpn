"""
هسته‌ی برنامه: نصب امن sing-box و مدیریت چرخه‌ی عمر پروسه.

چرا sing-box؟  یک باینری، همه‌ی پروتکل‌های امروزی (VLESS+REALITY، Hysteria2،
TUIC، AnyTLS، VMess، Trojan، Shadowsocks) و حالت TUN واقعی؛ بنابراین هم
کانفیگ‌های بیشتر و تازه‌تری قابل استفاده‌اند و هم می‌توان کل سیستم (نه فقط
مرورگر) را عبور داد.
"""
import atexit
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import requests

from app.config import (DATA_DIR, SB_DIR, SB_EXE, SB_LOG, IR_CIDR_FILE,
                        SB_FALLBACK_VERSIONS, SB_MIRROR_PREFIXES)
from app.utils.logger import log

_LOCK = threading.RLock()
_PROC = None
_LOG_FH = None
_RUNNING_TUN = False

WINTUN_URLS = [
    "https://www.wintun.net/builds/wintun-0.14.1.zip",
    "https://gh-proxy.com/https://www.wintun.net/builds/wintun-0.14.1.zip",
]


# ---------------------------------------------------------------------------
# نصب
# ---------------------------------------------------------------------------
def is_installed() -> bool:
    return SB_EXE.exists() and SB_EXE.stat().st_size > 5_000_000


def _asset_url(version: str) -> str:
    if version == "latest":
        return ("https://github.com/SagerNet/sing-box/releases/latest/download/"
                "sing-box-latest-windows-amd64.zip")
    return (f"https://github.com/SagerNet/sing-box/releases/download/{version}/"
            f"sing-box-{version.lstrip('v')}-windows-amd64.zip")


def _mirrors(url: str):
    out = [url]
    for prefix in SB_MIRROR_PREFIXES:
        if prefix and not url.startswith(prefix):
            out.append(prefix + url)
    return out


def _download(url: str, dst: Path, timeout=120, progress_cb=None) -> bool:
    try:
        with requests.get(url, stream=True, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0) or 0)
            done = 0
            tmp = dst.with_suffix(dst.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(99, int(done * 100 / total)))
            if done < 1_000_000:
                tmp.unlink(missing_ok=True)
                return False
            os.replace(tmp, dst)
            return True
    except Exception as e:
        log.warning(f"download failed {url}: {e}")
        return False


def _extract(zip_path: Path, names: tuple) -> bool:
    """استخراج فایل‌های موردنیاز از آرشیو (بدون حفظ ساختار پوشه)."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            for member in z.namelist():
                base = Path(member).name
                if base in names:
                    with z.open(member) as src, open(SB_DIR / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        return SB_EXE.exists()
    except Exception as e:
        log.warning(f"extract failed: {e}")
        return False


def install(progress_cb=None) -> bool:
    """دانلود sing-box (و درایور wintun برای حالت TUN) با آینه‌های جایگزین."""
    def say(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    with _LOCK:
        if is_installed():
            _ensure_wintun()
            return True
        SB_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SB_DIR / "_dl.zip"
        for version in SB_FALLBACK_VERSIONS:
            url = _asset_url(version)
            for i, mirror in enumerate(_mirrors(url), 1):
                say(f"دانلود هسته sing-box ({version}) — تلاش {i}...")
                ok = _download(
                    mirror, tmp, timeout=180,
                    progress_cb=lambda p: say(f"دانلود هسته‌ی sing-box... {p}%"))
                if not ok:
                    continue
                _extract(tmp, ("sing-box.exe", "libcronet.dll", "LICENSE"))
                tmp.unlink(missing_ok=True)
                if is_installed():
                    log.info(f"sing-box installed from {mirror}")
                    _ensure_wintun()
                    say("هسته‌ی sing-box نصب شد.")
                    return True
        log.error("sing-box install failed on every mirror")
        say("نصب خودکار هسته ناموفق بود. فایل sing-box.exe را در data/singbox قرار دهید.")
        return False


def _ensure_wintun() -> bool:
    """wintun.dll برای حالت TUN لازم است؛ نبودش فقط TUN را غیرفعال می‌کند."""
    target = SB_DIR / "wintun.dll"
    if target.exists() and target.stat().st_size > 100_000:
        return True
    tmp = SB_DIR / "_wintun.zip"
    for url in WINTUN_URLS:
        if not _download(url, tmp, timeout=90):
            continue
        try:
            with zipfile.ZipFile(tmp) as z:
                for member in z.namelist():
                    if member.lower().endswith("bin/amd64/wintun.dll"):
                        with z.open(member) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        break
        except Exception as e:
            log.warning(f"wintun extract failed: {e}")
        tmp.unlink(missing_ok=True)
        if target.exists():
            log.info("wintun.dll installed")
            return True
    log.warning("wintun.dll unavailable — TUN mode disabled")
    return False


def has_tun_driver() -> bool:
    return (SB_DIR / "wintun.dll").exists()


def is_admin() -> bool:
    """آیا برنامه با دسترسی مدیر اجرا شده است؟ (برای حالت TUN لازم است)"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def tun_ready() -> bool:
    return has_tun_driver() and is_admin()


def version() -> str:
    if not is_installed():
        return ""
    try:
        out = subprocess.run([str(SB_EXE), "version"], capture_output=True,
                             text=True, timeout=10,
                             creationflags=_flags())
        for line in out.stdout.splitlines():
            if line.strip():
                return line.strip()
    except Exception:
        pass
    return ""


def _flags():
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# ساخت کانفیگ
# ---------------------------------------------------------------------------
def _ir_cidrs() -> list:
    """فهرست CIDR سایت‌های ایرانی برای عبور مستقیم (کاهش پهنای باند و مشکلات بانکی)."""
    try:
        if IR_CIDR_FILE.exists():
            lines = IR_CIDR_FILE.read_text(encoding="utf-8").splitlines()
            return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    except Exception:
        pass
    return []


IR_DOMAIN_SUFFIXES = [
    ".ir", ".ir.", "digikala.com", "aparat.com", "divar.ir", "blogfa.com",
    "bmi.ir", "shaparak.ir", "banksepah.ir", "bsi.ir", "mci.ir", "irancell.ir",
    "sadad.ir", "zarinpal.com", "snapp.ir", "tap30.ir", "cafebazaar.ir",
    "myket.ir", "bale.ai", "eitaa.com", "rubika.ir", "splus.ir", "telewebion.com",
    "filimo.com", "navaar.ir", "khanoumi.com", "torob.com", "sheypoor.com",
    "alibaba.ir", "ghasedak24.com", "parsian-bank.ir", "sb24.ir", "blubank.ir",
]


def build_config(nodes: list, mixed_port: int, http_port: int,
                 tun: bool = False, bypass_iran: bool = True,
                 log_level: str = "warning", stats_port: int = 19090) -> dict:
    """کانفیگ کامل sing-box برای اتصال اصلی.
    nodes: لیست گره‌ها؛ nodes[0] گره‌ی فعال است.
    """
    outbounds = []
    for i, node in enumerate(nodes):
        ob = json.loads(json.dumps(node["outbound"]))   # کپی عمیق
        ob["tag"] = f"node-{i}"
        outbounds.append(ob)
    outbounds.append({"type": "direct", "tag": "direct"})
    outbounds.append({"type": "block", "tag": "block"})

    inbounds = [
        {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1",
         "listen_port": int(mixed_port)},
    ]
    if http_port and int(http_port) != int(mixed_port):
        inbounds.append({"type": "http", "tag": "http-in", "listen": "127.0.0.1",
                         "listen_port": int(http_port)})

    rules = []
    if bypass_iran:
        rules.append({"domain_suffix": IR_DOMAIN_SUFFIXES, "outbound": "direct"})
    if tun:
        inbounds.append({
            "type": "tun", "tag": "tun-in",
            "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
            "mtu": 9000, "auto_route": True, "strict_route": True,
            "stack": "mixed",
        })
        ir_cidrs = _ir_cidrs()
        if bypass_iran and ir_cidrs:
            rules.insert(0, {"ip_cidr": ir_cidrs, "outbound": "direct"})
        rules.insert(0, {"ip_is_private": True, "outbound": "direct"})
        rules.insert(0, {"protocol": "dns", "action": "hijack-dns"})
        rules.insert(0, {"action": "sniff"})

    dns = {"servers": [{"tag": "local", "type": "local"}], "final": "local"}
    if tun:
        # در حالت TUN کوئری‌ها باید از تونل بروند تا مسموم‌سازی DNS اثر نکند
        dns = {
            "servers": [
                {"tag": "remote", "type": "https", "server": "1.1.1.1",
                 "detour": "node-0", "domain_resolver": "local"},
                {"tag": "local", "type": "local"},
            ],
            "final": "remote",
            "strategy": "ipv4_only",
        }

    config = {
        "log": {"level": log_level, "timestamp": True},
        "dns": dns,
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {
            "rules": rules,
            "final": "node-0",
            "auto_detect_interface": True,
            "default_domain_resolver": "local",
        },
        "experimental": {
            "clash_api": {"external_controller": f"127.0.0.1:{stats_port}"}
        },
    }
    return config


def check_config(config: dict):
    """اعتبارسنجی کانفیگ با خود هسته. (ok, message)"""
    tmp = SB_DIR / f"_check_{os.getpid()}_{threading.get_ident()}.json"
    try:
        tmp.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([str(SB_EXE), "check", "-c", str(tmp)],
                           capture_output=True, text=True, timeout=25,
                           creationflags=_flags())
        if r.returncode == 0:
            return True, ""
        msg = (r.stderr or r.stdout or "").strip()
        return False, msg.splitlines()[-1] if msg else "unknown"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# اجرا / توقف
# ---------------------------------------------------------------------------
def _port_open(port: int, timeout=0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def start(config: dict, wait_port: int = None, timeout: float = 8.0) -> bool:
    """اجرای هسته با کانفیگ داده‌شده و انتظار تا آماده‌شدن پورت محلی."""
    global _PROC, _LOG_FH, _RUNNING_TUN
    with _LOCK:
        if not is_installed():
            log.error("sing-box is not installed")
            return False
        stop()

        cfg_file = SB_DIR / "active.json"
        cfg_file.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        try:
            _LOG_FH = open(SB_LOG, "a", encoding="utf-8", errors="replace")
            _LOG_FH.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            _LOG_FH.flush()
            _PROC = subprocess.Popen(
                [str(SB_EXE), "run", "-c", str(cfg_file)],
                stdout=_LOG_FH, stderr=subprocess.STDOUT,
                creationflags=_flags(),
            )
        except Exception as e:
            log.error(f"sing-box start failed: {e}")
            _PROC = None
            return False
        _RUNNING_TUN = any(ib.get("type") == "tun" for ib in config.get("inbounds", []))

    if wait_port:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with _LOCK:
                proc = _PROC
            if proc is None:
                return False
            if proc.poll() is not None:
                log.error(f"sing-box exited immediately (code {proc.returncode})")
                with _LOCK:
                    _PROC = None
                _close_log()
                return False
            if _port_open(wait_port):
                log.info(f"sing-box started (pid={proc.pid}, port={wait_port})")
                return True
            time.sleep(0.15)
        log.error("sing-box started but local port never opened")
        stop()
        return False
    time.sleep(0.6)
    return _PROC is not None and _PROC.poll() is None


def _close_log():
    global _LOG_FH
    if _LOG_FH:
        try:
            _LOG_FH.close()
        except Exception:
            pass
        _LOG_FH = None


def is_running() -> bool:
    with _LOCK:
        return _PROC is not None and _PROC.poll() is None


def is_tun_active() -> bool:
    return _RUNNING_TUN and is_running()


def stop():
    global _PROC, _RUNNING_TUN
    with _LOCK:
        proc = _PROC
        _PROC = None
        _RUNNING_TUN = False
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=6)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _close_log()
        log.info("sing-box stopped")


def tail_log(lines: int = 40) -> str:
    try:
        if SB_LOG.exists():
            return "\n".join(SB_LOG.read_text(encoding="utf-8",
                                              errors="replace").splitlines()[-lines:])
    except Exception:
        pass
    return ""


def _cleanup():
    try:
        stop()
    except Exception:
        pass


atexit.register(_cleanup)
