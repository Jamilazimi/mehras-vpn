"""
تست واقعیِ گره‌ها از داخل تونل.

روش: به‌جای اجرای یک پروسه‌ی جداگانه برای هر کانفیگ (که نسخه‌ی قبلی را کند و
ناتوان کرده بود)، برای هر «دسته» یک پروسه‌ی sing-box با چندین inbound/outbound
ساخته می‌شود؛ هر گره روی یک پورت SOCKS محلی جداگانه منتشر می‌شود و همه‌ی
پورت‌ها هم‌زمان و موازی تست می‌شوند. نتیجه: ۳۰ گره در ~۴ ثانیه به‌جای ~۹۰ ثانیه.
"""
import json
import os
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

from app.config import SB_DIR
from app.core import engine
from app.utils.logger import log

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

CONNECTIVITY_URL = "https://www.gstatic.com/generate_204"
# تأیید دوم از یک مقصد متفاوت: بعضی مسیرها فقط برای یک دامنه باز می‌شوند
CONFIRM_URL = "https://www.cloudflare.com/cdn-cgi/trace"


# ---------------------------------------------------------------------------
# تخصیص پورت
# ---------------------------------------------------------------------------
class PortPool:
    """تخصیص پورت از یک بازه‌ی خصوصی و خارج از بازه‌ی پویای ویندوز.

    نکته‌ی مهم: bind(port=0) روی ویندوز معمولاً همان پورت قبلی را برمی‌گرداند،
    بنابراین شمارنده‌ی ترتیبی با تست واقعی bind استفاده می‌شود.
    """

    START = 21000
    END = 32000

    def __init__(self):
        self._lock = threading.Lock()
        self._next = self.START
        self._used = set()

    def acquire(self) -> int:
        with self._lock:
            span = self.END - self.START
            for _ in range(span):
                port = self._next
                self._next = self.START if port + 1 >= self.END else port + 1
                if port in self._used:
                    continue
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.bind(("127.0.0.1", port))   # بدون SO_REUSEADDR = تست انحصاری
                except OSError:
                    continue
                finally:
                    s.close()
                self._used.add(port)
                return port
            raise RuntimeError("no free local port")

    def release(self, port: int):
        with self._lock:
            self._used.discard(port)


PORTS = PortPool()


# ---------------------------------------------------------------------------
# پیش‌فیلتر TCP (بدون تونل) — فقط برای حذف گره‌های مرده
# ---------------------------------------------------------------------------
def tcp_ping(host: str, port: int, timeout: float):
    try:
        start = time.perf_counter()
        s = socket.create_connection((host, port), timeout=timeout)
        try:
            # بستن با RST تا پورت محلی فوراً آزاد شود (جلوگیری از اشباع پورت)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except Exception:
            pass
        s.close()
        return round((time.perf_counter() - start) * 1000, 1)
    except Exception:
        return None


def tcp_prefilter(nodes, timeout=1.8, workers=48, deadline=45.0,
                  max_alive=400, stop_fn=None) -> list:
    """حذف سریع گره‌هایی که پورتشان از این شبکه باز نیست.

    تعداد worker عمداً معتدل است: اسکن پرهیاهو باعث می‌شود ISP موقتاً
    اتصال‌ها را drop کند و نتیجه‌ی تست بدتر از واقعیت شود.
    """
    if not nodes:
        return []
    start = time.perf_counter()
    alive = []
    done = [0]
    total = len(nodes)

    def check(node):
        latency = tcp_ping(node["server"], node["port"], timeout)
        node["tcp_ping"] = latency
        return node, latency is not None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(check, n) for n in nodes]
        for fut in as_completed(futures):
            done[0] += 1
            if stop_fn and stop_fn():
                for f in futures:
                    f.cancel()
                break
            try:
                node, ok = fut.result()
                if ok:
                    alive.append(node)
            except Exception:
                pass
            if len(alive) >= max_alive:
                log.info(f"tcp_prefilter: max_alive {max_alive} reached")
                for f in futures:
                    f.cancel()
                break
            if time.perf_counter() - start > deadline:
                log.info(f"tcp_prefilter: deadline at {done[0]}/{total}")
                for f in futures:
                    f.cancel()
                break

    alive.sort(key=lambda n: n.get("tcp_ping") or 9e9)
    log.info(f"tcp_prefilter: {len(alive)}/{total} alive in "
             f"{time.perf_counter() - start:.1f}s")
    return alive


# ---------------------------------------------------------------------------
# ساخت کانفیگ دسته‌ای
# ---------------------------------------------------------------------------
def _batch_config(nodes, ports):
    inbounds, outbounds, rules = [], [], []
    for i, (node, port) in enumerate(zip(nodes, ports)):
        inbounds.append({"type": "socks", "tag": f"in-{i}",
                         "listen": "127.0.0.1", "listen_port": port})
        ob = json.loads(json.dumps(node["outbound"]))
        ob["tag"] = f"n-{i}"
        outbounds.append(ob)
        rules.append({"inbound": [f"in-{i}"], "outbound": f"n-{i}"})
    outbounds.append({"type": "direct", "tag": "direct"})
    return {
        "log": {"level": "error", "timestamp": False},
        "dns": {"servers": [{"tag": "local", "type": "local"}], "final": "local"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {
            "rules": rules,
            "final": "direct",
            "auto_detect_interface": True,
            "default_domain_resolver": "local",
        },
    }


def _wait_ports(ports, proc, timeout=5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        opened = 0
        for port in ports:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                    opened += 1
            except Exception:
                pass
        if opened == len(ports):
            return True
        time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# پروب HTTP از داخل تونل
# ---------------------------------------------------------------------------
def http_via_socks(port, url, timeout=6.0):
    """(status, latency_ms, bytes) — status=None یعنی اتصال برقرار نشد."""
    proxies = {"http": f"socks5h://127.0.0.1:{port}",
               "https": f"socks5h://127.0.0.1:{port}"}
    start = time.perf_counter()
    try:
        r = requests.get(url, proxies=proxies, timeout=timeout, headers={
            "User-Agent": UA, "Accept": "*/*", "Connection": "close"},
            allow_redirects=False, stream=True)
        status = r.status_code
        body = b""
        try:
            body = next(r.iter_content(2048), b"") or b""
        except Exception:
            pass
        r.close()
        return status, round((time.perf_counter() - start) * 1000, 1), len(body)
    except Exception:
        return None, None, 0


def speed_via_socks(port, url, seconds=2.0):
    """سرعت دانلود (کیلوبیت بر ثانیه) با محدودیت زمانی."""
    proxies = {"http": f"socks5h://127.0.0.1:{port}",
               "https": f"socks5h://127.0.0.1:{port}"}
    start = time.perf_counter()
    total = 0
    try:
        with requests.get(url, proxies=proxies, timeout=12, stream=True,
                          headers={"User-Agent": UA}, verify=False) as r:
            if r.status_code >= 400:
                return None
            for chunk in r.iter_content(1 << 16):
                total += len(chunk)
                if time.perf_counter() - start >= seconds:
                    break
    except Exception:
        return None
    elapsed = time.perf_counter() - start
    if elapsed < 0.4 or total < 50_000:
        return None
    return round(total * 8 / 1000 / elapsed, 1)


# ---------------------------------------------------------------------------
# اجرای یک دسته
# ---------------------------------------------------------------------------
def _acquire_ports(count):
    return [PORTS.acquire() for _ in range(count)]


def _release_ports(ports):
    for p in ports:
        try:
            PORTS.release(p)
        except Exception:
            pass


def _bad_outbound_index(err: str, count: int):
    marker = "initialize outbound["
    if marker not in err:
        return None
    try:
        idx = int(err.split(marker, 1)[1].split("]", 1)[0])
    except Exception:
        return None
    return idx if 0 <= idx < count else None


def _err_text(proc) -> str:
    path = getattr(proc, "_err", None) if proc is not None else None
    if not path:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _start_batch(nodes, stop_fn):
    """آماده‌سازی و اجرای یک دسته.

    خروجی: (proc, ports) یا (None, []) در صورت شکست کامل.
    گره‌هایی که هسته را از کار می‌اندازند (در check یا در اجرا) حذف می‌شوند.
    """
    drop_budget = 5
    port_retry = 3
    while nodes and port_retry > 0:
        if stop_fn and stop_fn():
            return None, []
        ports = _acquire_ports(len(nodes))
        config = _batch_config(nodes, ports)
        ok, err = engine.check_config(config)
        if not ok:
            bad = _bad_outbound_index(err, len(nodes))
            _release_ports(ports)
            if bad is not None and drop_budget > 0:
                log.warning(f"drop invalid node ({nodes[bad].get('protocol')}): "
                            f"{err[:110]}")
                nodes.pop(bad)
                drop_budget -= 1
                continue
            log.warning(f"batch config invalid: {err[:160]}")
            return None, []

        proc = _spawn(config, tag=f"p{ports[0]}")
        if proc is not None and _wait_ports(ports, proc):
            return proc, ports

        # اجرا شکست خورد: علت را از لاگ هسته بخوان
        text = _err_text(proc)
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            _cleanup_cfg(proc)
        _release_ports(ports)

        bad = _bad_outbound_index(text, len(nodes))
        if bad is not None and drop_budget > 0:
            log.warning(f"drop node ({nodes[bad].get('protocol')}) after start "
                        f"error: {text.strip().splitlines()[-1][:110]}")
            nodes.pop(bad)
            drop_budget -= 1
            continue
        port_retry -= 1
        if port_retry <= 0:
            log.warning(f"batch failed to start: {text.strip()[-200:]}")
    return None, []


def _run_batch(nodes, timeout, do_speed, speed_secs, speed_url, stop_fn,
               target_sites=None):
    """تست یک دسته از گره‌ها. لیست گره‌های تست‌شده برمی‌گرداند."""
    nodes = [n for n in nodes if n]
    if not nodes or (stop_fn and stop_fn()):
        return []

    proc, ports = _start_batch(nodes, stop_fn)
    if proc is None:
        return [dict(n, working=False, latency=None, speed_kbps=None,
                     error="core-start") for n in nodes]

    port_by_index = {i: ports[i] for i in range(len(nodes))}
    try:
        def test(index):
            node = nodes[index]
            if stop_fn and stop_fn():
                return None
            status, latency, _ = http_via_socks(port_by_index[index],
                                                CONNECTIVITY_URL, timeout)
            node["latency"] = latency
            node["http_status"] = status
            node["working"] = status in (200, 204)
            node["error"] = "" if node["working"] else (
                f"HTTP {status}" if status else "no-connect")
            return node

        results = []
        with ThreadPoolExecutor(max_workers=min(24, len(nodes))) as ex:
            futures = [ex.submit(test, i) for i in range(len(nodes))]
            for fut in as_completed(futures):
                try:
                    node = fut.result()
                    if node:
                        results.append(node)
                except Exception:
                    pass

        # --- تأیید از مقصد دوم: گره‌های «یک‌بارمصرف» حذف می‌شوند ---
        first_pass = [(i, n) for i, n in enumerate(nodes) if n.get("working")]

        def confirm(pair):
            idx, node = pair
            if stop_fn and stop_fn():
                return
            status2, latency2, _ = http_via_socks(
                port_by_index[idx], CONFIRM_URL, timeout)
            if status2 is not None and status2 < 400:
                node["success_rate"] = 1.0
                if latency2:
                    node["latency"] = round(
                        ((node.get("latency") or latency2) + latency2) / 2, 1)
            else:
                node["success_rate"] = 0.5
                node["confirm_status"] = status2

        if first_pass:
            with ThreadPoolExecutor(max_workers=min(12, len(first_pass))) as ex:
                list(ex.map(confirm, first_pass))

        working = [(i, n) for i, n in first_pass
                   if n.get("success_rate", 1.0) >= 1.0]

        # --- آزمون سایت‌های هدف (تلگرام/اینستاگرام/یوتیوب) ---
        if target_sites and working:
            def check_sites(pair):
                idx, node = pair
                if stop_fn and stop_fn():
                    return
                result = probe_targets(port_by_index[idx], target_sites,
                                       timeout=min(timeout, 10.0), retries=0)
                node["targets"] = result
                node["targets_ok"] = sum(1 for v in result.values() if v.get("ok"))

            with ThreadPoolExecutor(max_workers=min(6, len(working))) as ex:
                list(ex.map(check_sites, working))

        if do_speed and working:
            def do_speed_one(pair):
                idx, node = pair
                if stop_fn and stop_fn():
                    return
                if (node.get("latency") or 9999) > 3000:
                    node["speed_kbps"] = None
                    return
                node["speed_kbps"] = speed_via_socks(
                    port_by_index[idx], speed_url, speed_secs)

            with ThreadPoolExecutor(max_workers=min(8, len(working))) as ex:
                list(ex.map(do_speed_one, working))
        for node in results:
            node.setdefault("speed_kbps", None)
            node.setdefault("success_rate", 1.0 if node.get("working") else 0.0)
        return results
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _cleanup_cfg(proc)
        _release_ports(ports)


_BATCH_LOCK = threading.Lock()


def _spawn(config, tag=""):
    """اجرای یک پروسه‌ی sing-box فقط برای تست (لاگ جدا، بدون TUN)."""
    import subprocess
    import sys
    unique = f"{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000) % 100000}"
    path = SB_DIR / f"_probe_{unique}.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    err_path = SB_DIR / f"_probe_err_{unique}.log"
    try:
        fh = open(err_path, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [str(engine.SB_EXE), "run", "-c", str(path)],
            stdout=fh, stderr=subprocess.STDOUT,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
    except Exception as e:
        log.error(f"probe spawn failed: {e}")
        return None
    proc._cfg = path      # type: ignore
    proc._err = err_path  # type: ignore
    proc._fh = fh         # type: ignore
    log.debug(f"batch {tag} spawned pid={proc.pid} ports="
              f"{[ib['listen_port'] for ib in config['inbounds']][:2]}... "
              f"n={len(config['inbounds'])}")
    return proc


def _cleanup_cfg(proc):
    path = getattr(proc, "_cfg", None)
    if path:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    fh = getattr(proc, "_fh", None)
    if fh:
        try:
            fh.close()
        except Exception:
            pass
    err_path = getattr(proc, "_err", None)
    if err_path:
        try:
            text = err_path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                log.debug(f"probe batch log: {text[-400:]}")
            err_path.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# API عمومی
# ---------------------------------------------------------------------------
def probe_many(nodes, batch_size=24, concurrency=2, timeout=6.0,
               do_speed=True, speed_secs=2.0,
               speed_url="https://speed.cloudflare.com/__down?bytes=5000000",
               progress_cb=None, stop_fn=None, retry_failed=True,
               target_sites=None) -> list:
    """تست موازی همه‌ی گره‌ها در دسته‌های موازی."""
    nodes = [n for n in nodes if n]
    if not nodes:
        return []
    batches = [nodes[i:i + batch_size] for i in range(0, len(nodes), batch_size)]
    total = len(nodes)
    done = [0]
    tested = []
    lock = threading.Lock()

    def run(batch):
        return _run_batch(batch, timeout, do_speed, speed_secs, speed_url,
                          stop_fn, target_sites)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = [ex.submit(run, b) for b in batches]
        for fut in as_completed(futures):
            if stop_fn and stop_fn():
                for f in futures:
                    f.cancel()
                break
            try:
                res = fut.result()
            except Exception as e:
                log.warning(f"batch failed: {e}")
                res = []
            with lock:
                tested.extend(res)
                done[0] += len(res)
                if progress_cb:
                    progress_cb(min(done[0], total), total,
                                f"تست تونل {min(done[0], total)}/{total}")

    # --- شانس دوم: گره‌هایی که فقط «اتصال برقرار نشد» داشتند یک بار دیگر ---
    if retry_failed and not (stop_fn and stop_fn()):
        failed = [n for n in tested
                  if not n.get("working") and n.get("error") == "no-connect"]
        if failed:
            log.info(f"probe_many: retrying {len(failed)} failed nodes")
            retry = probe_many(failed, batch_size=batch_size,
                               concurrency=concurrency, timeout=timeout + 2.0,
                               do_speed=False, speed_secs=speed_secs,
                               speed_url=speed_url, progress_cb=None,
                               stop_fn=stop_fn, retry_failed=False)
            fixed = {n["id"]: n for n in retry}
            for i, node in enumerate(tested):
                if node["id"] in fixed and fixed[node["id"]].get("working"):
                    tested[i] = fixed[node["id"]]
            seen = {n["id"] for n in tested}
            tested.extend(n for n in retry if n["id"] not in seen)

    log.info(f"probe_many: {len(tested)} tested, "
             f"{sum(1 for n in tested if n.get('working'))} working")
    return tested


def probe_targets(port, targets, timeout=8.0, retries=1, parallel=True) -> dict:
    """آزمایش سایت‌های هدف (تلگرام/اینستاگرام/یوتیوب) از داخل تونل.

    هر سایت در صورت شکست یک بار دیگر (با مهلت بیشتر) امتحان می‌شود تا یک
    کندی گذرا، نتیجه را «بسته» نشان ندهد. در حالت parallel سه سایت هم‌زمان
    بررسی می‌شوند تا زمان اتصال کوتاه بماند.
    """
    out = {}

    def one(target):
        name = target.get("name") or target.get("url", "")
        url = target.get("probe") or target.get("url")
        status = latency = None
        for attempt in range(retries + 1):
            status, latency, _ = http_via_socks(port, url, timeout + attempt * 4)
            if status is not None and status < 500:
                break
            time.sleep(0.5)
        return name, {"ok": status is not None and status < 500,
                      "status": status, "latency": latency}

    if parallel and len(targets) > 1:
        with ThreadPoolExecutor(max_workers=len(targets)) as ex:
            for name, info in ex.map(one, targets):
                out[name] = info
    else:
        for target in targets:
            name, info = one(target)
            out[name] = info
    return out
