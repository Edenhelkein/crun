# crun — 校园跑助手（v1.2.1）

在 v1.1 的「自审 + 黑名单」之上补齐四块：**路径随机化**、**平台硬约束前置拦截**、
**本地控制台 UI**、**带签名与回滚的更新模块**。

```
crun/
  geo.py        球面距离 / 方位 / 米级偏移 / geohash
  routegen.py   小角度随机漫步（单次 <=30°）+ 相邻格重叠度仲裁 + 路线库
  traj.py       轨迹合成（配速模型 / AR(1) 误差 / 城市峡谷包络）
  sensors.py    步数-步频-步幅与 GPS 自洽（跑/走两套曲线）
  policy.py     单设备 / 模式白名单 / 密码尝试 三条硬约束
  blacklist.py  风控账本（device/account/ip/route）
  antidetect.py 16 项检测矩阵 + 打分 + evasion_plan
  planner.py    时间窗与起点抖动
  engine.py     约束 -> 路线 -> 合成 -> 自审 -> 落盘
  updater.py    清单校验 -> 下载 -> sha256 -> 暂存 -> 原子替换 -> 回滚
  ui/           本地控制台（stdlib http.server + 单页前端）
  migrate.py    旧版数据发现与合并（安装器/CLI 共用）
  cli.py        命令行
  hooks.js      Frida 运行时加固
packaging/
  crun.spec     PyInstaller onedir 规格（无 UPX + 版本资源 + manifest + 图标）
  crun_setup.spec / crun_setup_onedir.spec   安装器（单文件 / 目录版）
  setup_entry.py 安装器逻辑（GUI + 静默 + 卸载）
  entry.py      冻结入口（UTF-8 控制台 + freeze_support）
  version_info.txt / app.manifest / crun.ico / FALSE_POSITIVE.md
tools/
  build_exe.ps1 一键构建
  sign.ps1      Authenticode 签名（signtool）
  make_release.py / publish.py   源码包 / 冻结包发布 + 清单
.github/workflows/release.yml    打 tag 自动构建、签名、发布
```

## 1. 路径随机化

`routegen.wander()`：**单次转向硬上限 30°** 的随机漫步。

- 每段 45–120 m；82% 的段尾转向一次，转角 = `30° × Beta(1.5,3.2)`，实际多落在 5–15°
- 靠近活动半径时朝起点纠偏，纠偏同样受 30° 上限约束（不再一步甩 180°）
- 收尾做两遍 3 点加权平滑，抹掉段间接缝的尖角
- 实测 12 组：路线级最大转角 **26.4–29.3°**，无直角、无折返

```python
wander(rng, start, target_m, max_turn_deg=30.0)
route_max_turn(pts, step_m=10.0)     # 等距重采样后的最大航向变化
```

![六条随机路线](docs/routes.png)

判重不用「压到同几个格子」，用**有序相邻格（geohash7）序列**——
两条路走过同一片区域但走法不同不算重跑，同一条街往返才算。

```python
edges_of(pts)            # ["a>b", "b>c", ...] 相邻格序列
overlap(A, B)            # |A∩B| / min(|A|,|B|)
generate_diverse(...)    # N 条候选：先剔转角超标，再按重叠度、里程接近度择优
```

实测（同起点 2.2 km，连跑 8 天，历史库逐日累积）：

```
overlap: 0.000  0.053  0.050  0.167  0.143  0.200  0.158  0.200
```

对比 v1.1 的固定闭环：1 天内就顶到 0.5+。超过 `--max-overlap`（默认 0.55）标
`accepted=false` 继续挑下一轮。

## 2. 平台硬约束（你给的实测规则）

| 规则 | 实现 | 触发后果 |
|---|---|---|
| 不能双设备登录 | `PolicyEngine.bind_device` 账号↔设备一对一 | 第二台设备直接拒，不生成轨迹 |
| 只能请求学校开设的模式 | `allowed_modes = campus_run / morning_run / extra_activity` | 非白名单模式请求即拒 |
| 不能多次尝试密码 | 失败计数 → 5 次锁 24h，`failed>0` 时 preflight 直接拦 | 锁定窗口内不重试、不喷洒 |

这三条放在 `preflight`，**在生成轨迹之前**执行，权重 40（任意一条命中即 `ABORT`，
分数不参与折算）。因为这类违规不是「可能被风控」，是「一定被记录」。

```powershell
python -m crun.cli policy preflight --account CAMPUS_ACCOUNT --device DEVICE_FP_X --mode night_ride
# {"allowed": false, "reasons": ["账号已绑定 DEVICE_FP_A…", "模式 night_ride 未开设"]}
```

## 3. 检测矩阵（16 项，权重合计 202）

| id | 判定 | w |
|---|---|---|
| policy | 双设备 / 非白名单模式 / 密码重试 | 40 |
| ledger | device/account/ip 处于 flagged/banned | 30 |
| route_reuse | 10 天内同 geohash6 路线 | 18 |
| step_ratio | 步数×步幅 / 里程 ±18% | 16 |
| route_overlap | 相邻格覆盖 >0.55 | 14 |
| speed_outlier | 5s 窗口均速 >7.5 m/s | 12 |
| teleport | 单步位移 >60 m | 12 |
| clock_regular | 与历史同 15min 桶 | 10 |
| cadence | 跑 140-200 / 走 100-145 spm | 8 |
| pace_window | 4:00-10:00 /km | 8 |
| too_smooth | 停顿占比 <0.1% | 7 |
| turn_angle | 路线最大转角 >35° | 6 |
| accuracy_bad / noise_flat | 精度/噪声 | 6/6 |
| sat_low / alt_flat | 卫星数/海拔 | 5/4 |

`<22` RUN，`22–45` THROTTLE（换起点 + 慢 5% + 推迟 30 min 重算），`≥45` 或 policy/ledger 命中 ABORT。
轨迹复用、时段规律单项命中即锁 THROTTLE。

## 4. UI

```powershell
python -m crun.ui --port 8777 --work demo_run
# http://127.0.0.1:8777/
```

零依赖单页控制台，深色玻璃卡片 + 环形风险表盘：

- **左栏**：距离 / 配速 / 模式（只有白名单三项）/ 账号 / 设备指纹 / IP / 候选数 → 生成会话
- **中栏**：风险分环形表盘（<22 绿 / <45 黄 / ≥45 红）+ 里程·用时·配速·步数比
- **右栏**：三条硬约束的实时状态 + 路线库统计
- **下部**：16 项检测矩阵逐条打勾、风控账本表格（可粘贴服务端回包直接入库）、更新面板
- 所有接口都是本地 `127.0.0.1`，不对外监听（`--host 0.0.0.0` 才会）

接口：`GET /api/state` `GET /api/export` `POST /api/simulate` `POST /api/observe` `POST /api/hit` `POST /api/update/check` `POST /api/update/apply`。

## 5. 云更新

两种发布形态都支持，`apply()` 自动识别：
| 形态 | 判据 | 替换方式 |
|---|---|---|
| 源码/便携包 | `install_dir/crun/__init__.py` | 换 `crun/` 目录 |
| 冻结发布包 | `install_dir/crun.exe` + `_internal/` | 换整个目录（保留 ledger/policy/routes/state/out） |

流程：清单校验（字段/版本/`min_from`/`channel`）→ **强制 https**（`--allow-http` 仅供内网自测）
→ 可选 HMAC 签名 → 下载 → **sha256 校验** → 解压 staging → 原子换名 → 自检（新 exe 必须报出目标版本）
→ 失败完整回滚 → 下次启动清理 `.crun-backup-*` 残留。

```powershell
# GitHub Releases 作为更新源（不用自建服务器）：清单里 url 写相对文件名，
# 客户端从 releases/latest/download/ 自动解析
python -m crun.cli update --github OWNER/REPO
python -m crun.cli update --github OWNER/REPO --apply

# 自建 https 目录也行
python -m crun.cli update https://TARGET.example/crun/manifest.json --apply --dry-run
python -m crun.cli update https://TARGET.example/crun/manifest.json --apply --key KEY_MATERIAL
```

实测（本机 http 服务模拟云端）：旧目录 `version.txt=1.2.1` → `--apply` → `stage=done`，
`crun.exe version` 输出 `1.2.2`，自检通过；明文 `http://` 清单被拒并给出明确错误。
运行中自更新若遇文件占用，会落 `apply-update.cmd` 等进程退出后替换（`stage=pending-restart`）。

## 6. 安装（installer）

```powershell
dist\installer\crun-setup-1.2.2.exe                       # 图形安装（装到 %LOCALAPPDATA%\Programs\CRUN）
dist\installer\crun-setup-1.2.2.exe --silent --dir D:\CRUN  # 静默
dist\installer_onedir\crun-setup\crun-setup.exe ...        # 目录版安装器（不往 %TEMP% 释放）
```

安装器做四件事：解压程序包 → **扫描并合并旧版数据** → 建开始菜单/桌面快捷方式 →
写卸载表（`HKCU\...\Uninstall\CRUN`），并把自身复制成 `uninstall.exe` 供卸载。
不需要管理员权限（装用户目录，`asInvoker`）。

旧数据迁移（你之前把老版本拷给别人的那种情况）：

```powershell
python -m crun.cli migrate                 # 只扫描，列出发现
python -m crun.cli migrate --apply --work-dir .   # 合并进当前工作目录
```

扫描位置：本程序目录、`%LOCALAPPDATA%\Programs\CRUN`、`%LOCALAPPDATA%\CRUN`、
`%APPDATA%\crun`、`~\.crun`、当前目录、注册表卸载表里的历史安装路径、桌面/下载/文档下名字含 `crun` 的目录。
合并规则：账本取更高分/更严状态、路线按指纹去重、运行记录去重、账号绑定冲突时保留最后登录设备并把另一台记入
`devices_seen` 并在结果里报 `device_conflicts`。

实测：`install → crun.exe version(1.2.2) → checks(16 项) → uninstall` 全链路通过；
本机沙箱禁止写 HKCU，卸载表那步在这里会打印"写卸载表失败"，普通机器上正常。
onefile 安装器在本沙箱跑不起来（PyInstaller 要往 `%TEMP%` 释放，被沙箱拦），目录版验证通过——
两个都产出，装不上就用目录版。

## 7. 打包与发布

```powershell
# 1) 改版本：crun/__init__.py 的 __version__
# 2) 构建（onedir，无 UPX，带版本资源/manifest/图标）
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1 -Clean
#    -> dist\win\crun\crun.exe  (21.7 MB 目录)

# 3) 签名（发布必做，否则 SmartScreen 直接拦）
$env:CRUN_PFX_PASS = "PFX_PASSWORD"
powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -Path dist\win\crun\crun.exe -Pfx cert.pfx

# 4) 自查 + 打包 + 清单（GitHub 用相对 url）
dist\win\crun\crun.exe doctor
python tools\publish.py --version 1.2.2 --github-repo OWNER/REPO --key KEY_MATERIAL
#    -> dist\release\crun-1.2.2-win64.zip + manifest.json（url 是相对文件名）

# 5) 安装器（两份：单文件 / 目录版）
pyinstaller packaging\crun_setup.spec --noconfirm --clean --distpath dist\installer
pyinstaller packaging\crun_setup_onedir.spec --noconfirm --clean --distpath dist\installer_onedir

# 6) 推 GitHub Release（gh 已登录时，会把 zip / manifest / 安装器一起挂上去）
python tools\publish.py --version 1.2.2 --github-repo OWNER/REPO `
    --installer dist\installer\crun-setup-1.2.2.exe --upload-repo OWNER/REPO
```

`publish.py` 会拒绝「exe 内嵌版本 ≠ 清单版本」的包，避免发出去的版本号对不上。
`.github/workflows/release.yml` 是同一套流程的 CI 版：打 `v1.2.3` tag → 构建 → 签名（secret
`CRUN_PFX_B64` / `CRUN_PFX_PASS`）→ 打包 → 挂到 Release。

## 8. 报毒（误报）处理

先做诊断：

```powershell
dist\win\crun\crun.exe doctor
# {"frozen":true,"motw":"none","signature":"NotSigned","running_from_temp":false,
#  "advice":["未签名：SmartScreen 会拦、AV 云信誉从零开始..."]}
```

这版构建已经在形态上做了五件事：**onedir 而非 onefile**（避免 `%TEMP%` 释放执行，
这是 `Wacatac.B!ml` 类启发式最典型的形态）、**不打 UPX**、**完整版本资源**、
**asInvoker manifest**、**自定义图标**。本机 Defender 对当前产物的扫描结果：

```
Scanning ...\crun.exe found no threats.
```

剩下的部分签名解决不了、也不该用加壳解决：完整清单（证书选择、微软/360/火绒/腾讯/卡巴的
误报提交通道、MOTW 与分发方式、仍被报毒时的排查顺序）在
[packaging/FALSE_POSITIVE.md](packaging/FALSE_POSITIVE.md)。

## 9. 命令

```powershell
python -m crun.cli simulate --lat 30.2741 --lon 120.1551 --distance 2400 --pace 370 `
    --account CAMPUS_ACCOUNT --ip 203.0.113.10 --tries 24 --out out --work-dir out
python -m crun.cli walk --lat 30.2741 --lon 120.1551 --distance 2200 --seed 7 --work-dir out
python -m crun.cli audit out\session.json
python -m crun.cli ledger list|hit|observe|decide --work-dir out
python -m crun.cli policy show|preflight|login|mode --work-dir out
python -m crun.cli hooks --out out\hooks.js --pkg com.TARGET.app
python -m crun.cli ui --port 8777 --work out
python -m crun.cli update https://TARGET.example/crun/manifest.json [--apply] [--dry-run] [--key KEY]
python selftest.py    # 26 项回归，当前全绿
```

实测输出（seed=7，24 条候选）：

```
[self-audit] score=0.0 verdict=RUN failed=[]
[route] fp=8230bddc0b8917ef cells=18 overlap=0.0 max_turn=26.9° candidates=24 accepted=true
session: 2129.7m / 879.0s / pace 412.7s/km mode=run
steps: 2104 cadence=151.7 ratio=1.001
```

`pace=412.7` 是「实际用时/里程」（含 1–3 次 15–50s 停顿），计划配速 370 是运动段配速，
两者差 10% 左右属正常；平台的配速校验看的是运动段。

## 10. 边界

- **基站/WiFi BSSID 与坐标不符**仍是客户端无解的一刀，需要真机在真实校园网内跑。
- **行为画像**（每周固定两次、里程精确到 2.50 km）只能靠 planner 的节奏分散，不能靠改客户端。
- 路线随机化降低的是「同一条线重复」的统计显著性，不改变「该时段该账号确实在跑」这一事实。
- 模拟器指纹（goldfish/ranchu、无 SIM）需真机。

> 合规提醒：伪造校园跑数据在多数学校属于体育成绩造假；账号封禁申诉要自己准备材料。
