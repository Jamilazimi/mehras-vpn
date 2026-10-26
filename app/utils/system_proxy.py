"""
پروکسی سیستم ویندوز (رجیستری) با پشتیبان‌گیری و بازگردانی تنظیمات کاربر.
پروتکل‌های http/https/socks همه به پورت mixed هسته اشاره می‌کنند تا
مرورگرها و برنامه‌هایی که پروکسی سیستم را می‌خوانند بدون تنظیم اضافه کار کنند.
"""
import ctypes
import json

import winreg

from app.config import PROXY_BACKUP_FILE
from app.utils.logger import log

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39


def _refresh():
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception as e:
        log.warning(f"proxy refresh failed: {e}")


def get_current_proxy():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            try:
                enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                override = ""
                try:
                    override, _ = winreg.QueryValueEx(key, "ProxyOverride")
                except FileNotFoundError:
                    pass
                return {"enable": bool(enable), "server": server or "",
                        "override": override or ""}
            except FileNotFoundError:
                return {"enable": False, "server": "", "override": ""}
    except Exception as e:
        log.error(f"read proxy failed: {e}")
        return {"enable": False, "server": "", "override": ""}


def _backup_once():
    """فقط یک بار، قبل از اولین تغییر، وضعیت اصلی کاربر ذخیره می‌شود."""
    try:
        if PROXY_BACKUP_FILE.exists():
            return
        PROXY_BACKUP_FILE.write_text(json.dumps(get_current_proxy()),
                                     encoding="utf-8")
    except Exception as e:
        log.warning(f"proxy backup failed: {e}")


def set_proxy(host="127.0.0.1", port=10808) -> bool:
    try:
        _backup_once()
        server = (f"http={host}:{port};https={host}:{port};socks={host}:{port}")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                              "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;"
                              "172.19.*;172.20.*;172.21.*;172.22.*;172.23.*;"
                              "172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;"
                              "172.29.*;172.30.*;172.31.*;192.168.*;<local>")
        _refresh()
        log.info(f"system proxy -> {server}")
        return True
    except Exception as e:
        log.error(f"set proxy failed: {e}")
        return False


def clear_proxy() -> bool:
    """بازگردانی تنظیم قبلی کاربر (یا غیرفعال‌سازی اگر پشتیبانی نبود)."""
    try:
        restored = False
        if PROXY_BACKUP_FILE.exists():
            try:
                data = json.loads(PROXY_BACKUP_FILE.read_text(encoding="utf-8"))
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                                    winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD,
                                      1 if data.get("enable") else 0)
                    if data.get("server"):
                        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ,
                                          data["server"])
                    if data.get("override"):
                        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                                          data["override"])
                restored = True
                PROXY_BACKUP_FILE.unlink(missing_ok=True)
                log.info(f"system proxy restored: {data}")
            except Exception as e:
                log.warning(f"proxy restore failed: {e}")
        if not restored:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            log.info("system proxy disabled")
        _refresh()
        return True
    except Exception as e:
        log.error(f"clear proxy failed: {e}")
        return False


def is_ours(port=10808) -> bool:
    cur = get_current_proxy()
    return cur["enable"] and f":{port}" in cur["server"]
