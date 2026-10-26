"""
تست یکپارچه‌ی کنترلر (بدون رابط گرافیکی).

کل چرخه‌ی واقعی را اجرا می‌کند: نصب هسته، خواندن کش، اسکن، اتصال،
آزمایش تلگرام/اینستاگرام/یوتیوب و آمار زنده. سپس قطع می‌کند.

اجرا:  python tools/controller_test.py [--fresh]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PySide6.QtCore import QCoreApplication, QTimer                    # noqa: E402

from app.core import selector                                          # noqa: E402
from app.core.vpn import VPNController                                 # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="کش را نادیده بگیر")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--scan", action="store_true", help="اسکن کامل را هم امتحان کن")
    args = ap.parse_args()

    if args.fresh:
        from app.config import WORKING_CACHE_FILE
        WORKING_CACHE_FILE.unlink(missing_ok=True)

    app = QCoreApplication(sys.argv)
    settings = selector.load_settings()
    settings["auto_connect"] = True
    settings["auto_switch"] = True
    settings["set_system_proxy"] = False        # در تست، پروکسی ویندوز تغییر نکند

    ctl = VPNController(settings)
    started = time.time()
    result = {"connected": None, "targets": {}, "stats": {}, "errors": []}

    def log_status(msg):
        print(f"[{time.time() - started:6.1f}s] {msg}", flush=True)

    def on_connected(node):
        result["connected"] = {k: node.get(k) for k in
                               ("protocol", "server", "port", "remark", "latency")}
        print(f"\n✅ متصل: {node.get('protocol')} {node.get('server')}:{node.get('port')} "
              f"({node.get('remark', '')[:40]})\n", flush=True)

    def on_targets(res):
        result["targets"] = res
        for name, info in res.items():
            print(f"   {'OK  ' if info.get('ok') else 'FAIL'} {name}: "
                  f"status={info.get('status')} latency={info.get('latency')}ms", flush=True)

    def on_stats(st):
        result["stats"] = st

    def on_nodes(nodes):
        result["nodes_total"] = len(nodes)
        result["nodes_working"] = sum(1 for n in nodes if n.get("working"))
        result["top"] = [
            {"proto": n.get("protocol"), "server": n.get("server"),
             "lat": n.get("latency"), "speed": n.get("speed_kbps"),
             "score": selector.score(n)}
            for n in nodes[:8] if n.get("working")
        ]

    def on_error(msg):
        result["errors"].append(msg)
        print(f"   ⚠ {msg}", flush=True)

    ctl.status.connect(log_status)
    ctl.connected.connect(on_connected)
    ctl.targets.connect(on_targets)
    ctl.stats.connect(on_stats)
    ctl.nodes_updated.connect(on_nodes)
    ctl.error.connect(on_error)
    ctl.start()

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.2)
        if result["targets"] and time.time() - started > 6:
            # کمی آمار زنده جمع کن
            time.sleep(3)
            app.processEvents()
            break
    ctl.stop()
    ctl.request_disconnect()
    ctl.wait(15000)

    print("\n--- گزارش ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = bool(result["connected"]) and bool(result["targets"]) and \
        all(v.get("ok") for v in result["targets"].values())
    print("\nنتیجه:", "PASS ✅" if ok else "FAIL ⚠")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
