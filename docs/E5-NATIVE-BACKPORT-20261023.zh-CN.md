# E5 共享运行时与启动优化移植

后续已在用户连接的 E5 上部署新内核及运行时，具体实测和备份范围见
[E5 部署验证](E5-NATIVE-LIVE-20261023.zh-CN.md)。下文的验证边界记录代码移植完成时的状态。

日期：2026-10-23。工作基线为 E5 `main` 的 `bfb8c8f5`，覆盖 E5、T551M、M8、
T512N、远航 41S、K1 的共享构建路径。没有修改安装器、分区算法、默认启动意图、
通话路由或各机型充电参数，没有恢复已取消的机型，也没有提交或推送。

来源为 MU300 维护分支本轮已适配的优化，而非直接合并旧 main：

- liuwang97 `cpu-load`：`ccf89bb65e283f1c609f507f4c51585b929b6e99`。
- liuwang97 `boot-speed`：`1fb42bebd75a0dfdfa9493cf4d1069e430ad7f1e`。
- PR #373：`85d25c4b03ecaa2d3d6775b2505f09ed7b812860`。
- 本地 MU300 源码与核查记录：`../mu300-linux-clean-tf-7.2/` 的
  `docs/LIUWANG97-BACKPORT-AUDIT-20261023.zh-CN.md`。

## 平台适配

E5 的拨号、短信、通话和 URC 由 sipc_wwan / ModemManager 管理，不能换成 MU300
直接管理这些通道的整套 daemon。保留本地所有者、双卡地址、命令顺序、启动回放、
用户射频选择、充电和屏幕控制，以操作为单位替换实现；不增加失败后切回旧后端的分支。

| 范围 | 当前处理 |
| --- | --- |
| 专用 AT 所有者 | 新增静态 arm64 C `atd.c`，替换包内三个 Python 所有者；nr2 交互、nr6/nr7 采集，nr1 与 URC/短信通道仍归原所有者。保留 JSON/plain 协议、100ms 间隔、请求期限、独立队列、超时隔离、迟到终止码及两步只读恢复。探针拒绝不关闭描述符，写命令不重发。flock 在打开设备前取得；核对驱动公开的 cmd_ring/urc_ring/drain_rings，保留合法的 urc_ring=-1。通过 WWAN/kobject 事件检查真实端口代际，空闲阻塞等待。 |
| 系统与速率采集 | 新增 rpcd 常驻 `e5status`；系统快照直接读 proc/sys、UCI、ubus、rtnetlink、nl80211 和 statvfs。网速维持每卡八个 CID 计数之和、浮点时间及 ifindex 语义。原 CLI 只转调同一个新 RPC，不自行选择旧采集器。 |
| ModemManager 状态 | 只读 D-Bus 属性镜像，订阅后取得初始快照，重放期间事件；处理属性失效、对象移除、MM 消失与重现。原库已随包携带，不增加 GI 扩展。没有周期扫描或 AT 请求。镜像仅保存当前模组与 SIM/APN 所需属性，文件权限 0600；不写短信正文、通话号码或密码，也不通过看板返回 ICCID/IMSI。 |
| 工程信息 | 保留 E5 原有工程字段解析、分段发布、并发池、实时信号入口和 AT 顺序。由常驻 RPC 异步启动原采集器，不把 MU300 不同固件的 LTE/NR 字段布局强套进来，也没有两套失败接管路径。 |
| 热点客户端 | 原生关联列表与 hostapd 的实际 assoc 状态，过滤无效/广播 MAC、零信号及无效率值。保留 E5 原有按 ifindex 隔离、五秒期限、一秒共享预算的异步 station-get 补测；只补缺失指标，不增加不存在的客户端。 |
| 短信通知 | 每五秒只检查共享收件箱的原子替换签名，变化后才下载列表；保留两卡合并通知、首次静默基线、只通知收件、清空重建。失败不消耗签名，隐藏页面暂停，并发请求互斥。原 SIPC sysfs 事件收件、分卡存储、归档及转发保持原实现。 |
| 充电控制 | 将 e5-charge 的 Shell 循环完整改为 ucode，使用现有 power_supply 热插拔事件，并保留原三十秒安全检查。原阈值、滞回、充满一次、重插恢复 HiZ 和退出恢复充电不变。释放操作会尝试两个控制写入并报告失败；不引入 U30 电池颜色、充电芯片或电量算法。 |
| USB 守护 | OpenWrt 入口完整改为 ucode，监听 USB/UDC/extcon/power_supply 事件，仍保留原两秒安全检查。保持 SDP/CDP、extcon、手动复位锁、每轮最多五次恢复、原冷却与一秒软重连规则；不解绑 gadget，不关闭网卡，退出时恢复自身尚未完成的软断开。Debian 的显式平台入口保持原实现。 |
| 后台小核 | 只限制新 AT 所有者、属性镜像、网络恢复及短信通知进程和它们的子进程。按实际在线 CPU capacity 识别，不写热插拔、频率、调压或 IRQ；不限制屏幕、音频、ModemManager 或整个 services cgroup。保留已有 services_cpus 选择，默认 little，可显式配置 all。 |
| 启动 | 保留已经存在的 printk=4；新增异步熵初始化和模块预读。分区发现改为 100ms 检查且 mdev 频率仍为一秒；WCN、SIPC 就绪改为 200ms 检查，原 6/20、15、120 秒预算不缩短。保留 WCN 固件交接、动态 A/B、持久日志、安全定时器、常规模块加载和故障恢复。 |
| 监管库 | 保留数据库和签名的先行交接，去掉 reload 后固定一秒等待，失败明确报告。E5 本来没有 MU300 那个二十秒 fallback 等待，不能声称这里同样节省二十秒。 |
| 内核 | 共享准备器加入 NCM/RNDIS OS descriptor 释放后清空指针的修复；启用 UCLAMP、THERMAL_NETLINK。UMS9620 LP_AP_INTC 模块接入内核构建及完整模块交付，启动时仅对实际 sprd,ums9620 加载；模块自身再核对 DT、GIC 与时钟门控。保持 suspend/unload 的原位恢复，不改变用户 idle 策略。 |

流量账本已经是常驻 ucode/uloop；网络恢复、收件和电池保护已经使用本地事件机制，
这些原实现继续保留。E5 的屏幕、按键、蓝牙和通话功能不由 MU300 sysd 接管。
本地 WCN 走 SDIO，没有移入针对 Marlin PCIe 初次 probe 的修改；U30/V50 的灯组
和电源策略也不适用于这里。这些属于平台边界，不是增加另一种备用算法。

## 构建与更新接线

- `devices/t551m/ui.py` 为六个机型暂存同一份新运行时，AT 所有者按源码/二进制
  SHA-256 缓存并检查 arm64 ELF。包内不再暂存旧 `atd.py`，该文件只作历史回归对照。
- `openwrt/build-rootfs.sh` 和增量 `build-profile-tf.py` 均安装原生 RPC 所需包。
  增量路径显式补齐旧基础 root 缺少的依赖；结束审计要求新脚本、模块和二进制齐全。
- E5、T551M、M8 的共享内核准备调用同时覆盖 T512N、41S、K1 的既有继承链。
  common config 的扩展功能校验会拒绝缺少新选项的旧内核；交付校验也要求 LP_INTC 模块。
- 沿用原构建锁、模块配套与哈希校验。没有复制完整 rootfs、重建安装器、组装发布包、
  触碰用户设备或执行任何实机分区/刷写。

后台服务可以通过 `unisoc_modem.main.services_cpus` 选择 `little` 或 `all`。
选择在该服务下次启动时应用；不要为改变调度在 CP 运行时反复重启 AT 所有者。
部署新运行时与配套内核后正常重启，使新所有者在冷启动接管。

## 验证证据

所有命令经过 `tools/build-release.py run`。设备、USB、充电控制和 MMIO 写入均使用
私有夹具；实际执行原生 ucode、uloop、ubus、rpcd、D-Bus 和编译后的 C。

| 范围 | 最终结果及证据 |
| --- | --- |
| 新 C AT 所有者 | 主机 17 项通过；实际 arm64 静态程序 17 项中 16 通过，1 项主机编译客户端用例已在主机通过。[端到端日志](../out/build-logs/20261023-065750-e5-native-at-release-validation-37261/command.log) |
| C 内存安全 | ASan/UBSan 执行两万份有界畸形 JSON/UTF-8 输入，无越界或未定义行为；与上一行同一日志。 |
| 原有兼容功能 | 主机 75 项中 71 通过、4 项需要原生 ucode 的检查转到 ARM64 容器执行；另含真实电源事件分类。[主机回归](../out/build-logs/20261023-064216-e5-shared-compatibility-33178/command.log) |
| 六机型暂存、启动等待、D-Bus 生命周期、原生快照 | 分别 1 项（含六机型子用例）、3 项、1 项、8 项通过。[运行时整合日志前半](../out/build-logs/20261023-064946-e5-runtime-integration-36647/command.log) |
| 真实充电/USB 事件及 SIGTERM、策略、rpcd 插件 | 分别 2、7、1 项通过；旧 APN/CID 回归的行为用例也通过。[原生服务日志](../out/build-logs/20261023-065031-e5-native-services-final-37037/command.log) |
| 热点指标及补测并发、MM 属性过滤、LP_INTC MMIO | 见[补充回归](../out/build-logs/20261023-065730-e5-native-compatibility-final-37191/command.log)；生产 LP_INTC C 直接跑八种 MMIO 场景，包括卸载/suspend 恢复、错误 SoC、不映射关闭块与失败清理。 |
| K1 完整内核 | `6.18.54-k1-bringup1` Image、Image.lk 与 235 个配套模块通过构建和完整哈希/内嵌 config 检查，含新 LP_INTC；原缓存权限问题后改用原有 root 构建方式，没有重置源码。[构建日志](../out/build-logs/20261023-062721-k1-native-backport-kernel-3144/command.log) |
| 最终交付约束 | CI 输入/发布审计 13 项通过，旧内核拒绝及模块准备/MMIO 3 项通过；重新核验实际 K1 产物，入口 Shell 语法检查通过。[最终审计](../out/build-logs/20261023-070624-e5-native-final-audit-37920/command.log) |
| 原启动默认值与分区根目录回归 | 两组各 9 项及构建任务运行器 14 项通过；该日志末尾的旧 Wi-Fi 审计夹具失败已在最终审计修复。[约束回归](../out/build-logs/20261023-070327-e5-native-final-contracts-37355/command.log) |

保留了失败日志：初轮工具/语法检查、K1 缓存权限、测试夹具初始化短暂删文件、
容器漏复制 Makefile，以及 Python 模拟 iw 的解释器启动超过正式查询期限。最后一项
改用 FIFO 明确同步的轻量夹具，没有延长正式程序的 300ms 单次/1s 总预算；补齐 Makefile
后打包接线检查单独通过，见[接线补测首项](../out/build-logs/20261023-065624-e5-native-compatibility-finish-37137/command.log)。
原发布审计夹具漏带现有 Wi-Fi SAE 源码与载荷，已补齐真实来源并新增过期标记、
缺失运行文件拒绝用例；最终 13 项通过，生产哈希校验没有放宽。
没有通过删除行为用例、屏蔽异常或切回旧服务得到通过结果。

## 实机与发布边界

本轮没有新的 E5 实机验证。不能把此前 K1 通话/触控验证、U30 Air 的启动时间或
上游待机数据算作本次 E5 原生化的实测。各机型冷启动、USB 拔插、双卡/热插卡、
通话/蓝牙、充电、休眠唤醒及长期功耗仍需用配套系统验证。

只编译了 K1 的完整新内核；其余五机型需要通过各自原构建器重编后才能生成新发布包。
既有旧内核不能绕过新增配置/模块检查混入新包。K1 的 Image 和模块也必须整套使用，
不能仅凭相同 release/vermagic 将新模块拷进旧内核。本轮没有产生可对外发布的固件包。
