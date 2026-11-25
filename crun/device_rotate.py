"""设备指纹轮换：每个账号一套独立机型，按周期换一代。

原版 device_profile.get_profile(uid) 按 uid 哈希从 19 个机型里定死一个，写进
device_profiles.json 后不再变化。这里在它外面包一层：到期（默认 14 天）就把
该账号换到下一代机型并同步换 android_id —— 服务端看到的是"同一账号换过手机"，
而不是"一台机器挂了所有账号"。

注意：轮换元数据（第几代、上次轮换时间）存在单独的 crun_device_meta.json，
不能塞进 device_profiles.json —— 原版会用 DeviceProfile(**entry) 反序列化，
多一个字段就直接 TypeError。
"""
import hashlib
import json
import os
import time
from dataclasses import asdict

ROTATE_DAYS = float(os.environ.get("CRUN_ROTATE_DAYS", "14"))
META = "crun_device_meta.json"


def _meta_path():
    return os.path.join(os.getcwd(), META)


def _load_meta():
    try:
        with open(_meta_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_meta(data):
    try:
        with open(_meta_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _gen_profile(mod, uid, generation):
    pool = mod.DEVICE_POOL
    seed = int(hashlib.md5(("%s:%d" % (uid, generation)).encode()).hexdigest()[:8], 16)
    brand, model, osver, a_list = pool[seed % len(pool)]
    android_id = hashlib.md5(("%s:%d:aid" % (uid, generation)).encode()).hexdigest()[:16]
    return mod.DeviceProfile(brand=brand, model=model, osver=osver, a_list=a_list,
                             android_id=android_id, device_name=model)


def install(mod, log=print):
    orig = getattr(mod, "get_profile", None)
    if orig is None:
        return False

    def get_profile(uid=None):
        prof = orig(uid)
        if not uid:
            return prof
        try:
            meta = _load_meta()
            rec = meta.get(str(uid)) or {}
            last = float(rec.get("ts") or 0)
            gen = int(rec.get("gen") or 0)
            if time.time() - last < ROTATE_DAYS * 86400:
                return prof
            gen += 1
            new = _gen_profile(mod, uid, gen)
            store = mod._load_store()
            store[str(uid)] = asdict(new)           # 只写 DeviceProfile 的 6 个字段
            mod._save_store(store)
            meta[str(uid)] = {"gen": gen, "ts": time.time()}
            _save_meta(meta)
            log("[设备] 账号 %s 轮换到 %s %s（第 %d 代）" % (str(uid)[-4:], new.brand, new.model, gen))
            return new
        except Exception as e:
            log("[设备] 轮换失败，沿用原指纹：%s" % e)
            return prof

    mod.get_profile = get_profile
    return True


def status(mod):
    meta = _load_meta()
    out = []
    for uid, rec in meta.items():
        nxt = (rec.get("ts") or 0) + ROTATE_DAYS * 86400
        out.append({"account": str(uid)[-6:], "generation": rec.get("gen"),
                    "next_rotate": time.strftime("%Y-%m-%d", time.localtime(nxt))})
    return out
