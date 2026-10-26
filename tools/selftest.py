"""
تست پذیرش (headless) — کل مسیر برنامه را بدون رابط گرافیکی اجرا می‌کند:
دریافت منابع ← فیلتر TCP ← تست واقعی تونل ← انتخاب بهترین گره ← اتصال ←
آزمایش تلگرام / اینستاگرام / یوتیوب از داخل تونل.

اجرا:
    python tools/selftest.py                # مسیر کامل
    python tools/selftest.py --limit 60     # سریع‌تر
    python tools/selftest.py --cached       # فقط کش و اتصال
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# کنسول ویندوز پیش‌فرض cp1252 است؛ متن فارسی باید UTF-8 چاپ شود
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.config import DEFAULT_SETTINGS, WORKING_CACHE_FILE          # noqa: E402
from app.core import engine, probe, selector, sources                # noqa: E402
from app.utils.logger import log                                     # noqa: E402

TARGETS = DEFAULT_SETTINGS["target_sites"]


def _step(msg):
    print(f"\n>>> {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=140,
                    help="حداکثر گره برای تست واقعی تونل")
    ap.add_argument("--batch", type=int, default=28)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--cached", action="store_true", help="فقط از کش")
    ap.add_argument("--sources", type=str, default="", help="فقط منابع شامل این کلمه")
    ap.add_argument("--keep-connected", action="store_true")
    args = ap.parse_args()

    t_all = time.time()
    if not engine.is_installed():
        _step("نصب هسته sing-box")
        if not engine.install(lambda m: print("   ", m, flush=True)):
            print("نصب هسته ناموفق بود.")
            return 1
    print("هسته:", engine.version())

    # ---------------------------------------------------------------- دریافت
    nodes = []
    if args.cached:
        nodes = selector.load_cache()
        print(f"از کش: {len(nodes)} گره‌ی سالم")
    else:
        tested_all = []
        for tier_name, kinds, budget in (
                ("منابع تست‌شده", ("tested",), args.limit),
                ("منابع حجیم", ("bulk",), max(40, args.limit // 2))):
            if args.sources:
                srcs = [s for s in sources.SOURCES if args.sources in s["url"]]
            else:
                srcs = [s for s in sources.SOURCES if s["kind"] in kinds]
            if not srcs:
                continue
            _step(f"دریافت {tier_name}")
            t0 = time.time()
            got = sources.fetch_all(
                progress_cb=lambda d, t, m: print(f"\r   {m}", end="", flush=True),
                sources=srcs)
            print(f"\n   {len(got)} گره یکتا در {time.time() - t0:.1f} ثانیه")
            if not got:
                continue
            _step("فیلتر TCP (حذف گره‌های مرده)")
            t0 = time.time()
            alive = probe.tcp_prefilter(got, timeout=1.8, workers=48,
                                        deadline=35, max_alive=320)
            print(f"   {len(alive)} گره با پورت باز در {time.time() - t0:.1f} ثانیه")
            if not alive:
                continue
            picks = selector.order_by_health(alive)[:budget]
            _step(f"تست واقعی تونل روی {len(picks)} گره")
            t0 = time.time()
            tested = probe.probe_many(
                picks, batch_size=args.batch, concurrency=args.concurrency,
                timeout=6.0, do_speed=True, speed_secs=2.0,
                progress_cb=lambda c, t, m: print(f"\r   {m}", end="", flush=True))
            tested_all.extend(tested)
            working = selector.rank(tested)
            print(f"\n   {len(working)} از {len(tested)} گره سالم "
                  f"در {time.time() - t0:.1f} ثانیه")
            selector.update_source_health(tested)
            if len(selector.rank(tested_all)) >= 10:
                break

        tested_all = list({n["id"]: n for n in tested_all}.values())
        working = selector.rank(tested_all)
        selector.save_cache(tested_all)
        selector.save_servers(selector.rank_all(tested_all))
        nodes = working

    working = selector.rank(nodes)
    if not working:
        print("هیچ گره سالمی پیدا نشد.")
        return 1

    print("\n   بهترین گره‌ها:")
    for n in working[:8]:
        print(f"     {n.get('protocol'):<9} {n.get('server'):<22}:{n.get('port'):<5} "
              f"{n.get('latency') or '-':>7}ms  {n.get('speed_kbps') or '-':>8}kbps  "
              f"{n.get('remark', '')[:24]}")

    # ---------------------------------------------------------------- اتصال
    _step("اتصال به بهترین گره")
    best = None
    results = {}
    for candidate in working[:4]:
        best = candidate
        config = engine.build_config([best], DEFAULT_SETTINGS["mixed_port"],
                                     DEFAULT_SETTINGS["http_port"], tun=False)
        ok, err = engine.check_config(config)
        if not ok:
            print("کانفیگ نامعتبر:", err)
            engine.stop()
            continue
        if not engine.start(config, wait_port=DEFAULT_SETTINGS["mixed_port"]):
            print(f"   هسته با {best.get('server')} بالا نیامد؛ بعدی...")
            engine.stop()
            continue
        print(f"   متصل: {best.get('remark')} ({best.get('protocol')})")
        results = probe.probe_targets(DEFAULT_SETTINGS["mixed_port"],
                                      TARGETS, timeout=12)
        if all(r["ok"] for r in results.values()):
            break
        print("   یکی از سایت‌ها باز نشد؛ تلاش با گره‌ی بعدی...")
        engine.stop()
        results = {}
    if not engine.is_running():
        print("اتصال به هیچ گره‌ای برقرار نشد.")
        return 1

    # ------------------------------------------------------------- سایت‌ها
    _step("آزمایش سایت‌های هدف از داخل تونل")
    if not results:
        results = probe.probe_targets(DEFAULT_SETTINGS["mixed_port"], TARGETS,
                                      timeout=12)
    for name, res in results.items():
        mark = "OK " if res["ok"] else "FAIL"
        print(f"   [{mark}] {name:<12} status={res['status']} "
              f"latency={res['latency']}ms")

    _step("تست سرعت و پینگ نهایی")
    speed = probe.speed_via_socks(DEFAULT_SETTINGS["mixed_port"],
                                  DEFAULT_SETTINGS["speed_test_url"], 4.0)
    status, latency, _ = probe.http_via_socks(
        DEFAULT_SETTINGS["mixed_port"],
        DEFAULT_SETTINGS["connectivity_probe"], timeout=10)
    print(f"   سرعت دانلود: {speed} kbps")
    print(f"   پینگ تونل: {latency} ms (status={status})")

    report = {
        "engine": engine.version(),
        "node": {k: best.get(k) for k in ("protocol", "server", "port", "remark",
                                          "latency", "speed_kbps")},
        "targets": results,
        "speed_kbps": speed,
        "ping_ms": latency,
        "working_nodes": len(working),
        "elapsed_sec": round(time.time() - t_all, 1),
    }
    out = ROOT / "data" / "selftest_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nگزارش در {out}")

    if not args.keep_connected:
        engine.stop()
    all_ok = all(r["ok"] for r in results.values())
    print("\nنتیجه:", "همه‌ی سایت‌ها باز شدند ✅" if all_ok else "برخی سایت‌ها باز نشدند ⚠")
    return 0 if all_ok else 2


if __name__ == "__main__":
    sys.exit(main())
