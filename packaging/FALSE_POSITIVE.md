# 报毒（误报）处理手册

先分清四种"报毒"，处理方式完全不同：

| 现象 | 本质 | 处理 |
|---|---|---|
| SmartScreen「Windows 已保护你的电脑」 | 无签名 + 零云信誉 | **代码签名**，EV 证书即时建立信誉 |
| Defender `Trojan:Win32/Wacatac.B!ml` / `Behavior:Win32/...` | ML 启发式，常见于 PyInstaller 打包 | 改构建形态 + 提交误报 |
| 360/火绒/腾讯报 `Win32.Trojan.*` | 本地特征 + 云查，新文件默认可疑 | 提交误报 + 签名 |
| 用户机器上的"解压即删" | 压缩包继承 MOTW（ZoneId=3） | 签名安装包 + 说明 |

## 已经做到的（这版构建）

1. **onedir 而不是 onefile**。onefile 会在 `%TEMP%\_MEIxxxx` 释放内嵌 exe 再执行，
   这是 `Wacatac.B!ml` 一类启发式最典型的形态；onedir 没有这个行为。
2. **不启用 UPX**（`upx=False`）。UPX 压缩段是静态特征重灾区，会显著抬高检出率。
3. **完整版本资源**：`CompanyName / FileDescription / FileVersion / ProductName / OriginalFilename`
   （`packaging/version_info.txt`）。无版本信息的 exe 在世界各地都是可疑文件。
4. **内嵌 manifest**：`asInvoker`（不请求管理员）、DPI 感知、声明支持 Win10/11。
   要管理员权限的未知程序会被叠加一层 UAC 启发式。
5. **图标**：`packaging/crun.ico`。默认 PyInstaller 图标本身就是一个弱特征。
6. **裁剪依赖**：`excludes` 去掉 tkinter/numpy/pandas/PIL/sqlite3 等，减小体积与可疑面。

## 发布前必做

```powershell
# 1. 构建
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1 -Clean

# 2. 签名（PFX 或证书库指纹）
$env:CRUN_PFX_PASS = "PFX_PASSWORD"
powershell -ExecutionPolicy Bypass -File tools\sign.ps1 -Path dist\win\crun\crun.exe -Pfx cert.pfx

# 3. 自查签名/MOTW/Defender 状态
dist\win\crun\crun.exe doctor

# 4. 打包 + 清单 + 上传
python tools\publish.py --version 1.2.2 --url https://TARGET.example/crun/ --key KEY_MATERIAL
```

**证书选择**：OV 证书要攒信誉（几周内逐步变白），EV 证书对 SmartScreen 是即时生效的。
自签名证书对最终用户没有任何帮助（仍然"未知发布者"），只适合内网测试。

## 提交误报（免费，48h 内通常有结果）

1. **微软**：<https://www.microsoft.com/en-us/wdsi/filesubmission> 选
   *Software developer* → 上传 exe → 勾选 "I believe this file is incorrectly detected"。
   同一份文件被 Defender 报过才需要提交；提交时写明产品名与用途。
2. **VirusTotal**：<https://www.virustotal.com/gui/home/upload> 先传一次拿到全引擎报告，
   把报毒引擎名和结果页链接一起提交给对应厂商（VT 页面上每个引擎都有 "false positive" 反馈入口）。
3. **国内三家**（校园用户主力）：
   - 360：<https://open.soft.360.cn/report.php>
   - 火绒：<https://www.huorong.cn/>（论坛误报反馈区）
   - 腾讯电脑管家 / 哈勃：<https://habo.qq.com>
4. **卡巴斯基**：<https://opentip.kaspersky.com> → 文件 → "Report as false positive"。
5. 每次发新版都要重新提交一次 —— 误报白名单是按哈希的，换版本即失效。

## 传输与安装

- 分发 **zip** 会让每个文件各自带 MOTW；更稳的是做成签名安装包
  （Inno Setup / MSIX），安装后文件不带网络标记。
- 让用户从**固定域名**下载，不要用网盘短链（短链跳转会被云查降权）。
- 更新器本身也要过 `doctor`：更新包如果没签名，用户端 AV 会在替换瞬间拦下来，
  表现为"更新失败但没报错"。

## 仍被报毒时的排查顺序

1. `dist\win\crun\crun.exe doctor` —— 看 `motw`、`signature`、`running_from_temp`。
2. 拿报毒名反查形态：带 `!ml` 的是 ML 启发式（签名 + 提交最有效），
   带 `Behavior:` 的是运行时行为（检查是否在写 `%TEMP%`、是否自解压）。
3. 试 Nuitka 编译（`--standalone`）出一版对照：若 Nuitka 版不报而 PyInstaller 版报，
   说明是 bootloader 特征，直接把发布形态换成 Nuitka。
4. 别用"加壳/混淆"去对抗 —— 那是把误报变成真报，且会让签名失效。
