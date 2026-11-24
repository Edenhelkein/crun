"""CLI: python -m crun.cli <simulate|walk|audit|ledger|policy|checks|hooks|ui|update|version>"""
import argparse
import json
import os
import sys

from . import __version__
from .antidetect import CHECKS, audit, evasion_plan
from .blacklist import RiskLedger, fingerprint
from .engine import run_session
from .policy import DEFAULT_MODES, PolicyEngine
from .routegen import generate_diverse, RouteLibrary, cells_of
from .sensors import build_steps
from .traj import simulate_run


def cmd_simulate(a):
    cfg = {
        "device_fp": a.device or fingerprint(a.model, a.build, a.android_id),
        "account_id": a.account, "egress_ip": a.ip, "seed": a.seed,
        "distance_m": a.distance, "pace_s_per_km": a.pace, "mode": a.mode,
        "tries": a.tries, "max_overlap": a.max_overlap,
        "noise_sigma": a.noise_sigma, "canyon_p": a.canyon_p,
        "work_dir": a.work_dir, "min_gap_days": a.min_gap_days,
    }
    if a.lat is not None and a.lon is not None:
        cfg["origin"] = [a.lat, a.lon]
    rep = run_session(cfg, out_dir=a.out)
    print(json.dumps({k: rep[k] for k in ("verdict", "reasons", "action") if k in rep},
                     ensure_ascii=False, indent=2))
    if "audit" in rep:
        au = rep["audit"]
        print(f"\n[self-audit] score={au['score']} verdict={au['verdict']} failed={au['failed']}")
        for r in au["checks"]:
            if r["fail"]:
                print(f"  ! {r['id']:<14} {r['detail']}  -> {r['counter']}")
        if rep.get("route"):
            m = rep["route"]
            print(f"[route] fp={m['fp']} cells={m['cells']} overlap={m['overlap']} "
                  f"max_turn={m.get('max_turn_deg')}° candidates={m['candidates']} accepted={m['accepted']}")
        print("\n[actions]")
        for x in rep["actions"]:
            print("  -", x)
        s = rep["session"]
        print(f"\nsession: {s['distance_m']}m / {s['duration_s']}s / pace {s['pace_s_per_km']}s/km "
              f"mode={s.get('mode')} route={s['route_hash']} geohash6={s['geohash6']}")
        print(f"steps: {rep['steps']['total_steps']} cadence={rep['steps']['avg_cadence_spm']} "
              f"ratio={rep['steps']['step_gps_ratio']}")
        print(f"written -> {os.path.join(a.out, 'session.json')}")
    return 0


def cmd_walk(a):
    import random
    lib = RouteLibrary(os.path.join(a.work_dir, "routes.json"))
    rng = random.Random(a.seed)
    pts, meta = generate_diverse(rng, (a.lat, a.lon), a.distance, lib, tries=a.tries,
                                 max_overlap=a.max_overlap)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"cells={len(cells_of(pts))} points={len(pts)}")
    if not a.no_save:
        import time
        lib.add(pts, ts=time.time(), distance_m=meta["distance_m"])
        lib.save()
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"type": "Feature", "geometry": {"type": "LineString",
                      "coordinates": [[round(p[1], 6), round(p[0], 6)] for p in pts]}}, f)
        print(f"geojson -> {a.out}")
    return 0


def cmd_audit(a):
    with open(a.session, encoding="utf-8") as f:
        data = json.load(f)
    steps = data.get("steps") or build_steps(data["session"]["points"],
                                             ref_distance=data["session"]["distance_m"])
    rep = audit(data["session"], steps, route_meta=data.get("route"))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    for x in evasion_plan(rep):
        print("  -", x)
    return 0


def cmd_ledger(a):
    led = RiskLedger(os.path.join(a.work_dir, "ledger.json"))
    if a.op == "list":
        for e in led.entries.values():
            print(f"{e['kind']:<8} {e['value']:<28} {e['status']:<8} score={e['score']:.1f} "
                  f"hits={e['hits']} notes={e['notes'][-2:]}")
    elif a.op == "hit":
        e = led.hit(a.kind, a.value, weight=a.weight, note=a.note or "manual")
        led.save()
        print(json.dumps(e, ensure_ascii=False))
    elif a.op == "observe":
        out = led.observe_response(a.text, {"device": a.device, "account": a.account, "ip": a.ip})
        led.save()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif a.op == "decide":
        print(json.dumps(led.decide({"device": a.device, "account": a.account, "ip": a.ip}),
                         ensure_ascii=False))
    return 0


def cmd_policy(a):
    pol = PolicyEngine(os.path.join(a.work_dir, "policy.json"))
    if a.op == "show":
        print(json.dumps(pol.summary(), ensure_ascii=False, indent=2))
    elif a.op == "login":
        r = pol.login(a.account, a.device, success=not a.fail)
        pol.save()
        print(json.dumps(r, ensure_ascii=False))
    elif a.op == "mode":
        print(json.dumps(dict(zip(("ok", "reason"), pol.check_mode(a.mode))), ensure_ascii=False))
    elif a.op == "preflight":
        r = pol.preflight(a.account, a.device, a.mode)
        pol.save()
        print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def cmd_hooks(a):
    src = os.path.join(os.path.dirname(__file__), "hooks.js")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(src, encoding="utf-8") as f, open(a.out, "w", encoding="utf-8") as g:
        g.write(f.read())
    print(f"hooks -> {a.out}\n用法: frida -U -f {a.pkg} -l {a.out} --no-pause")
    return 0


def cmd_checks(a):
    total = sum(c["w"] for c in CHECKS)
    print(f"{len(CHECKS)} 项检测，权重合计 {total}")
    for c in CHECKS:
        print(f"  {c['id']:<14} w={c['w']:<3} {c['name']}: {c['obs']}")
    return 0


def cmd_ui(a):
    from .ui import server
    return server.main(["--port", str(a.port), "--work", a.work_dir])


def cmd_update(a):
    from .updater import apply as update_apply, check as update_check
    src = a.manifest
    if a.github:
        src = f"https://github.com/{a.github}/releases/latest/download/manifest.json"
    if not src:
        print(json.dumps({"ok": False, "error": "需要清单地址，或 --github OWNER/REPO"}, ensure_ascii=False))
        return 1
    info = update_check(src, allow_http=a.allow_http, channel=a.channel)
    print(json.dumps(dict(info, source=src), ensure_ascii=False, indent=2))
    if not a.apply or not info.get("ok"):
        return 0
    res = update_apply(info, a.install_dir, dry_run=a.dry_run, key=a.key, allow_http=a.allow_http)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_migrate(a):
    from .migrate import candidate_dirs, merge, scan
    dirs = candidate_dirs(a.dir)
    found = scan(dirs)
    out = {"target": os.path.abspath(a.work_dir), "scanned": len(dirs), "found": found}
    if a.apply:
        src = [r["dir"] for r in found
               if os.path.normcase(os.path.abspath(r["dir"])) != os.path.normcase(os.path.abspath(a.work_dir))]
        out["merged"] = merge(a.work_dir, src)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(a):
    """发布前自检：签名 / MOTW / Defender / 运行环境。"""
    import subprocess
    exe = sys.executable
    rep = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
           "executable": exe, "cwd": os.getcwd(),
           "running_from_temp": any(s in exe.lower() for s in ("\\temp\\", "\\tmp\\", "\\downloads\\"))}

    # 网络标记（Zone.Identifier）
    try:
        with open(exe + ":Zone.Identifier", encoding="utf-8", errors="ignore") as f:
            zid = f.read()
        rep["motw"] = "present" if "ZoneId=3" in zid else "other"
    except OSError:
        rep["motw"] = "none"

    ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    try:
        sig = subprocess.run(ps + [f"(Get-AuthenticodeSignature '{exe}').Status"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        rep["signature"] = sig or "Unknown"
    except Exception as e:
        rep["signature"] = f"probe-failed:{e}"

    try:
        mp = subprocess.run(ps + ["$s=Get-MpComputerStatus; "
                                  "'{0}|{1}' -f $s.RealTimeProtectionEnabled,$s.AntivirusSignatureVersion"],
                            capture_output=True, text=True, timeout=20).stdout.strip()
        rt, ver = (mp.split("|") + ["", ""])[:2]
        rep["defender"] = {"realtime": rt, "signature": ver} if rt else "unavailable"
    except Exception:
        rep["defender"] = "unavailable"

    adv = []
    if rep["signature"] in ("NotSigned", "Unknown", "") or "probe-failed" in str(rep["signature"]):
        adv.append("未签名：SmartScreen 会拦、AV 云信誉从零开始。发布前必须 Authenticode 签名（EV 证书可即时获得信誉）")
    if rep["motw"] == "present":
        adv.append("文件带网络标记（ZoneId=3）：从网上下载的 zip 会继承，解压后触发 SmartScreen/Defender 云查")
    if rep["running_from_temp"]:
        adv.append("从 Temp/Downloads 运行：这是启发式高危路径，装到 Program Files 再跑")
    if not adv:
        adv.append("签名与环境正常；若仍被报毒，走厂商误报提交（见 packaging/FALSE_POSITIVE.md）")
    rep["advice"] = adv
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


def cmd_version(a):
    print(__version__)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="crun")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate")
    s.add_argument("--lat", type=float); s.add_argument("--lon", type=float)
    s.add_argument("--distance", type=float, default=2500.0)
    s.add_argument("--pace", type=float, default=360.0)
    s.add_argument("--mode", default="campus_run", choices=list(DEFAULT_MODES))
    s.add_argument("--tries", type=int, default=20); s.add_argument("--max-overlap", type=float, default=0.55)
    s.add_argument("--seed", type=int); s.add_argument("--out", default="out")
    s.add_argument("--work-dir", default=".")
    s.add_argument("--device"); s.add_argument("--account"); s.add_argument("--ip")
    s.add_argument("--model", default="Xiaomi 23013RK75C"); s.add_argument("--build", default="UP1A.231005.007")
    s.add_argument("--android-id", default="a1b2c3d4e5f60718")
    s.add_argument("--noise-sigma", type=float, default=3.0)
    s.add_argument("--canyon-p", type=float, default=0.12)
    s.add_argument("--min-gap-days", type=int, default=10)
    s.set_defaults(func=cmd_simulate)

    w = sub.add_parser("walk")
    w.add_argument("--lat", type=float, default=30.2741); w.add_argument("--lon", type=float, default=120.1551)
    w.add_argument("--distance", type=float, default=2500.0); w.add_argument("--seed", type=int, default=1)
    w.add_argument("--tries", type=int, default=20); w.add_argument("--max-overlap", type=float, default=0.55)
    w.add_argument("--out"); w.add_argument("--work-dir", default=".")
    w.add_argument("--no-save", action="store_true")
    w.set_defaults(func=cmd_walk)

    au = sub.add_parser("audit"); au.add_argument("session"); au.set_defaults(func=cmd_audit)

    lg = sub.add_parser("ledger")
    lg.add_argument("op", choices=["list", "hit", "observe", "decide"])
    lg.add_argument("--kind", default="device"); lg.add_argument("--value", default="")
    lg.add_argument("--weight", type=float, default=1.0); lg.add_argument("--note")
    lg.add_argument("--text", default=""); lg.add_argument("--device"); lg.add_argument("--account")
    lg.add_argument("--ip"); lg.add_argument("--work-dir", default=".")
    lg.set_defaults(func=cmd_ledger)

    po = sub.add_parser("policy")
    po.add_argument("op", choices=["show", "login", "mode", "preflight"])
    po.add_argument("--account", default="CAMPUS_ACCOUNT"); po.add_argument("--device", default="DEVICE_FP_X")
    po.add_argument("--mode", default="campus_run"); po.add_argument("--fail", action="store_true")
    po.add_argument("--work-dir", default=".")
    po.set_defaults(func=cmd_policy)

    hk = sub.add_parser("hooks"); hk.add_argument("--out", default="out/hooks.js")
    hk.add_argument("--pkg", default="com.TARGET.app"); hk.set_defaults(func=cmd_hooks)

    ck = sub.add_parser("checks"); ck.set_defaults(func=cmd_checks)

    ui = sub.add_parser("ui"); ui.add_argument("--port", type=int, default=8777)
    ui.add_argument("--work-dir", default="."); ui.set_defaults(func=cmd_ui)

    up = sub.add_parser("update")
    up.add_argument("manifest", nargs="?", help="清单 URL / 本地路径；用 --github 时可省略")
    up.add_argument("--apply", action="store_true")
    up.add_argument("--dry-run", action="store_true"); up.add_argument("--key")
    up.add_argument("--channel"); up.add_argument("--allow-http", action="store_true")
    up.add_argument("--github", help="OWNER/REPO，自动指向 releases/latest/download/manifest.json")
    up.add_argument("--install-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    up.set_defaults(func=cmd_update)

    dr = sub.add_parser("doctor"); dr.set_defaults(func=cmd_doctor)

    mg = sub.add_parser("migrate")
    mg.add_argument("--dir", action="append", help="额外扫描目录，可重复")
    mg.add_argument("--apply", action="store_true", help="把扫描结果合并进 --work-dir")
    mg.add_argument("--work-dir", default=".")
    mg.set_defaults(func=cmd_migrate)

    ve = sub.add_parser("version"); ve.set_defaults(func=cmd_version)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
