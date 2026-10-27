# 信息屏省电优化（2026-10-24）

本次只优化共享信息屏的定时器、请求并发和重复背光写入。
蜂窝、SIM、AT、射频、网络恢复、Wi-Fi 参数与充电策略不在改动范围内。
实现位于共用 infoscreen staging 路径，六种屏幕 profile 的新构建和屏幕更新都会携带。

## 已完成

- 顶栏和锁屏合用一个时钟定时器，按实际显示的秒/分钟边界调度。
  熄屏取消定时器，唤醒立即绘制当前时间；保留显示秒的设置。
  原先两个每秒执行一次、进入回调后才判断是否熄屏的 interval 已移除。
- 流量页和高级信息页的周期刷新改为读完后再调度下一次。
  熄屏取消页面定时器，唤醒恢复；旧页面请求的完成不会重建或替换新一代定时器。
- 状态读取只允许一个请求在途。请求期间的多次刷新/唤醒合并成一次后续补读，
  避免并行请求结束后各自建立周期刷新链。错误时释放在途状态，允许重试。
- 原生背光工具逐个读取当前亮度，相同值跳过驱动写入。
  触控策略仍独立核对，保留显式关闭触控、亮灭屏顺序和事件监听。

状态轮询保持亮屏 2 秒、熄屏 5 秒；短信、通知、来电及电源插拔的唤醒路径保留。
没有通过延长通知轮询、停止浏览器或终止后台应用获取省电效果。

## 验证

- 原生 screen-power 的 8 项测试通过，实际编译并运行生产 C 源码：
  反复亮灭、配置变化、外部亮度、触控禁用、事件等待、重复值及多背光独立核对。
- Chromium 虚拟时钟测试通过：分钟/秒模式、熄屏 65 秒无时钟回调及页面刷新、
  本地/外部亮灭屏恢复、20 次刷新合并、失败重试、页面请求跨睡眠竞争、通知唤醒。
- 现有设置唤醒竞争、充电插拔唤醒回归通过。
- 现有完整屏幕浏览器回归通过：手势、导航、设置、外观、网速单位、唤醒保护、
  电源菜单、拨号键、信号布局；没有 JS 异常。
- 六种 profile 的共享 staging 验证通过。
- 使用注册 SDK 经 tools/build-release.py 编译 arm64 t551m-screen-power 成功。
  日志：out/build-logs/20261024-054619-screen-power-saving-65887/command.log。

初次代码验证时未部署设备；随后按用户要求部署到 T551M，详情见下节。
本次未生成整机安装包。这些验证不是整机功耗、待机时长或硬件休眠成功的实测结论。

## T551M 部署

已核对 SSH 主机密钥、t551m profile、内核 6.18.54-t551m-otg10 和 eMMC 身份摘要，
确认当前没有通话。设备原有两个脚本与本次优化前版本一致。

仅替换以下三个文件并重启信息屏与背光监听服务：

- /usr/share/e5-infoscreen/www/app.js
- /usr/share/e5-infoscreen/www/mobile.js
- /usr/libexec/t551m-screen-power

上传前、部署后均核对 SHA-256；HTTP 实际提供的 app.js 与本地产物哈希一致。
设备原件保存在 /root/update-backups/power-saving-20261024-055539/，附 manifest.sha256。
电脑备份为 work/power-optimization/t551m-deploy/20261024-055539/original-files.tar.gz，
已解包读取校验；同目录 deployment.json 记录新旧文件哈希和验证结果。

设备测试依次设置亮度 0 → 120 → 0，每步等待 6 秒核对物理背光、状态接口和
直接触控输入的 inhibited 值。结果分别为熄屏/触控禁止、亮屏/触控允许、熄屏/触控禁止。
最后恢复部署前亮度 0。服务保持运行，近期日志未发现匹配的 JS 异常或屏幕同步失败。
本次没有重启整机；boot ID、信息屏配置哈希、ModemManager/语音进程 PID 均未改变。
尚未进行部署前后整机功耗对照，也未通过远程 JS 调试器读取设备内的定时器状态。

### 来电故障及最终部署状态

用户随后反馈正常回铃但设备没有来电提示。排查时原生语音服务
observer_ready=false，错误为 Waiting for complete call state。
先将省电的三个文件完整回滚并重启信息屏，观察器仍未恢复。

直接读取设备 D-Bus 确认：Voice.Calls 列出了 Call/0、Call/1，两个对象可通过
Properties.GetAll 读取，状态均为 terminated；但 GetManagedObjects 没有返回它们的
Call 接口属性。旧观察器反复获取总快照仍无法补齐这些属性，因而一直阻塞通话状态处理。
之前的离线模拟把 Call 放入总快照，漏掉了设备实际的独立导出方式。

已修正共享 native/voice.c：缺少 Call 属性时直接对对应路径异步读取 GetAll，
每个路径只保留一个读取，三秒超时；旧回复按 owner epoch 和对象修订号丢弃。
失败保留已有可信状态，通过原有恢复节奏重试；不发送通话控制或 AT 指令。
停止服务等待在途 Call 读取结束，再释放其跟踪表。

原生运行时 8 项测试通过，新增覆盖独立 Call 导出、重新连接、空闲无重复读取、
延迟 ringing 回复与终止事件竞争。修复 ELF 已备份原件、校验上传并单独重启语音服务；
观察器恢复 observer_ready=true、error=null。用户第一次拨入确认正常。

随后重新部署这三个省电文件，保留语音修复。ModemManager 和语音进程未因重新部署
信息屏而重启。设置熄屏后，用户第二次拨入确认亮屏、响铃和接听界面正常。
最终设备处于“省电优化 + 独立 Call 读取修复”状态，并非只回滚省电改动。
语音修复记录为同一部署目录 voice-fix.json；旧语音 ELF 同时保存在该目录和设备备份目录。

## 显示硬件仍需处理的部分

先前 M8/T551M 实机快照显示背光为零时 DRM CRTC 仍 active，DPU/DSI 仍在运行。
本次取消 JS 定时唤醒不等于关闭显示扫描，也不等于系统 suspend。
显示输出由 Cage 持有，需要通过合成器与驱动支持的显示电源路径协同关闭和恢复。

检查现有内核源码还发现 dpu_r6p0.c 的 disable_vsync() 寄存器清除被注释，
但同一个 VSYNC 中断同时参与 writeback、CABC 工作，不能仅取消注释就判定安全。
本次没有修改该中断，也没有移除 clk_ignore_unused / pd_ignore_unused /
regulator_ignore_unused。后续应结合各机型原厂驱动和设备树验证资源归属、
显示关闭/恢复和触控/电源键唤醒，再进行硬件层改动。

## 重跑

浏览器测试和现有屏幕回归使用相同的 --fixtures FILE --webroot DIR 参数。
webroot 应由 devices/common/infoscreen/stage.py 的 sources() 或 stage() 生成，
避免拿旧的 app.js 测试新源代码。

```sh
python3 devices/t551m/test_screen_native.py -v
python3 devices/t551m/test_screen_power_saving_browser.py --fixtures FILE --webroot DIR
python3 devices/t551m/test_wake_refresh_browser.py --fixtures FILE --webroot DIR
python3 devices/t551m/test_screen_charger_wake.py --fixtures FILE --webroot DIR
python3 openwrt/tests/screen-profiles.py
```
