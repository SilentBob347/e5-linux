# T512N 运行约十小时后崩溃：指令完整性核对（2026-10-26）

## 结论与边界

已确认这次是内核异常触发 panic 和自动重启。更关键的现场证据是：`tick_program_event` 中相邻两条指令与本地对应构建不一致，错误指令的运算结果与崩溃寄存器完全吻合。因此，不能仅因调用栈经过 cpuidle/hrtimer 就归因于深度休眠、时钟事件对象坏指针或定时器逻辑本身。

目前能够确认的是**故障现场的内核代码完整性异常**。谁改变了这 8 字节、它发生在加载阶段还是运行阶段，现有材料尚不能确定。不能据此宣布所有机型都有相同缺陷，也不能以本地镜像正常就排除公共驱动的运行时破坏。

本轮只解包和读取报告、比对源码/符号/内核交付件；没有修改生产驱动、关闭休眠、调压、刷机或操作任何设备 NV。

## 输入

- 群友报告：`D:\Downloads\Telegram Desktop\T512N-crash-report-20261026.tar.gz`。
- 现场文件保存在忽略目录 `work/t512n-crash-20261026/`；包括原始 README、pstore、重启后的日志和系统信息。
- 报告内核：`6.18.54-t512n-bringup1 #5`，构建时间 `Sat Oct 24 02:13:04 +08 2026`。
- 对照对象目录的 `include/generated/utsversion.h` 也是 `#5 SMP Sat Oct 24 02:13:04 +08 2026`，与群友 uname 一致。
- 对照交付件：既有 `/home/kano/openwrt-build/kernels/t512n/Image`、`System.map` 和 `/home/kano/openwrt-build/objects/t512n/vmlinux`。
- `Kernel Offset: disabled`，符号地址和故障偏移能够直接对应。`tick_program_event` 起点 `0xffffffc0801702d8`，故障 PC 为 `+0x2c`。
- 反汇编用 AArch64 GNU objdump 及 LLVM objdump 交叉核对；没有重新编译内核。

## 最有决定性的证据

崩溃的五条指令：

```text
91172129 9e42f2f3 30d62a21 92f00014 (f8696900)
```

对应本地发行 Image 和 vmlinux：

```text
91172129 aa0003f3 d538d088 92f00014 (f8696900)
```

| 地址 | 正常指令 | 报告现场指令 |
| --- | --- | --- |
| `0xffffffc0801702f8` | `aa0003f3`: `mov x19, x0` | `9e42f2f3`: `scvtf d19, x23, #4` |
| `0xffffffc0801702fc` | `d538d088`: `mrs x8, TPIDR_EL1` | `30d62a21`: `adr x1, 0xffffffc08011c841` |

两条相邻指令一共 8 字节，位差合计 31 个 bit。这不符合单个 bit 翻转的简单形态，但仍不能凭位差数量判断写入源。

异常 ADR 指令算出的 **`x1=0xffffffc08011c841`**，与原报告的 x1 **完全相同**。因此不只是拿到不同镜像或把日志打印坏了的泛泛怀疑：寄存器现场也支持 CPU 执行过这条异常指令。

由于原本读取 per-CPU 偏移的 MRS 被替换，x8 保留为日志中的 `0x11`；随后仍执行的 LDR 用 x8+x9 取地址：

```text
x9 = 0xffffffc08185c5c8   # System.map 中 tick_cpu_device 的模板地址
x8 = 0x11
x9 + x8 = 0xffffffc08185c5d9
```

结果与日志中的 translation fault 地址完全相符。此处还没有成功读出 `clock_event_device *`，所以不能直接把它描述为这个对象本身已损坏。

## 合法运行时替换的核对

- ELF 的 `.altinstructions` 在这个函数里只有一处匹配：`0xffffffc0801702fc`，长度 4 字节。
- 合法替换字为 `d53cd048`，即读取 TPIDR_EL2；不可能解释现场的 ADR，更不解释前一条 MOV 同时变成浮点转换。
- 函数入口有两个用于可修补入口的 NOP，故障的两条指令位于函数内部；不能把这 8 字节当作普通入口 ftrace 修补。
- 配置启用了 `CONFIG_STRICT_KERNEL_RWX=y`、`CONFIG_STRICT_MODULE_RWX=y`。这使直接 CPU 写只读代码值得警惕，但不能排除别名映射、驱动 DMA、固件写入或硬件一致性/存储问题。

上游的 [tick_program_event 源码](https://github.com/torvalds/linux/blob/v6.18/kernel/time/tick-oneshot.c) 确实通过 per-CPU 访问获取本 CPU 时钟事件设备；[ARM64 per-CPU 实现](https://github.com/torvalds/linux/blob/v6.18/arch/arm64/include/asm/percpu.h) 的合法路径读取 TPIDR_EL1/EL2。登记内核基线与本地源文件 `kernel/time/tick-oneshot.c` 的 SHA256 相同，没有发现此公共文件被本仓库修改。

## 六款机型的范围检查

只读检查现有 E5、T551M、M8、T512N、远航 41S、K1 六套 Image 和各自 System.map：都包含正常的 MOV/MRS 指令组合。机器可读结果：`work/t512n-crash-20261026/instruction-analysis.json`。

这证明当前本地交付件没有在这个位置预置报告中的两条异常指令，不等于证明驱动运行时没有缺陷。

- 若写坏来自共用的驱动 DMA、地址转换或基带固件交互，其他共享该路径的机型可能受影响。
- 若来自群友这台机器的硬件稳定性、特定启动镜像或特定运行时状态，不能扩散为所有机型问题。
- 现有日志无法区分以上来源。新包也没有针对这个尚未定位的写坏源加入修复，不能承诺换包即可消失。

## 其他日志如何理解

- uptime 约 36,329 秒，约 10.1 小时后触发；panic 在中断上下文，因此不可恢复并自动重启。
- `pstore ... error (-28)` 出现在 Oops 后，是记录空间不足，不是最初的崩溃原因。
- `SMP: failed to stop secondary CPUs` 发生在 panic 收尾，不能反过来当成最初故障。
- 崩溃前保留片段没有 OOM、soft lockup 或 eMMC 读写错误证据。重启后的内存统计不能代表崩溃瞬间的内存状况。
- SIPA 的资源释放/挂起、Wi-Fi 信标重写等确实出现，但调用时间接近不足以证明它们写坏了代码。
- 重启后打印了电压偏移 0；这不能倒推崩溃前的临时电压或硬件状态，也不足以把这次事件归因于降压。

## 下一步有判别力的只读材料

1. 按实际 Linux 槽位读回 boot，解出并比较内核段与该版本成品；不能硬编码 Linux 总在 A/B，也不能把设备绑定后的整份 boot 哈希不同直接当作内核损坏。
2. 在相同内核的正常运行中读取该函数的实际代码字节，与启动后的基准比较，以区分加载即异常与运行后被改写；优先按需采样，不先增加常驻轮询或改变业务时序。
3. 若确认运行后变化，再按故障页对应的物理地址追踪可访问该区域的 DMA/共享内存/固件路径，必要时使用有针对性的写入追踪。不能凭当前栈直接回退 USB、充电、SIPA 或显示改动。

目前不应修改 tick_program_event 加空指针兜底，也不应全机型关闭 CPU idle；这些都无法修复已经变质的机器指令。
