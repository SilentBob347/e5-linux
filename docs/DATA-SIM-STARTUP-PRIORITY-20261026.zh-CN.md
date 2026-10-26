# 上网卡初始化：延后副卡可选身份信息

2026-10-26。适用于共享 Unisoc ModemManager 的 E5、T551M、M8、T512N、远航 41S、K1 和 LYM-10K；新机型接入相同插件时一并使用。不修改设备、AT 通道归属、NV、SIM 射频保存值或用户上网卡选择。

## 找到的阻塞与本次边界

当前实现不要求两卡都注册成功才拨号，但整个共同上电和模式序列、卡槽枚举必须先完成。副卡命令若慢或超时，会拖住初始化。

其中副卡 `CIMI` 仅用于补全其 MM SIM 对象的 IMSI/运营商标识，不参与上网卡 APN 选择、身份加载或拨号。旧的 `load_sim_slots` 在读取副卡 CCID 后继续等待 CIMI（超时 5 秒），最后恢复选定卡 AT 上下文；这些工作全部在初始化关键路径。

本次仅移出其中的可选 CIMI，**不是完整拆分双卡 RF 初始化，也不宣称消除了全部副卡等待**：副卡 CCID 仍需先读，以保留真实卡槽/对象和后续短信路由语义；原有上下文恢复保留。共同 SIM 上电、两卡模式、SPSWDATA、SIM1/SIM2 协议栈顺序及开机回放均未改变。

保留该顺序的历史实机依据是 `docs/FINDINGS.md` §47.3：未设置双卡模式直接开启协议栈曾触发 7038；另一卡已附着时才从冷状态开启协议栈曾触发 7048。没有根据“主卡优先”的目标就盲目改变该硬件依赖。

## 最终行为

1. 初始化仍枚举副卡 CCID，返回同一个主/副卡槽结构。副卡存在性不会因为暂未读取 IMSI 而变为空。
2. 主卡的 SIM 身份、APN 自动匹配、注册和拨号照原流程继续，不等待副卡 CIMI。
3. 主卡进入 MM `CONNECTED` 后，由原 MM AT owner 发一次有卡槽限定的副卡 `CCID?;+CIMI`，再恢复上网卡 AT 上下文。没有新增物理端口、常驻服务、定时轮询或重拨。
4. 只有副卡对象仍位于原来的卡槽、模组仍有效、CCID 与原对象一致，才更新 IMSI/运营商标识。迟到回复不能覆盖新卡或新 MM 对象；模组已失效时不再发恢复命令。
5. 读取失败保留已知卡槽和 ICCID，不将数据连接判失败；本次连接期间不定时重试，下一次真实进入 CONNECTED 时可再次补全。成功后已有 IMSI 不重复查询。

在尚未联网时，**MM 的副卡可选 IMSI/运营商标识可能暂为空**，这是延后读取的结果；不是未插卡。网页/屏幕的独立 AT 信号采集入口未改。当前 APN 解析读取的是 `modem.generic.sim` 指向的上网卡，未改为读取这些延后字段；切卡后新主卡仍走完整的主 SIM 身份加载。短信、语音和射频控制的既有接口未替换。

## 实现与验证

- 新增 `rootfs/deb-patches/modemmanager-24-unisoc-secondary-metadata.patch`，通过通配补丁列表同时进入 Debian/OpenWrt 构建。
- `openwrt/build-modemmanager.sh` 修订号 E5REV=40；新增回归测试列入构建及 `tools/openwrt-package-state.py` 输入指纹。产物实际版本为 `1.24.0-r948`。
- `openwrt/tests/secondary-sim-metadata.py` 提取生产回调，以真实 GLib GTask/GObject 和 UBSan 编译执行。覆盖两种上网槽位、连接前不发 CIMI、空 IMSI 字符串、重复通知、缺卡、读取失败、CCID 不一致、旧对象释放、失效模组、命令上下文恢复与引用寿命。
- 完整 ModemManager 构建及其全部既有编译回归通过：双卡电源计划/射频权限、SIM 事件、短信隔离、通话、注册报文、16 个 SIPA 端口和移动网络原地续租。原厂电源序列测试仍按原顺序通过。
- 另外 APN 20 项、开机回放 9 项、AT 路由 3 项、网络恢复 14 项通过，共 46 项。
- 构建后插件 C 源码 SHA256 为 `fd71bbe3fcbdbc3775812f6f728cb218866bf5d49ad9b9bff469b56945f8db05`，与本次离线回调测试输入完全一致；APK 当前输入指纹验证通过。

本机使用现有 `e5-openwrt-src` 构建缓存，通过规定入口执行：

```sh
python3 tools/build-release.py run --workspace /home/kano/openwrt-build \
  --label modem-secondary-metadata -- bash openwrt/build-modemmanager.sh
```

日志：`out/build-logs/20261026-132550-modem-secondary-metadata-87394/command.log`，任务状态 complete。
产物：`out/openwrt/modemmanager-1.24.0-r948.apk` 与配套 rpcd APK。

本次没有重编内核、没有更新已发布完整 ZIP、没有部署或计时实测，不宣称实机提速固定秒数，也没有把此前 E5“运行一会儿无模组”认定为已经修好。

## 2026-10-26 22:11（Asia/Singapore）E5 热部署

经用户要求，已对连接电脑的 E5 应用上述 APK。部署前核对了机型、SSH 公钥及 eMMC 身份；另一个 `192.168.77.1` 的 MU300 系列设备未改动。E5 根分区为 `/dev/mmcblk0p71`，运行内核仍为 `6.18.54-e5-mobile4`。

- `modemmanager` 从 `1.24.0-r947` 升级到 `1.24.0-r948`；与旧已安装文件逐个比较，实际内容变化只有 `/usr/sbin/ModemManager`。未修改内核、NV、IMEI、热点、SIM 选择或射频权限。
- 原程序及 APK 数据库已备份并回读校验，保存于设备 `/root/e5-hotfix-secondary-metadata-r948/backup.tar.gz` 与电脑 `work/e5-secondary-sim/live/backup.tar.gz`。备份不含 NV。
- 安装时旧 daemon 尚在退出、新 daemon 抢先申请 D-Bus 名称，出现 `could not acquire ... service name`。已核对旧进程退出后重新启动服务并恢复 WAN；没有回滚源码、重启 CP 或加额外射频命令。后续热部署必须等待旧 daemon 退出、释放总线后再启动新服务，不能仅以 rc.common stop 返回判断完成。
- 最终进程 `/proc/<pid>/exe` 与磁盘中新程序 SHA256 都为 `0ecb38c772a9a2e134026f2f207b50dc36231f5cb39f64f65194d10780fd8443`；没有仅用磁盘文件推定加载状态。
- 两个 SIM 对象均保留有效 ICCID/IMSI/运营商信息；主卡为 SIM1，MM 状态 `connected`，注册 `home`，分组业务 `attached`。WAN 获得 IPv4 和 DNS，原网络恢复服务运行正常。
- 指定 `sipa_eth0` 向 `223.5.5.5` 发送 3 次 ICMP，3 次回复、0 丢包，RX/TX 计数均增加。该结果证明本轮热重启后有实际数据收发，不能推导弱信号、移动切换或冷启动的性能。

本轮没有整机重启或冷启动前后计时，尚不能报告节省秒数；完整 ZIP 未重新打包。
