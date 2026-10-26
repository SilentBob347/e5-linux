# E5 启动有信号、随后显示无模组：静态排查

2026-10-26。用户反馈来自另一台 E5，没有故障日志、准确安装包版本或本地修改清单；用户自己的设备不复现。本次没有操作连接设备、AT、射频、NV 或启动选择，也没有部署或打包。

## 结论边界

不能从这段现象认定是 NV、信号差、硬件损坏或用户用 AI 修改造成。已确认一条可能把暂时异常变成长时间无模组的宿主侧恢复缺口；最初导致 AT 异常的原因仍未确认。

“未注册/无网络”与“模组对象消失”不同。界面文字本身也不足以证明 CP 已经停止运行：管理总线调用失败或 ModemManager 退出，同样可能使状态读取失败。

## 已确认的代码路径

### 1. AT 连续超时后，模组对象可能被移除而不重新探测

对照本机现有只读构建缓存的 ModemManager 1.24.0 已打补丁源码：

- `src/mm-base-modem.c`：`DEFAULT_MAX_TIMEOUTS` 为 10；Unisoc 构造函数没有覆盖它。
- `port_timed_out_cb()` 到达该次数后，取消 modem-wide cancellable，令对象失效，但没有将 `reprobe` 设为 TRUE。
- 相邻的 `port_removed_cb()` 则明确先设置 `reprobe = TRUE` 再取消，两条分支不同。
- `src/mm-device.c:modem_valid()` 移除无效模组后，只有 `mm_base_modem_get_reprobe()` 为真，才安排 `reprobe()`。
- 当前 `e5-network-recovery` 调用 `mmcli -m unisoc-sipc -J` 获取对象，再恢复 netifd 的数据连接；对象不存在时只会等待下一次状态事件，不负责重建对象。
- `e5-mm-report-ports` 在启动/加载驱动时报告端口。不能把它等同于 AT 超时后的对象重建机制。

因此，在 **AT 连续超时且 SIPC 端口没有消失/重新出现** 的条件下，即使 AT 后来恢复，也存在持续没有 MM 模组对象的路径。这不是已经复现的群友故障，也不表示应无限重启 MM、重启厂商服务或强制复位 CP。当前没有修改上游的超时失效策略。

### 2. 真正的 CP 断言也能产生相同现象

仓库既有 E5 报告记录 CP Alive 后约 23 秒出现：

```text
drm_rfresourcehandle.c:3925
Drm allocate spr rf path fail! res_type=16
```

见 `docs/MODEM-ASSERT-RECOVERY-20261015.zh-CN.md` 和 `docs/FINDINGS.md`。这是历史设备证据，不是本次群友的日志；不能根据相似症状认定断言签名相同。

当前公共 staging 已启用 `e5-modemd`：被动接收厂商 Assert/Blocked 后确认 dump 完成，让厂商按原流程恢复。它不主动发送 Blocked，不修改 AT/RF/NV。SIPC 驱动在通道离线时移除 WWAN AT 端口、在线时重建。这条真实通道掉线路径与上面的“端口还在、MM 因超时失效”需要分别判断。

### 3. NV 校验不是定时关停机制

`devices/e5/stage.py:stage_nv()` 在厂商进程启动前执行 `t551m-nv-prepare`。它校验隔离副本、设置 loop 并记录本次来源；不是开机后定时校验失败再关停基带的任务。正常已经注册后再消失，不足以推导为这项启动校验拒绝。

NV 工作副本写入时的存储异常、`cp_diskserver` 异常退出仍是另一类可能性，需要当时的 I/O/进程错误证明，不能由上述结论排除。

## 已核对的现有保护

- 厂商 `modem_control`、`cp_diskserver` 由 procd 管理，正常退出路径之外的进程异常有 respawn；不能因此保证 CP 本身一定恢复。
- 预拨号回放发生在 MM 开始使能/拨号之前；没有为这次排查增加晚回放、SFUN 或服务重启。
- SIM ECIND 事件先确认选定卡的 CPIN，再使用 MM 的 SIM 检查流程；SIM busy/超时不会直接被当作拔卡。
- 数据重试与射频重启分离，不能修复一个已经消失的 MM 对象。
- AT 命令环/URC 环归属及另一卡 URC drain 仍存在；没有发现近期代码直接取消该保护。

## 离线回归

以下测试均不访问硬件，不能称为实机故障复现或硬件验收：

- `openwrt/tests/modem-recovery.py`：10 项通过，真实 C 助手和私有 socket。
- `openwrt/tests/network-recovery.py`：14 项通过。
- `openwrt/tests/modem-port-discovery.py`：10 项通过。
- `devices/t551m/test_boot_replay.py`：9 项通过。
- `devices/t551m/test_network_startup.py`：18 项通过，输入为现有构建缓存的包源码。
- `openwrt/tests/sim-events.py`：实际插件函数编译测试通过。
- `openwrt/tests/sim-power.py`：实际插件电源回调编译测试通过，含 8 种插卡/首选卡组合及各步骤失败。

共 61 项 unittest 与 2 组编译测试通过。读取构建缓存的容器使用已有镜像、只读 volume、禁用网络，未编译新包或修改缓存。

## 如再次遇到，如何区分

故障发生后先保留状态，不先重启或切网：

- `marking modem as invalid`：优先核对连续 AT 超时，以及 `/sys/class/wwan/` 端口是否一直存在。
- `Modem Assert` / `Drm allocate spr rf path fail`：CP 固件断言，核对厂商恢复日志。
- `channel down ... AT port removed`：SIPC 通道确实下线，跟踪后续 channel up 与端口重建。
- `Out of memory` / `Killed process` / 服务 crash：进程或内存问题，不能归为射频故障。
- `I/O error` / 只读文件系统 / NV 写错误：存储路径问题，需要保留工作 NV 与原始错误。

当前没有足够证据确定本次属于哪一类。未把“可能被 AI 修改”当作诊断结论，未用定时复位、放宽 NV 校验或增加 AT 重试掩盖现象。

## 同日 U30 Air 反馈的交叉核对

MU300 维护树使用独立 AT broker / mu300cell，不使用这里的 ModemManager。已在其公共双卡脚本发现 U30 专有的冷启动存在性判断问题：SIM 未上电也可能返回 CME 10，新入口可能因此跳过实际上插着的卡；该仓库已补 U30 专有预检及离线回归。记录位于 MU300 仓库 `docs/U30AIR-NO-NETWORK-AUDIT-20261026.zh-CN.md`，尚未实机验证或打包。

这不能用于解释 E5 的“已有信号后模组消失”。E5 的原有 CPIN-before-SFUN 行为有不同实机依据：上电前 CPIN 可读，强开空卡槽协议栈反而出现过 `mnphone_api.c:7048` 断言，因此未照搬 U30 上电预检，也未改动 E5 的射频时序。
