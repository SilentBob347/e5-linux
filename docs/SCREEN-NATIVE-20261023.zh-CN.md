# 屏幕常驻服务原生化与验证（2026-10-23）

## 改动

将屏幕电源、双卡状态采集、语音音频及其 SSE/WebSocket 服务改为 C，
旧服务路径保留。`e5-voice-audio` 是 exec 原生程序的兼容入口，没有 Python 后备进程。
旧 Python 实现移至测试 reference 目录，不进入系统载荷。

- `t551m-screen-power`：监听背光内核事件、actual_brightness 通知及配置文件变化，
  取消 100 ms 轮询；先调整触控 inhibited，再切换亮度，保留关闭触控设置。
- `t551m-sim-status`：保留两路 AT owner、每五秒采集、卡号前后复核与原命令顺序，
  不接管 AT 端口、不切卡或改射频。保留 UCS2 运营商名称、LTE SINR、NR 信号和可选查询失败处理。
- `e5-voice-native`：订阅 MM 对象/属性变化，启动/重连时获取完整快照，不轮询 MM。
  重连及快照不完整时保留最后可信通话和音频，不猜测挂断。一秒状态更新时间不触发 MM/AT 查询。
  ALSA 操作在串行工作线程完成；SSE/WebSocket 与 D-Bus 共用主事件循环。
- 厂商内核 `drivers/unisoc_platform/sprd_audio/audiopipe/audio-pipe.c` 的语音字符设备
  没有 poll 方法，read 不处理 O_NONBLOCK。独立 C 线程阻塞等待 20 字节通知，以管道唤醒主循环，
  不使用轮询掩盖驱动约束；停止服务时取消并回收该线程。

保留 receiver/speaker/Bluetooth、静音、双卡通话切换、蓝牙请求归属、SCO NB/WB、
A2DP 暂停/释放、来电声音/震动/亮屏、Host/Origin 检查及有界的只读本机 API 传输。
本服务不创建、接听、挂断或删除通话，MM 继续拥有呼叫控制。

通用路由清单在构建时从 `rootfs/overlay/opt/e5/e5-call-audio.py` 的常量生成，
不复制两份路由表。运行时读取接收设备自身的音频参数、receiver-output、receiver-wiring、
音量上限及现有可选低音量参数；41S 沿用其 stock audio_route.xml 分组。
本次 E5 没有 codec.xml，保留原服务既有的模拟增益默认值；没有新增调音参数。
低音量配置如已存在，仅按原规则处理 DSP RAM，不写工厂音频文件。

HFP 网关、短信、MM 状态镜像、网络恢复以及详情/壁纸/提示音等按需工具仍有 Python 实现。
本次没有宣称整个系统已删除 Python。

## 构建与更新

共用入口 `devices/common/build-screen-native.py` 使用 `tools/build-layout.json` 的
native_screen 配置和既有 OpenWrt SDK，默认 Docker 镜像 debian:trixie。
可用 `--config` 或 E5_BUILD_LAYOUT 显式选择配置，不搜索旧包或替代 SDK。
每个 ELF 分别校验源码、头文件、构建器、工具链配置及产物 SHA-256。

在仓库根目录的 Linux 环境执行：

```sh
python3 tools/build-release.py run --label screen-native-build -- \
  python3 devices/common/build-screen-native.py
python3 tools/build-release.py run --label screen-native-tests -- \
  python3 devices/t551m/test_screen_native.py
python3 tools/build-release.py run --label screen-runtime-tests -- \
  python3 devices/t551m/test_screen_runtime.py -v
python3 tools/build-release.py run --label screen-profile-tests -- \
  python3 openwrt/tests/screen-profiles.py
```

输出在 out/native-screen。共享 infoscreen/stage.py 同时用于六种屏幕机型的新构建和更新，
复制三个 ELF、兼容入口、服务定义和路由清单，并移除三个废弃 Python 传输模块。
OpenWrt 根系统显式安装 glib2、libjson-c5、alsa-lib；不为此新增 Python 依赖。
CI 在 MM/BlueZ 编译后、临时 SDK 卷清理前编译原生服务，将其产物和源码指纹一起缓存，
避免装配时依赖已经删除的卷。此次只编译这些原生程序，没有重建完整系统、内核或安装包。

## 自动化验证

实际编译/运行生产 C 源码，使用临时文件、假 ALSA、私有 D-Bus、假 SCO 对端和本机 HTTP。
不格式化存储，不拨号，不向用户设备发送测试 AT 命令。

- 六项屏幕电源测试：亮灭屏顺序、触控设置、驱动无关发现、外部亮度、服务恢复和事件等待。
- SIM 快照与旧实现逐项对照：无卡/PIN/射频关闭、LTE/NR、无注册查询结果、UCS2 错误与 PHY 查询失败。
- 八组随机参数 × 五个衰减档位：C 生成的校准数据与既有实现逐字节一致；验证最大档和非目标数据不变。
- 假 ALSA：读取新值、保存/恢复、错误回退、双向 PCM 均先 prepare 再 start、音量范围和单调性、
  听筒/免提/蓝牙、静音保持、双卡切换及停止。
- 四种真实 Unix socket SCO 流程：成功、拒绝、取消、连接丢失；验证只释放服务持有的资源，暂停的 A2DP 被恢复。
- 原生进程接私有 MM：初始化、缺失 Call 对象后补全、通话属性事件、MM owner 丢失/恢复、无空闲 MM 轮询。
- 原生 SSE/WebSocket：初始/变化状态、分片、ping/pong、close、来源隔离、路径限制、chunked HTTP、
  每客户端四请求并行/八请求在途限制，以及 DSP 尚未就绪时仍可提供屏幕接口。
- 六种 profile 的共享 staging、原有通话/HFP 协议、CI 缓存及 SDK 清理顺序回归通过。

关键日志：

- out/build-logs/20261023-101135-native-screen-final-check-5834/command.log
- out/build-logs/20261023-101255-screen-native-shared-build-6093/command.log
- out/build-logs/20261023-101517-screen-native-portable-toolchain-6297/command.log
- out/build-logs/20261023-101539-screen-native-ci-gates-6349/command.log

## E5 实机结果与边界

已核对 SSH 主机、E5 profile、eMMC 身份和根分区，再部署至当前 USB 连接的 E5。
部署前确认没有通话，保留原服务文件于设备
`/root/update-backups/screen-native-20261023/`，不覆盖既有安装备份。
最终设备 ELF 与本地最终编译产物 SHA-256 一致。

使用 /proc/PID/smaps_rollup 的 PSS（KiB，按比例分摊共享页）：

| 常驻服务 | Python 版 | C 版 |
| --- | ---: | ---: |
| 屏幕电源 | 6059 | 116 |
| 双卡状态 | 6503 | 623 |
| 语音与屏幕传输 | 18750 | 1516 |
| 三项合计 | 31312（30.6 MiB） | 2255（2.2 MiB） |

三项合计 PSS 下降约 92.8%。这是这些进程的观测值，不等于整机释放内存的精确计量，
也不是通话/蓝牙活动时的峰值。
12 秒空闲窗口里，屏幕电源 0 CPU tick，双卡采集 2 tick，语音服务 7 tick。
该窗口未取得旧进程的配对 CPU 基线，因此不报告 CPU 降幅百分比。

实机通过：亮灭屏与触控禁用/恢复并还原原亮度、服务停止/重启、音频后端初始化、
MM 通话状态订阅、双卡新鲜快照、SSE 连接。原有 24 项设置/文件摘要均未变化；
九个工厂 NV 分区的只读与工作副本核验通过。没有重启整机。

尚未实机验证：本次 C 改动后的通话听感、来电提示、蓝牙耳机双向通话，以及其他机型实际音频。
这些有自动化协议/路由测试，不能替代人工听音或逐机型硬件验证。

## 二次回归与错误路径修正

用户要求复查后，新增故障注入并修正以下边界：

1. 挂断与音量/带宽变化同时发生时，混音器写入错误不得阻止 PCM 关闭。
   优先按可信呼叫状态释放音频，回报恢复错误，不继续保持 active。
2. UCI 返回非零且配置文件或暂存配置存在时，保留已缓存的音量/铃声选择，
   显示读取错误；不能悄悄按默认最大音量覆盖。缺少可选配置仍使用既有默认值。
3. PCM 启动失败时，释放已取得或正在取得的 SCO，并恢复本服务暂停的 A2DP。
   仅在可信的活跃呼叫仍存在时定时重试音频；先恢复本机 PCM，再恢复蓝牙协商。
   空闲或 MM 状态不可信时不执行重试，也不重新引入 MM/AT 轮询。
4. 子命令超时改为独立 GMainContext 驱动；服务主循环已停止时仍可取消和回收
   阻塞命令，不依赖已停止的全局事件循环，也不新增常驻超时线程。
   修复前故障测试可复现超时失效，日志：
   out/build-logs/20261023-104013-native-timeout-reproduction-7003/command.log。

新增覆盖：挂断时故障注入、主配置与其他节隔离、配置读取失败、PCM 失败后的 SCO/A2DP
释放、音频重试的有效呼叫条件，以及没有运行主循环时的命令超时。
假 ALSA 生命周期另以 ASan/UBSan/LSan 执行，未发现内存越界、未定义行为或泄漏。

最终完整回归日志：
out/build-logs/20261023-104048-screen-native-final-regression-7087/command.log。
该回归包含原生运行时测试、屏幕电源测试、六机型共享 staging、通用运行时 staging
及 CI 门禁。仍不把这些自动化结果当作真实通话听感验证。

部署状态：二次回归中的挂断、配置读取、SCO 释放/重试修正已部署当前 E5，
确认服务 ready、MM observer ready、设备 ELF 与当时源码编译结果一致。
最后加入的独立命令超时修正已通过完整回归及 ARM64 编译，但最终部署动作被自动审批拒绝，
工具仅返回 blocked by policy，未提供更具体原因。本记录不将该最后版本标为已在 E5 部署。

## 详细信息与系统页空白修复

实机确认 /api/advanced 和 /api/settings/system 都返回了错误 envelope，错误为
left-hand side is not a function。共同根因是 image_version 定义在 read_trim 之前，
ucode 在定义处绑定函数名，旧镜像版本读取路径调用到了未绑定的函数。
已将 image_version 移到依赖函数之后，共享构建和屏幕更新同样包含此修复。
HTTP 返回成功但正文只有 error 时，页面现在会走现有的加载失败/重试提示，不再把错误当空数据渲染。

已备份并更新当前 E5 的 API 和 app.js，只重载 api 服务实例，没有重启整机或改动配置。
实机 HTTP 和原生 WebSocket 均确认详细信息含 device/baseband/sim，系统分类有 13 项设置；
CPU、温控、充电、通知、声音、屏幕、界面、导航、USB、流量等实际使用分类读取接口的类别也正常。
APN/AT/设备/应用/蓝牙为前端专用视图，不使用通用 /settings/<id> 分类读取。

新增 devices/t551m/test_screen_metadata.py：完整 staged API 在真实 ucode VM 内验证
OTA 版本、旧镜像版本、损坏/空/类型错误的 OTA 元数据及缺少版本文件；
生产 pageRead 另验证错误 envelope、失败后的再次加载，以及带警告的有效数据仍可显示。
最终日志：out/build-logs/20261023-105035-screen-metadata-final-7700/command.log。
