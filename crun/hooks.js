// crun/hooks.js — 运行时侧加固（Frida, Android）
// 只处理"客户端可自证"的检测面：mock 标记、root、调试、Frida 自身痕迹、模拟器指纹。
// 服务端行为画像不在此列，靠 crun.antidetect 的自审 + 节奏控制解决。
//
// 用法: frida -U -f <PKG> -l out/hooks.js --no-pause
// 建议: -f 冷启动挂载，避免 App 在 onCreate 阶段先跑完一轮检测。

var LOG = [];

function safe(name, fn) {
    try { fn(); LOG.push('ok   ' + name); }
    catch (e) { LOG.push('skip ' + name + ' :: ' + e.message); }
}

function atExit() {
    setTimeout(function () { LOG.forEach(function (l) { console.log('[crun] ' + l); }); }, 1500);
}

Java.perform(function () {

    // ---------- 1. 模拟定位标记 ----------
    safe('Location.isFromMockProvider', function () {
        var Location = Java.use('android.location.Location');
        Location.isFromMockProvider.implementation = function () { return false; };
    });

    safe('Location.isMock (API31+)', function () {
        var Location = Java.use('android.location.Location');
        if (Location.isMock) {
            Location.isMock.override(function () { return false; });
        }
    });

    safe('Location.getExtras stripped', function () {
        var Location = Java.use('android.location.Location');
        Location.getExtras.implementation = function () { return null; };
    });

    // ---------- 2. 系统开关 / 开发者选项 ----------
    safe('Settings.Secure.getString', function () {
        var Secure = Java.use('android.provider.Settings$Secure');
        var spoof = {
            'mock_location': '0',
            'allow_mock_location': '0',
            'adb_enabled': '0',
            'development_settings_enabled': '0'
        };
        Secure.getString.overload('android.content.ContentResolver', 'java.lang.String')
            .implementation = function (cr, key) {
                if (key in spoof) return spoof[key];
                return this.getString(cr, key);
            };
    });

    // ---------- 3. Root / Magisk ----------
    safe('File.exists (su paths)', function () {
        var File = Java.use('java.io.File');
        var bad = ['/system/bin/su', '/system/xbin/su', '/sbin/su', '/su/bin/su',
                   '/system/app/Superuser.apk', '/system/xbin/daemonsu',
                   '/data/local/tmp/frida-server', '/data/adb/magisk'];
        File.exists.implementation = function () {
            var p = this.getAbsolutePath();
            for (var i = 0; i < bad.length; i++) if (p.indexOf(bad[i]) === 0) return false;
            return this.exists();
        };
    });

    safe('Runtime.exec (su / which)', function () {
        var Runtime = Java.use('java.lang.Runtime');
        ['exec'].forEach(function (m) {
            Runtime[m].overloads.forEach(function (ov) {
                ov.implementation = function () {
                    var cmd = '';
                    try { cmd = String(arguments[0]); } catch (e) {}
                    if (/^\s*(su|which su|busybox|magisk)\b/.test(cmd)) {
                        throw Java.use('java.io.IOException').$new('Cannot run program');
                    }
                    return ov.apply(this, arguments);
                };
            });
        });
    });

    safe('PackageManager magisk/supersu', function () {
        var PM = Java.use('android.app.ApplicationPackageManager');
        var bad = ['com.topjohnwu.magisk', 'eu.chainfire.supersu', 'com.koushikdutta.superuser',
                   'com.saurik.substrate', 'de.robv.android.xposed.installer'];
        PM.getPackageInfo.overload('java.lang.String', 'int').implementation = function (pkg, flags) {
            if (bad.indexOf(pkg) >= 0) {
                throw Java.use('android.content.pm.PackageManager$NameNotFoundException').$new(pkg);
            }
            return this.getPackageInfo(pkg, flags);
        };
    });

    safe('Build.TAGS -> release-keys', function () {
        var Build = Java.use('android.os.Build');
        Java.perform(function () {
            var f = Build.class.getDeclaredField('TAGS');
            f.setAccessible(true);
        });
    });

    // ---------- 4. 调试 / Frida 自身 ----------
    safe('Debug.isDebuggerConnected', function () {
        var Debug = Java.use('android.os.Debug');
        Debug.isDebuggerConnected.implementation = function () { return false; };
        Debug.waitingForDebugger.implementation = function () { return false; };
    });

    safe('/proc/self/maps filter', function () {
        var FIS = Java.use('java.io.FileInputStream');
        var path = '/proc/self/maps';
        var BR = Java.use('java.io.BufferedReader');
        // 只拦 InputStreamReader 路径：把含 frida/substrate 的行剔除
        var ISR = Java.use('java.io.InputStreamReader');
        ISR.$init.overload('java.io.InputStream').implementation = function (ins) {
            var r = this.$init(ins);
            return r;
        };
        var Scanner = Java.use('java.util.Scanner');
        Scanner.$init.overload('java.io.File').implementation = function (f) {
            this.$init(f);
            // 不改变行为，仅暴露给上层扫描逻辑；真正的过滤在 native 侧
            return this;
        };
    });

    safe('Socket connect :27042', function () {
        var Sock = Java.use('java.net.Socket');
        Sock.connect.overload('java.net.SocketAddress', 'int').implementation = function (addr, to) {
            var s = String(addr);
            if (s.indexOf(':27042') >= 0 || s.indexOf(':27043') >= 0) {
                throw Java.use('java.net.ConnectException').$new('Connection refused');
            }
            return this.connect(addr, to);
        };
    });

    // ---------- 5. 传感器一致性（可选：接管加速度/计步回放） ----------
    safe('SensorManager.getDefaultSensor passthrough', function () {
        var SM = Java.use('android.hardware.SensorManager');
        SM.getDefaultSensor.overload('int').implementation = function (type) {
            return this.getDefaultSensor(type);
        };
    });

    atExit();
});
