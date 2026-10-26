"""
تجزیه لینک‌های اشتراک (vmess / vless / trojan / shadowsocks / hysteria2 / tuic / anytls)
به outbound استاندارد sing-box نسخه ۱.۱۲+.

طراحی:
  * هر تابع فقط یک وظیفه دارد و در صورت کوچک‌ترین ابهام None برمی‌گرداند،
    چون یک گره‌ی ناقص باعث خطای راه‌اندازی کل هسته می‌شود.
  * خروجی هر گره یک دیکشنری آماده‌ی استفاده در `outbounds` هسته است.
  * فیلدهای اختیاری فقط وقتی اضافه می‌شوند که مقدار معتبر داشته باشند
    (sing-box روی مقدار نامعتبر مثل fingerprint ناشناس خطای مهلک می‌دهد).
"""
import base64
import hashlib
import json
import re
import urllib.parse

# --------------------------------------------------------------------------
# مقادیر مجاز — دقیقاً همان چیزی که sing-box قبول می‌کند
# --------------------------------------------------------------------------
UTLS_FINGERPRINTS = {
    "chrome", "firefox", "edge", "safari", "360", "qq", "ios",
    "android", "random", "randomized",
}
SS_METHODS = {
    "aes-128-gcm", "aes-192-gcm", "aes-256-gcm",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
    "none", "plain",
}
VMESS_SECURITY = {"auto", "none", "zero", "aes-128-gcm", "chacha20-poly1305"}
TUIC_CONGESTION = {"cubic", "new_reno", "bbr"}
TUIC_RELAY = {"native", "quic"}
SUPPORTED_SCHEMES = ("vmess://", "vless://", "trojan://", "ss://",
                     "hysteria2://", "hy2://", "tuic://", "anytls://")

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")


# --------------------------------------------------------------------------
# کمک‌تابع‌ها
# --------------------------------------------------------------------------
def b64decode_any(s: str) -> str:
    """دیکد base64 با تحمل خطا (url-safe، بدون padding، با فاصله/نویز)."""
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s, validate=False).decode("utf-8", "ignore")
    except Exception:
        return ""


def b64encode_str(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def norm_uuid(raw: str) -> str:
    """نرمال‌سازی UUID: حذف آکولاد/فاصله و افزودن خط‌تیره در صورت نیاز."""
    if not raw:
        return ""
    s = raw.strip().strip("{}").strip().lower()
    if UUID_RE.match(s):
        return s
    hexonly = re.sub(r"[^0-9a-f]", "", s)
    if len(hexonly) == 32:
        return (f"{hexonly[0:8]}-{hexonly[8:12]}-{hexonly[12:16]}-"
                f"{hexonly[16:20]}-{hexonly[20:32]}")
    return ""


def _q(query: dict, key: str, default: str = "") -> str:
    v = query.get(key)
    if isinstance(v, list):
        v = v[0] if v else ""
    return (v or default).strip()


def _is_private_host(host: str) -> bool:
    """گره‌های لوکال/خصوصی هیچ‌وقت پروکسی عمومی نیستند."""
    if not host:
        return True
    h = host.strip("[]").lower()
    if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if re.match(r"^10\.", h) or re.match(r"^192\.168\.", h) or re.match(r"^169\.254\.", h):
        return True
    m = re.match(r"^172\.(\d{1,3})\.", h)
    if m and 16 <= int(m.group(1)) <= 31:
        return True
    if h.startswith(("fc", "fd", "fe80")):
        return True
    return False


def _alpn_list(raw: str):
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p and len(p) < 32]


def _valid_server(server: str) -> bool:
    if not server or len(server) > 253:
        return False
    if _is_private_host(server):
        return False
    if " " in server or "/" in server:
        return False
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", server):
        return all(0 <= int(p) <= 255 for p in server.split("."))
    return bool(HOST_RE.match(server))


def _tls_block(security: str, sni: str, fp: str, alpn: str,
               insecure: bool, pbk: str = "", sid: str = ""):
    """ساخت بخش tls؛ reality فقط وقتی کلید عمومی معتبر باشد ساخته می‌شود."""
    security = (security or "").lower()
    if security not in ("tls", "reality", "xtls"):
        return None
    tls = {"enabled": True}
    if sni:
        tls["server_name"] = sni
    if insecure:
        tls["insecure"] = True
    fpr = (fp or "").lower()
    if fpr in UTLS_FINGERPRINTS:
        tls["utls"] = {"enabled": True, "fingerprint": fpr}
    alpn_list = _alpn_list(alpn)
    if alpn_list:
        tls["alpn"] = alpn_list
    if security == "reality":
        if not pbk:
            return None                      # بدون کلید عمومی، REALITY کار نمی‌کند
        # sing-box برای REALITY حتماً uTLS می‌خواهد؛ اگر لینک fp نداشت chrome بگذار
        if "utls" not in tls:
            tls["utls"] = {"enabled": True, "fingerprint": "chrome"}
        reality = {"enabled": True, "public_key": pbk}
        if sid:
            reality["short_id"] = sid
        tls["reality"] = reality
    return tls


def _transport(net: str, path: str, host: str, service_name: str = "",
               header_type: str = ""):
    """ساخت transport. رشته "__skip__" یعنی پروتکل انتقال پشتیبانی نمی‌شود."""
    net = (net or "tcp").strip().lower()
    if net in ("", "tcp", "raw", "none"):
        if (header_type or "").lower() == "http":
            return "__skip__"                # هدر HTTP روی TCP در sing-box نیست
        return None
    if net == "ws":
        ws = {"type": "ws", "path": path or "/"}
        if host:
            ws["headers"] = {"Host": host}
        return ws
    if net in ("httpupgrade", "http-upgrade"):
        tr = {"type": "httpupgrade", "path": path or "/"}
        if host:
            tr["host"] = host
        return tr
    if net == "grpc":
        return {"type": "grpc", "service_name": (service_name or path or "").lstrip("/")}
    if net in ("h2", "http"):
        tr = {"type": "http", "path": path or "/"}
        if host:
            tr["host"] = [host]
        return tr
    if net == "quic":
        return {"type": "quic"}
    return "__skip__"


def _finish(kind: str, server: str, port: int, remark: str, outbound: dict, raw: str):
    """اعتبارسنجی نهایی و ساخت شیء گره."""
    if not _valid_server(server):
        return None
    try:
        port = int(port)
    except Exception:
        return None
    if not (0 < port < 65536):
        return None
    outbound["server"] = server
    outbound["server_port"] = port
    node = {
        "protocol": kind,
        "server": server,
        "port": port,
        "remark": (remark or f"{server}:{port}").strip()[:120],
        "outbound": outbound,
        "raw": raw,
    }
    node["id"] = node_id(node)
    return node


def node_id(node: dict) -> str:
    """شناسه پایدار بر اساس مشخصات اتصال (مستقل از نام/کامنت)."""
    ob = node.get("outbound") or {}
    key = [ob.get("type", ""), ob.get("server", ""), str(ob.get("server_port", "")),
           ob.get("uuid", ""), ob.get("password", ""), ob.get("method", "")]
    tr = ob.get("transport") or {}
    if tr:
        key += [tr.get("type", ""), tr.get("path", ""), str(tr.get("service_name", ""))]
    tls = ob.get("tls") or {}
    key += [tls.get("server_name", "")]
    return hashlib.md5("|".join(key).encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------
# VLESS
# --------------------------------------------------------------------------
def parse_vless(link: str):
    try:
        u = urllib.parse.urlparse(link)
        if not u.hostname:
            return None
        q = urllib.parse.parse_qs(u.query)
        uid = norm_uuid(urllib.parse.unquote(u.username or ""))
        if not uid:
            return None
        port = u.port or 443
        net = _q(q, "type", "tcp")
        security = _q(q, "security", "")
        if not security:
            security = "tls" if _q(q, "tls") == "tls" else "none"
        host = _q(q, "host")
        sni = _q(q, "sni") or _q(q, "peer") or host
        path = _q(q, "path", "/")
        insecure = _q(q, "allowInsecure") in ("1", "true") or _q(q, "insecure") in ("1", "true")

        outbound = {"type": "vless", "uuid": uid}
        flow = _q(q, "flow")
        if flow and security in ("reality", "tls") and net in ("tcp", "raw", ""):
            outbound["flow"] = flow
        tls = _tls_block(security, sni, _q(q, "fp"), _q(q, "alpn"), insecure,
                         _q(q, "pbk"), _q(q, "sid"))
        if security in ("reality", "tls", "xtls") and tls is None:
            return None
        if tls:
            outbound["tls"] = tls
        tr = _transport(net, path, host, _q(q, "serviceName") or path, _q(q, "headerType"))
        if tr == "__skip__":
            return None
        if tr:
            outbound["transport"] = tr
        return _finish("vless", u.hostname, port,
                       urllib.parse.unquote(u.fragment), outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# VMess
# --------------------------------------------------------------------------
def parse_vmess(link: str):
    body = link[len("vmess://"):].strip()
    data = None
    if body.startswith("{"):
        try:
            data = json.loads(body)
        except Exception:
            data = None
    if data is None:
        decoded = b64decode_any(body)
        if decoded.strip().startswith("{"):
            try:
                data = json.loads(decoded)
            except Exception:
                data = None
    if data is None:
        return _parse_vmess_uri(link, body)
    try:
        server = str(data.get("add", "")).strip()
        port = int(str(data.get("port", 0)).strip() or 0)
        uid = norm_uuid(str(data.get("id", "")))
        if not uid:
            return None
        net = str(data.get("net", "tcp") or "tcp").lower()
        header_type = str(data.get("type", "") or "").lower()
        tls_flag = str(data.get("tls", "") or "").lower()
        host = str(data.get("host", "") or "")
        path = str(data.get("path", "") or "/")
        sni = str(data.get("sni", "") or "") or host
        security = str(data.get("scy", "auto") or "auto").lower()
        if security not in VMESS_SECURITY:
            security = "auto"

        outbound = {"type": "vmess", "uuid": uid, "security": security,
                    "alter_id": int(str(data.get("aid", 0) or 0).strip() or 0)}
        if tls_flag in ("tls", "reality"):
            tls = _tls_block("tls" if tls_flag == "tls" else "reality",
                             sni, str(data.get("fp", "") or ""),
                             str(data.get("alpn", "") or ""), False,
                             str(data.get("pbk", "") or ""),
                             str(data.get("sid", "") or ""))
            if tls:
                outbound["tls"] = tls
            elif tls_flag == "reality":
                return None
        tr = _transport(net, path, host, path, header_type)
        if tr == "__skip__":
            return None
        if tr:
            outbound["transport"] = tr
        return _finish("vmess", server, port,
                       str(data.get("ps", "") or ""), outbound, link)
    except Exception:
        return None


def _parse_vmess_uri(link: str, body: str):
    """فرمت جدید vmess://uuid@host:port?type=ws&security=tls#name"""
    try:
        u = urllib.parse.urlparse("vmess://" + body)
        if not u.hostname or not u.username:
            return None
        q = urllib.parse.parse_qs(u.query)
        uid = norm_uuid(urllib.parse.unquote(u.username))
        if not uid:
            return None
        security = _q(q, "security", "auto") or "auto"
        outbound = {"type": "vmess", "uuid": uid,
                    "security": security if security in VMESS_SECURITY else "auto",
                    "alter_id": 0}
        host = _q(q, "host")
        sni = _q(q, "sni") or host
        tls = _tls_block(security, sni, _q(q, "fp"), _q(q, "alpn"),
                         _q(q, "allowInsecure") in ("1", "true"), _q(q, "pbk"), _q(q, "sid"))
        if security in ("tls", "reality") and tls is None:
            return None
        if tls:
            outbound["tls"] = tls
        tr = _transport(_q(q, "type", "tcp"), _q(q, "path", "/"), host, _q(q, "path", ""))
        if tr == "__skip__":
            return None
        if tr:
            outbound["transport"] = tr
        return _finish("vmess", u.hostname, u.port or 443,
                       urllib.parse.unquote(u.fragment), outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Trojan
# --------------------------------------------------------------------------
def parse_trojan(link: str):
    try:
        u = urllib.parse.urlparse(link)
        if not u.hostname:
            return None
        q = urllib.parse.parse_qs(u.query)
        password = urllib.parse.unquote(u.username or "")
        if not password:
            return None
        port = u.port or 443
        net = _q(q, "type", "tcp")
        security = _q(q, "security", "tls")
        host = _q(q, "host")
        sni = _q(q, "sni") or _q(q, "peer") or host
        outbound = {"type": "trojan", "password": password}
        tls = _tls_block(security if security != "none" else "",
                         sni, _q(q, "fp"), _q(q, "alpn"),
                         _q(q, "allowInsecure") in ("1", "true") or _q(q, "insecure") in ("1", "true"))
        if tls:
            outbound["tls"] = tls
        tr = _transport(net, _q(q, "path", "/"), host,
                        _q(q, "serviceName") or _q(q, "path", ""), _q(q, "headerType"))
        if tr == "__skip__":
            return None
        if tr:
            outbound["transport"] = tr
        return _finish("trojan", u.hostname, port,
                       urllib.parse.unquote(u.fragment), outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Shadowsocks
# --------------------------------------------------------------------------
def _parse_ss_credentials(userinfo: str):
    """method:password — چه ساده چه base64 شده."""
    if ":" in userinfo:
        method, password = userinfo.split(":", 1)
        if method in SS_METHODS:
            return method, password
    decoded = b64decode_any(userinfo)
    if ":" in decoded:
        method, password = decoded.split(":", 1)
        if method in SS_METHODS:
            return method, password
    return None, None


def parse_ss(link: str):
    try:
        body = link[len("ss://"):]
        plugin = ""
        if "#" in body:
            body, frag = body.split("#", 1)
        else:
            frag = ""
        if "?" in body:
            body, query = body.split("?", 1)
            qs = urllib.parse.parse_qs(query)
            raw_plugin = _q(qs, "plugin")
            if raw_plugin:
                # plugin=obfs-local;obfs=http;obfs-host=example.com
                plugin = urllib.parse.unquote(raw_plugin)
        remark = urllib.parse.unquote(frag)

        if "@" in body:
            userinfo, hostpart = body.rsplit("@", 1)
            userinfo = urllib.parse.unquote(userinfo)
            method, password = _parse_ss_credentials(userinfo)
            if not method:
                return None
        else:
            decoded = b64decode_any(urllib.parse.unquote(body))
            if "@" not in decoded:
                return None
            userinfo, hostpart = decoded.rsplit("@", 1)
            method, password = _parse_ss_credentials(userinfo)
            if not method:
                return None
        hostpart = hostpart.strip("/")
        if hostpart.startswith("["):
            m = re.match(r"^\[([^\]]+)\]:(\d+)$", hostpart)
            if not m:
                return None
            server, port = m.group(1), int(m.group(2))
        elif ":" in hostpart:
            server, port_s = hostpart.rsplit(":", 1)
            port = int(port_s)
        else:
            return None

        outbound = {"type": "shadowsocks", "method": method, "password": password}
        if plugin:
            pname, _, popts = plugin.partition(";")
            pname = pname.strip()
            if pname in ("obfs-local", "simple-obfs", "v2ray-plugin"):
                if pname in ("obfs-local", "simple-obfs"):
                    pname = "obfs-local"
                    # sing-box خودش Host هدر را از sni جدا نمی‌کند؛ فرمت opts را حفظ می‌کنیم
                outbound["plugin"] = pname
                outbound["plugin_opts"] = popts
            else:
                return None
        return _finish("ss", server, port, remark, outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Hysteria2
# --------------------------------------------------------------------------
def parse_hysteria2(link: str):
    try:
        u = urllib.parse.urlparse(link)
        if not u.hostname:
            return None
        q = urllib.parse.parse_qs(u.query)
        auth = urllib.parse.unquote(u.username or "") or _q(q, "auth")
        if u.password:
            auth = f"{auth}:{urllib.parse.unquote(u.password)}"
        if not auth:
            return None
        outbound = {"type": "hysteria2", "password": auth}
        sni = _q(q, "sni") or _q(q, "peer") or u.hostname
        insecure = _q(q, "insecure") in ("1", "true") or _q(q, "allowInsecure") in ("1", "true")
        tls = _tls_block("tls", sni, "", _q(q, "alpn"), insecure)
        if tls:
            outbound["tls"] = tls
        obfs = _q(q, "obfs")
        if obfs and obfs != "none":
            obfs_pw = _q(q, "obfs-password") or _q(q, "obfs_password")
            if obfs == "salamander" and obfs_pw:
                outbound["obfs"] = {"type": "salamander", "password": obfs_pw}
        return _finish("hysteria2", u.hostname, u.port or 443,
                       urllib.parse.unquote(u.fragment), outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# TUIC
# --------------------------------------------------------------------------
def parse_tuic(link: str):
    try:
        u = urllib.parse.urlparse(link)
        if not u.hostname:
            return None
        q = urllib.parse.parse_qs(u.query)
        uid = norm_uuid(urllib.parse.unquote(u.username or ""))
        password = urllib.parse.unquote(u.password or "")
        if not uid or not password:
            return None
        outbound = {"type": "tuic", "uuid": uid, "password": password}
        cc = _q(q, "congestion_control") or _q(q, "congestion")
        if cc in TUIC_CONGESTION:
            outbound["congestion_control"] = cc
        relay = _q(q, "udp_relay_mode")
        if relay in TUIC_RELAY:
            outbound["udp_relay_mode"] = relay
        tls = _tls_block("tls", _q(q, "sni") or u.hostname, _q(q, "fp"),
                         _q(q, "alpn") or "h3",
                         _q(q, "allow_insecure") in ("1", "true")
                         or _q(q, "allowInsecure") in ("1", "true"))
        if tls:
            outbound["tls"] = tls
        return _finish("tuic", u.hostname, u.port or 443,
                       urllib.parse.unquote(u.fragment), outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# AnyTLS
# --------------------------------------------------------------------------
def parse_anytls(link: str):
    try:
        u = urllib.parse.urlparse(link)
        if not u.hostname:
            return None
        q = urllib.parse.parse_qs(u.query)
        password = urllib.parse.unquote(u.username or "") or _q(q, "password")
        if not password:
            return None
        outbound = {"type": "anytls", "password": password}
        tls = _tls_block("tls", _q(q, "sni") or u.hostname, _q(q, "fp"),
                         _q(q, "alpn"),
                         _q(q, "insecure") in ("1", "true")
                         or _q(q, "allowInsecure") in ("1", "true"))
        if tls:
            outbound["tls"] = tls
        return _finish("anytls", u.hostname, u.port or 443,
                       urllib.parse.unquote(u.fragment), outbound, link)
    except Exception:
        return None


# --------------------------------------------------------------------------
# ورودی عمومی
# --------------------------------------------------------------------------
_PARSERS = (
    ("vmess://", parse_vmess),
    ("vless://", parse_vless),
    ("trojan://", parse_trojan),
    ("ss://", parse_ss),
    ("hysteria2://", parse_hysteria2),
    ("hy2://", parse_hysteria2),
    ("tuic://", parse_tuic),
    ("anytls://", parse_anytls),
)


def parse_link(link: str):
    """تجزیه یک لینک؛ None یعنی پشتیبانی نمی‌شود یا معتبر نیست."""
    if not isinstance(link, str):
        return None
    link = link.strip().strip("\u200b\ufeff")
    if not link or link.startswith("#") or link.startswith("//"):
        return None
    for prefix, fn in _PARSERS:
        if link.startswith(prefix):
            try:
                return fn(link)
            except Exception:
                return None
    return None
