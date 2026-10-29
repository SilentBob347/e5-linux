# DDR DVFS参考资料核查（2026-10-29）

用户提供 `D:\随身WiFi\device_soc_sprd-OpenHarmony-4.0-Release`，要求只读。
本次只读取该目录；没有在其中生成文件、索引或构建产物，没有访问或写入硬件。
它是调查参考，不是登记的生产构建输入；本次不移植驱动、不改内核配置或固件。

## 已确认的内容

目录主要由 common、uis7885/hardware 和 uis7885/bootloader 组成；README仍为通用模板。
不能仅由目录名称断定它就是任一现有机型的原厂完整源码。

LK 的 `platform/common/ddr_debug/` 明确包含 qogirn6l、qogirn6pro、qogirl6等实现，
`rules.mk` 按 PLATFORM 选择编译。对我们同平台家族的DDR适配具有参考价值，
但尚未与每台机的实际SML/SP、DT、内存颗粒及原厂Linux驱动逐项核验。

- `dmc_freq_sel_search()` 给出频率到0—7索引的映射。
- `get_freq_vol()` 给出启动调试路径采用的电压阈值；两个平台并不完全一致。
- `sw_dvfs_go()` 读取当前索引、暂时关闭light-sleep、申请PUB DVFS锁、等待ACK、
  发起切换、等待完成、释放锁并重新打开light-sleep。这是启动阶段的直接MMIO操作，
  带无超时忙等；不是可直接移入Linux运行时的完整控制器。
- `ddr_boot_freq_voltage_set()` 使用 `regulator_set_voltage("vddpub", vol)`。
- `ddr_paras_set_to_sp()` 向IRAM写DFS、DVS、retention及屏蔽频点参数，
  说明启动阶段会向后续固件交接控制参数。尚不能仅据此证明OpenWrt中的实时DFS状态。
- 两平台IRAM地址不同：该参考的n6l使用0x65018cxx/0x65018dxx，n6pro使用
  0x65014cxx/0x65014dxx。不得在其他机型上猜测或照抄地址。

## 仅供交叉核验的启动调试映射

| 索引 | 源码标注MHz | qogirn6l阈值mV | qogirn6pro阈值mV |
| --- | ---: | ---: | ---: |
| 0 | 384 | 600 | 650 |
| 1 | 533 | 650 | 650 |
| 2 | 768 | 700 | 700 |
| 3 | 1066 | 700 | 700 |
| 4 | 1244 | 700 | 750 |
| 5 | 1536 | 750 | 750 |
| 6 | 1866 | 750 | 750 |
| 7 | 2133 | 750 | 750 |

这是所读参考文件的映射，不是本机实测频率表或已验证的运行时OPP；MHz也不应
直接写成DDR的MT/s。不得据此对现有机器直接调压、锁频或关掉休眠。

`sprd_ddr_debug.c` 中，工程参数从miscdata读入，只有magic=0x5aa5才应用；
0x5a表示禁用DFS/retention等调试开关，并将屏蔽表交给SP。这是研究现有启动
状态的一条线索，不是当前授权修改miscdata的依据。本轮没有读写设备miscdata。

## 运行时驱动与GPU部分

本次文件名及硬件目录内容检索没有找到 `sprd_ddr_dvfs_core.c`、`sprd-governor`
或完整Linux DDR运行时驱动；LK中的kernel子目录是LK本身的内核，不是Linux。

作为独立的实际原机证据，已保存的远航41S Android `sprd_ddr_dvfs.ko` 包含
`depends=sipc-core`、smsg_ch_open/send/recv、devfreq及场景请求接口。
后续应以本机模块、DT和实际固件确认SIPC协议、频点查询、自动DFS状态及场景
生命周期；参考LK代码用于验证寄存器和固件交接语义，不取代原机证据。

GPU的 `hardware/gpu/BUILD.gn` 是allocator/mapper/GLES_mali预编译库的装配定义，
并非Panfrost负载调频实现；不能据此把OpenHarmony二进制直接替换进OpenWrt。

## 未完成项

尚未确认OpenWrt实时DDR频率、是否由SP自主变化、各机型可用频点和电压、
场景加票/退票以及休眠恢复协议；未编译、部署或实测DDR DVFS移植。

## 只读参考文件校验

| 相对于参考目录的文件 | 原始字节SHA-256 |
| --- | --- |
| `uis7885/bootloader/bootloader/lk/platform/common/ddr_debug/ddr_dvfs_qogirn6l.c` | `c1ec11f7476402cd0452c2158572888bd79f45b0a09883a991491645d504ebb6` |
| `uis7885/bootloader/bootloader/lk/platform/common/ddr_debug/ddr_dvfs_qogirn6pro.c` | `212c0a885e6c2fc91a6a37ec3bafe74c3695bfcd89ec81ad6d6098ea3f9b152c` |
| `uis7885/bootloader/bootloader/lk/platform/common/ddr_debug/sprd_ddr_debug.c` | `818ffb3b3d74d47c21129838863967bad7ea1285c6199be275a3436ff927c51e` |
| `uis7885/bootloader/bootloader/lk/platform/common/ddr_debug/rules.mk` | `e2167561f6f2b7aed8a59004ea5b1b8ce55c84924f5786401efff1c7f1ba01e6` |
| `uis7885/bootloader/bootloader/lk/platform/common/include/sprd_ddr_dvfs.h` | `65867cad0cd4fb88d8a9c6c45e50082f7d2b6f660364ff07a06706f5fcb7df83` |
| `uis7885/hardware/gpu/BUILD.gn` | `5c2243abe98b4a2fe0b56db0f13ddec263e4074adbfbfa34c3d1a10ae2ff8d77` |
