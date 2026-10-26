"""
کنترلر VPN — تمام کارهای سنگین در یک رشته‌ی مستقل انجام می‌شود تا پنجره
هیچ‌وقت فریز نشود.

چرخه‌ی کار:
  ۱) اگر از اجرای قبل گره‌ی سالمی ذخیره شده، همان اول به آن وصل می‌شویم
     (اتصال در چند ثانیه).
  ۲) در پس‌زمینه اسکن تازه انجام می‌شود: منابع تست‌شده ← فیلتر TCP ←
     تست واقعی تونل ← تست سرعت ← انتخاب بهترین.
  ۳) اتصال با پایش سلامت هر چند ثانیه؛ در صورت مرگ گره، خودکار به گره‌ی
     بعدی منتقل می‌شود.
"""
import json
import threading
import time
import urllib.request

from PySide6.QtCore import QThread, Signal

from app.config import DEFAULT_SETTINGS, SOURCES, APP_VERSION
from app.core import engine, probe, selector, sources
from app.utils import system_proxy
from app.utils.logger import log

STATS_URL = "http://127.0.0.1:{port}/connections"


def _default_settings():
    return json.loads(json.dumps(DEFAULT_SETTINGS))


class VPNController(QThread):
    # --- سیگنال‌ها ---
    status = Signal(str)                 # پیام متنی وضعیت
    progress = Signal(str, int, int)     # (مرحله، فعلی، کل)
    nodes_updated = Signal(list)         # لیست گره‌ها برای جدول
    connected = Signal(dict)             # گره‌ی متصل‌شده
    disconnected = Signal()
    stats = Signal(dict)                 # آمار زنده (سرعت/پینگ/حجم/زمان)
    targets = Signal(dict)               # وضعیت تلگرام/اینستاگرام/یوتیوب
    error = Signal(str)
    state_changed = Signal(str)          # idle/scanning/connecting/connected/error

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = selector.settings_with_defaults(settings or {})
        self.nodes = []
        self.current = None
        self._state = "idle"

        self._lock = threading.Lock()
        self._stop_flag = False
        self._cmd_connect_best = False
        self._cmd_refresh = False
        self._cmd_deep = False
        self._cmd_disconnect = False
        self._pending_node = None

        self._scan_thread = None
        self._op_lock = threading.RLock()
        self._last_health = 0.0
        self._last_refresh = 0.0
        self._fail_count = 0
        self._connected_at = 0.0
        self._traffic = {"down": 0, "up": 0, "last_t": 0.0, "rate_down": 0.0,
                         "rate_up": 0.0, "total_down": 0, "total_up": 0}
        self._targets = {}

    # ------------------------------------------------------------------ API
    def request_connect_best(self):
        with self._lock:
            self._cmd_connect_best = True

    def request_connect(self, node):
        with self._lock:
            self._pending_node = node

    def request_disconnect(self):
        with self._lock:
            self._cmd_disconnect = True

    def request_refresh(self, deep=False):
        with self._lock:
            self._cmd_refresh = True
            self._cmd_deep = bool(deep)

    def update_settings(self, settings: dict):
        self.settings = selector.settings_with_defaults(settings)
        if self.current and self.settings.get("set_system_proxy"):
            system_proxy.set_proxy("127.0.0.1", self.settings["mixed_port"])

    def stop(self):
        self._stop_flag = True

    @property
    def state(self):
        return self._state

    def _set_state(self, state, message=None):
        self._state = state
        if message:
            self.status.emit(message)
        self.state_changed.emit(state)

    # ------------------------------------------------------- اسکن پس‌زمینه
    def _spawn_scan(self, deep=False, connect_after=True):
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self._scan_thread = threading.Thread(
            target=self._scan_worker, args=(deep, connect_after), daemon=True)
        self._scan_thread.start()

    def _scan_worker(self, deep=False, connect_after=True):
        try:
            self._do_scan(deep, connect_after)
        except Exception as e:
            log.error(f"scan failed: {e}")
            self.error.emit(f"خطا در اسکن: {e}")

    def _emit_progress(self, phase, cur, total):
        self.progress.emit(phase, int(cur), int(total))

    # ---------------------------------------------------------- کمک‌های اسکن
    def _probe_nodes(self, nodes, budget, label, do_speed=False,
                     target_sites=None, deadline=40, max_alive=None,
                     concurrency=None, skip_ids=None, retry_failed=True):
        """پیش‌فیلتر TCP + تست واقعی تونل روی یک گروه از گره‌ها."""
        if not nodes or self._stop_flag:
            return []
        if skip_ids:
            nodes = [n for n in nodes if n["id"] not in skip_ids]
        if not nodes:
            return []
        alive = probe.tcp_prefilter(
            selector.order_by_health(nodes),
            timeout=1.8, workers=48, deadline=deadline,
            max_alive=max_alive or max(120, budget),
            stop_fn=lambda: self._stop_flag)
        if self._stop_flag or not alive:
            return []
        self.status.emit(f"{label}: {len(alive)} گره پاسخ داد — تست تونل...")
        return probe.probe_many(
            alive[:budget],
            batch_size=int(self.settings.get("batch_size", 24)),
            concurrency=concurrency or int(self.settings.get("concurrency", 2)),
            timeout=float(self.settings.get("test_timeout_sec", 6.0)),
            do_speed=do_speed,
            speed_secs=float(self.settings.get("speed_test_sec", 2.0)),
            speed_url=self.settings.get("speed_test_url"),
            target_sites=target_sites,
            retry_failed=retry_failed,
            progress_cb=lambda c, t, m: self._emit_progress(label, c, t),
            stop_fn=lambda: self._stop_flag)

    def _merge_and_publish(self, collected, tested):
        if not tested:
            return collected
        known = {n["id"] for n in collected}
        collected.extend(n for n in tested if n["id"] not in known)
        self.nodes = selector.rank_all(collected)
        self.nodes_updated.emit(list(self.nodes))
        try:
            selector.update_source_health(tested)
        except Exception:
            pass
        return collected

    def _do_scan(self, deep=False, connect_after=True):
        """اسکن مرحله‌ای: اشتراک شخصی ← منابع تست‌شده (سریع) ← حجیم."""
        if self._stop_flag:
            return
        if not self.current:
            self._set_state("scanning", "شروع جستجوی گره‌های سالم...")
        else:
            self.status.emit("به‌روزرسانی گره‌ها در پس‌زمینه...")
        self._last_refresh = time.time()
        collected = []
        tested_ids = set()
        budget = int(self.settings.get("max_test_nodes", 180))

        # ---------- ۱) اشتراک/کانفیگ شخصی کاربر (بالاترین اولویت) ----------
        try:
            custom_entries = sources.load_custom_entries()
        except Exception:
            custom_entries = []
        if custom_entries and not self._stop_flag:
            self.status.emit("بررسی اشتراک شخصی شما...")
            try:
                custom_nodes = sources.fetch_all(
                    sources=custom_entries, include_custom=False,
                    stop_fn=lambda: self._stop_flag,
                    deadline_sec=30,
                    progress_cb=lambda d, t, m: self._emit_progress("اشتراک شخصی", d, t))
            except Exception as e:
                log.warning(f"custom sources failed: {e}")
                custom_nodes = []
            if custom_nodes:
                tested = self._probe_nodes(
                    custom_nodes, min(48, len(custom_nodes)), "اشتراک شخصی",
                    do_speed=False, deadline=18, max_alive=60, concurrency=2)
                collected = self._merge_and_publish(collected, tested)
                tested_ids.update(n["id"] for n in tested)
                working_custom = selector.rank(tested)
                if working_custom:
                    self.status.emit(
                        f"{len(working_custom)} گره از اشتراک شخصی سالم است.")
                    if not self.current and connect_after:
                        for node in working_custom[:3]:
                            if self._stop_flag or self.current:
                                break
                            if self._connect_node(node):
                                break

        # ---------- ۲) مرحله‌ی سریع: منابع تست‌شده، بودجه‌ی کوچک ----------
        tested_srcs = [s for s in SOURCES if s["kind"] == "tested"]
        self.status.emit("در حال دریافت منابع تست‌شده...")
        got = sources.fetch_all(
            sources=tested_srcs, include_custom=False,
            stop_fn=lambda: self._stop_flag,
            progress_cb=lambda d, t, m: self._emit_progress("منابع تست‌شده", d, t))
        if self._stop_flag:
            return

        if got and not self.current and connect_after:
            quick = self._probe_nodes(
                got, 40, "اتصال سریع", do_speed=False,
                deadline=15, max_alive=56, concurrency=4,
                skip_ids=tested_ids, retry_failed=False)
            collected = self._merge_and_publish(collected, quick)
            tested_ids.update(n["id"] for n in quick)
            quick_working = selector.rank(quick)
            if quick_working:
                self.status.emit("گره‌ی سالم پیدا شد — اتصال سریع...")
                if self._connect_node(quick_working[0]):
                    # ادامه‌ی اسکن در پس‌زمینه، بدون قطع اتصال فعلی
                    pass
        if self._stop_flag:
            return

        # ---------- ۳) اسکن کامل منابع تست‌شده ----------
        if got:
            full = self._probe_nodes(
                got, budget, "تست تونل", do_speed=False,
                deadline=35, max_alive=max(100, budget),
                skip_ids=tested_ids)
            collected = self._merge_and_publish(collected, full)
            tested_ids.update(n["id"] for n in full)

        # ---------- ۴) در صورت کمبود، منابع حجیم ----------
        working_now = selector.rank(collected)
        need_bulk = deep or len(working_now) < 6
        if need_bulk and not self._stop_flag:
            bulk_srcs = [s for s in SOURCES if s["kind"] == "bulk"]
            self.status.emit("دریافت منابع حجیم برای یافتن گزینه‌های بیشتر...")
            bulk_nodes = sources.fetch_all(
                sources=bulk_srcs, include_custom=False,
                stop_fn=lambda: self._stop_flag,
                progress_cb=lambda d, t, m: self._emit_progress("منابع حجیم", d, t))
            if self._stop_flag:
                return
            if bulk_nodes:
                extra = self._probe_nodes(
                    bulk_nodes, max(80, budget // 2), "تست منابع حجیم",
                    do_speed=False, deadline=40, max_alive=140,
                    skip_ids=tested_ids)
                collected = self._merge_and_publish(collected, extra)

        working = selector.rank(collected)
        if not working:
            self._set_state("idle", "هیچ گره‌ی سالمی پیدا نشد. دوباره تلاش کنید.")
            self.error.emit("هیچ گره‌ی سالمی پیدا نشد — دوباره تلاش کنید.")
            return

        # --- تست سرعت + سایت‌های هدف برای گره‌های برتر ---
        top = working[:8]
        self.status.emit("تست سرعت و سایت‌های هدف برای گره‌های برتر...")
        try:
            probe.probe_many(top, batch_size=min(8, len(top)), concurrency=1,
                             timeout=8.0, do_speed=True,
                             speed_secs=float(self.settings.get("speed_test_sec", 2.0)),
                             speed_url=self.settings.get("speed_test_url"),
                             retry_failed=False, stop_fn=lambda: self._stop_flag,
                             target_sites=self.settings.get("target_sites"))
        except Exception as e:
            log.warning(f"speed phase failed: {e}")
        if self._stop_flag:
            return

        self.nodes = selector.rank_all(collected)
        self.nodes_updated.emit(list(self.nodes))
        selector.save_cache(collected)
        selector.save_servers(self.nodes)
        self._last_refresh = time.time()
        best = (selector.rank(collected) or [None])[0]
        if best:
            self.status.emit(
                f"{len(working)} گره سالم — بهترین: {best.get('latency')}ms"
                + (f" / {best.get('speed_kbps')}kbps" if best.get("speed_kbps") else ""))
        self._emit_progress("پایان", 1, 1)

        if connect_after and best and not self._stop_flag:
            if not self.current:
                self._connect_node(best)
            elif self.settings.get("auto_switch"):
                current_score = selector.score(self.current)
                best_score = selector.score(best)
                current_lat = self.current.get("latency") or 9999
                better = (current_score < 0 or best_score > current_score * 1.2)
                clearly_better = current_lat > 1500 and (best.get("latency") or 9999) < 900
                if better or clearly_better:
                    self.status.emit("گره‌ی بهتری پیدا شد — جابه‌جایی...")
                    self._connect_node(best)

    # ------------------------------------------------------------ اتصال
    def _connect_node(self, node, allow_tun=True) -> bool:
        with self._op_lock:
            return self._connect_node_inner(node, allow_tun)

    def _connect_node_inner(self, node, allow_tun=True) -> bool:
        if not node or self._stop_flag:
            return False
        self._set_state("connecting",
                        f"اتصال به {node.get('remark', '')[:40]}...")
        use_tun = (self.settings.get("mode") == "tun" and allow_tun
                   and engine.has_tun_driver())
        if self.settings.get("mode") == "tun" and not use_tun:
            self.status.emit("درایور TUN در دسترس نیست — حالت پروکسی استفاده می‌شود.")

        mixed = int(self.settings.get("mixed_port", 10808))
        http_port = int(self.settings.get("http_port", 10809))
        config = engine.build_config(
            [node], mixed, http_port, tun=use_tun,
            bypass_iran=bool(self.settings.get("bypass_iran", True)),
            stats_port=int(self.settings.get("stats_port", 19090)))
        ok, err = engine.check_config(config)
        if not ok:
            log.warning(f"config rejected for {node.get('server')}: {err[:150]}")
            node["working"] = False
            node["error"] = "config"
            self.error.emit("کانفیگ این گره پذیرفته نشد؛ گره‌ی بعدی امتحان می‌شود.")
            return False

        started = engine.start(config, wait_port=mixed)
        if not started and use_tun:
            # TUN اغلب به دسترسی مدیر نیاز دارد؛ بی‌صدا به حالت پروکسی برگرد
            self.status.emit("حالت TUN اجرا نشد (دسترسی مدیر لازم است) — "
                             "اتصال در حالت پروکسی...")
            config = engine.build_config([node], mixed, http_port, tun=False,
                                         bypass_iran=bool(self.settings.get("bypass_iran", True)),
                                         stats_port=int(self.settings.get("stats_port", 19090)))
            started = engine.start(config, wait_port=mixed)
            use_tun = False
        if not started:
            node["working"] = False
            node["error"] = "core-start"
            self.error.emit("هسته بالا نیامد؛ گره‌ی بعدی امتحان می‌شود.")
            log.error(f"connect failed: {engine.tail_log(12)}")
            return False

        # --- راستی‌آزمایی واقعی تونل: بالا آمدن هسته کافی نیست ---
        status, latency, _ = probe.http_via_socks(
            mixed, self.settings.get("connectivity_probe"), timeout=9)
        if status not in (200, 204):
            log.warning(f"tunnel check failed for {node.get('server')} "
                        f"(status={status})")
            node["working"] = False
            node["error"] = "tunnel-dead"
            engine.stop()
            self.error.emit("این گره تونل نساخت؛ گره‌ی بعدی امتحان می‌شود.")
            return False
        node["latency"] = latency
        node["working"] = True

        # --- آیا سایت‌های هدف (تلگرام/اینستاگرام/یوتیوب) از این گره باز می‌شوند؟ ---
        target_result = {}
        try:
            target_result = probe.probe_targets(
                mixed, self.settings.get("target_sites", []),
                timeout=7.0, retries=0, parallel=True)
        except Exception as e:
            log.warning(f"target verification failed: {e}")
        if target_result:
            ok_count = sum(1 for v in target_result.values() if v.get("ok"))
            node["targets"] = target_result
            node["targets_ok"] = ok_count
            if ok_count < 2:
                log.warning(f"target sites unreachable via {node.get('server')} "
                            f"({ok_count}/3)")
                node["working"] = False
                node["error"] = "targets"
                engine.stop()
                self.error.emit("این گره سایت‌های هدف را باز نمی‌کند؛ گره‌ی بعدی...")
                return False
            self._targets = target_result
            self.targets.emit(target_result)

        if self.settings.get("set_system_proxy"):
            system_proxy.set_proxy("127.0.0.1", mixed)

        self.current = node
        self._connected_at = time.time()
        self._fail_count = 0
        self._last_health = time.time()
        self._traffic = {"down": 0, "up": 0, "last_t": 0.0, "rate_down": 0.0,
                         "rate_up": 0.0, "total_down": 0, "total_up": 0}
        self._set_state("connected",
                        f"متصل به {node.get('remark', '')[:40]}"
                        + (" (کل سیستم)" if use_tun else ""))
        self.connected.emit(node)
        if not target_result:
            # اگر آزمون سایت‌ها در مرحله‌ی اتصال انجام نشد، جداگانه انجام شود
            threading.Thread(target=self._check_targets, args=(mixed,),
                             daemon=True).start()
        return True

    def _check_targets(self, mixed_port):
        try:
            result = probe.probe_targets(
                mixed_port, self.settings.get("target_sites", []), timeout=10)
            self._targets = result
            self.targets.emit(result)
        except Exception as e:
            log.warning(f"target probe failed: {e}")

    def _disconnect(self, message="قطع شد"):
        with self._op_lock:
            try:
                engine.stop()
            except Exception:
                pass
            if self.settings.get("set_system_proxy"):
                system_proxy.clear_proxy()
            self.current = None
            self._connected_at = 0.0
            self._set_state("idle", message)
            self.disconnected.emit()

    # --------------------------------------------------- پایش سلامت/آمار
    def _poll_traffic(self):
        url = STATS_URL.format(port=int(self.settings.get("stats_port", 19090)))
        try:
            with urllib.request.urlopen(url, timeout=2.5) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
        except Exception:
            return
        now = time.time()
        down = int(data.get("downloadTotal") or 0)
        up = int(data.get("uploadTotal") or 0)
        prev = self._traffic
        dt = now - (prev.get("last_t") or now)
        rate_down = rate_up = 0.0
        if dt > 0.2 and prev.get("last_t"):
            rate_down = max(0.0, (down - prev["down"]) / dt)
            rate_up = max(0.0, (up - prev["up"]) / dt)
        self._traffic = {"down": down, "up": up, "last_t": now,
                         "rate_down": rate_down, "rate_up": rate_up,
                         "total_down": down, "total_up": up}
        self.stats.emit(self._stats_payload())

    def _stats_payload(self, latency=None):
        t = self._traffic
        return {
            "rate_down": round(t.get("rate_down", 0.0), 1),
            "rate_up": round(t.get("rate_up", 0.0), 1),
            "total_down": t.get("down", 0),
            "total_up": t.get("up", 0),
            "latency": latency,
            "uptime": int(time.time() - self._connected_at) if self._connected_at else 0,
        }

    def _health_tick(self):
        if not self.current:
            return
        if self._scan_thread and self._scan_thread.is_alive():
            return                      # وسط اسکن، اتصال را به هم نزن
        interval = max(5, int(self.settings.get("health_check_seconds", 20)))
        if time.time() - self._last_health < interval:
            return
        self._last_health = time.time()
        if not engine.is_running():
            log.warning("core died — reconnect")
            self._failover()
            return
        mixed = int(self.settings.get("mixed_port", 10808))
        status, latency, _ = probe.http_via_socks(
            mixed, self.settings.get("connectivity_probe"), timeout=8)
        if status in (200, 204):
            self._fail_count = 0
            self.stats.emit(self._stats_payload(latency))
        else:
            self._fail_count += 1
            log.warning(f"health check failed ({self._fail_count})")
            if self._fail_count >= 2:
                self._failover()

    def _failover(self):
        failed = self.current
        if failed:
            failed["working"] = False
            failed["error"] = "unstable"
        working = [n for n in selector.rank(self.nodes)
                   if not failed or n["id"] != failed["id"]]
        for node in working[:3]:
            if self._stop_flag:
                return
            self.status.emit(f"گره‌ی فعلی ناپایدار است — تلاش با "
                             f"{node.get('remark', '')[:30]}...")
            if self._connect_node(node):
                selector.save_cache(
                    [n for n in self.nodes if n.get("working")])
                return
        self.status.emit("هیچ گره‌ی جایگزینی پاسخ نداد — اسکن تازه...")
        self._disconnect("اتصال قطع شد؛ نیاز به اسکن تازه")
        self.request_refresh(True)

    # ------------------------------------------------------------ حلقه
    def run(self):
        log.info("vpn controller started")
        if not engine.is_installed():
            self._set_state("connecting", "نصب هسته‌ی sing-box...")
            if not engine.install(lambda m: self.status.emit(m)):
                self._set_state("error", "نصب هسته ناموفق بود.")
                self.error.emit("نصب هسته ناموفق بود. اتصال اینترنت را بررسی کنید.")
                return

        cached = selector.load_cache()
        if cached:
            self.nodes = cached
            self.nodes_updated.emit(list(cached))
            self.status.emit(f"{len(cached)} گره‌ی ذخیره‌شده آماده است.")
            if self.settings.get("auto_connect"):
                self._set_state("connecting", "اتصال سریع از حافظه...")
                for node in cached[:5]:
                    if self._stop_flag:
                        break
                    if self._connect_node(node):
                        break
        if not self._stop_flag and self.settings.get("auto_connect"):
            # حتی اگر از کش وصل شدیم، در پس‌زمینه گره‌های تازه‌تر را هم بسنج
            self._spawn_scan(False, connect_after=True)

        last_traffic = 0.0
        while not self._stop_flag:
            try:
                with self._lock:
                    connect_best = self._cmd_connect_best
                    do_refresh = self._cmd_refresh
                    deep = self._cmd_deep
                    do_disconnect = self._cmd_disconnect
                    pending = self._pending_node
                    self._cmd_connect_best = False
                    self._cmd_refresh = False
                    self._cmd_deep = False
                    self._cmd_disconnect = False
                    self._pending_node = None

                if do_disconnect:
                    self._disconnect()

                if pending is not None:
                    if self.current and self.current.get("id") == pending.get("id"):
                        self.status.emit("به همین گره وصل هستید.")
                    else:
                        self._connect_node(pending)

                if connect_best:
                    working = selector.rank(self.nodes)
                    if not working:
                        self.request_refresh(True)
                    elif not self._connect_node(working[0]):
                        self.request_refresh(True)

                if do_refresh:
                    self._spawn_scan(deep, connect_after=True)

                if self.current:
                    if time.time() - last_traffic >= 2.0:
                        last_traffic = time.time()
                        self._poll_traffic()
                    self._health_tick()
                elif (self.settings.get("auto_connect")
                      and not (self._scan_thread and self._scan_thread.is_alive())
                      and time.time() - self._last_refresh
                      > int(self.settings.get("refresh_interval_minutes", 60)) * 60):
                    self._spawn_scan(False, connect_after=True)
            except Exception as e:
                log.error(f"controller loop error: {e}")
                self.error.emit(str(e))

            time.sleep(0.4)

        if self.current:
            self._disconnect()
        log.info("vpn controller stopped")
