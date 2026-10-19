# B1：理解异步等待

> 2026-10-19 更新：本节保留为可选背景阅读，不再作为项目推进的前置条件。
> 当前采用[本地优先的交付计划](../v0.1-execution-plan.md)，无需逐题完成教学练习。

预计学习时间：30–45 分钟。先运行、预测输出，再逐行理解。
本节用 Python 标准库模拟等待后端；不发网络请求，也不做 GPU 推理。

## 运行

所有命令都在 **Ubuntu/WSL** 终端执行：

```bash
cd /home/jerry/code/ServeLab
uv run --locked python labs/01_async_wait.py
```

`uv run --locked` 使用项目环境，要求锁文件与项目配置一致；
`python labs/01_async_wait.py` 执行本节代码。

先预测：A 和 B 各等 1 秒，依次等待需要多久？同时调度又需要多久？

典型输出如下。时间只是模拟等待的观测，系统负载会影响实际数值。

```text
Sequential: await A, then await B
0.00s  A: start waiting
1.00s  A: response received
1.00s  B: start waiting
2.00s  B: response received
Total: 2.00s

Concurrent: schedule A and B, then wait for both
0.00s  A: start waiting
0.00s  B: start waiting
1.00s  A: response received
1.00s  B: response received
Total: 1.00s
```

验收重点是：第一段 B 在 A 完成后开始；第二段 A、B 都开始等待后才收到响应。
同一时刻就绪的任务完成顺序不作为接口承诺，也不要求耗时精确等于 1 或 2 秒。

2026-10-19 已在项目的 WSL / CPython 3.12.14 环境实际运行：顺序版本为 2.09 秒，
并发版本为 1.08 秒，进程正常退出。它们是本次教学示例的观测值，不是 ServeLab 性能结果。

## 只掌握五个概念

1. `async def` 定义协程函数。调用 `request(...)` 创建协程对象，不会自动开启线程或开始执行函数体。
2. `await` 等待一个可等待对象完成。遇到尚未完成的异步操作时，当前任务可以挂起，让事件循环运行其他已就绪任务；并非每次 `await` 都必然切换任务。
3. `asyncio.sleep(1)` 模拟异步等待。它等待计时器而不阻塞事件循环。
4. `asyncio.gather(...)` 将传入的协程调度为任务，并等待它们完成。本例里 A、B 的等待时间因此能够重叠。
5. `asyncio.run(main())` 管理事件循环并运行入口协程。这里的 Python 协程在同一个事件循环线程上轮流推进。

在顺序版本中，`await request("A", ...)` 结束前，程序根本没有执行到创建 B 的那行。
即使 A 等待期间事件循环可以运行其他任务，此时也没有已调度的 B。

在并发版本中，A、B 都已调度。A 等待时 B 可以开始；B 也等待后，事件循环等待计时器就绪再恢复任务。
`perf_counter()` 用于测量间隔，日志时间以本段实验开始时刻为零点。

## 与 ServeLab 的关系

网关经常需要等待推理后端通过网络返回数据。等待 A 的响应期间，网关可以接收 B、转发其他流式数据或处理取消。
这些等待能否重叠，取决于调用路径是否使用异步 I/O。GPU 上怎样执行请求，由推理引擎决定。
本例不能证明推理吞吐提升，也不能据此推导 GPU 能并行处理多少请求。

常见失败是把阻塞调用放在事件循环线程里。若把 `await asyncio.sleep(1)` 换成 `time.sleep(1)`，
这个线程会被阻塞，其他协程也无法及时推进。真实服务里同样要留意同步网络调用和长时间 CPU 计算。
本节先理解正常路径；后续练习会分别验证任务异常、timeout、cancel 和 `finally` 清理。

## 本节完成标准

- 亲自在 WSL 运行一次，观察两段日志。
- 能解释为什么两个连续 `await` 不会自动让 A、B 并发。
- 能解释并发版本是否使用了两个 Python 线程。
- 能预测阻塞调用会对事件循环造成什么影响。

如果希望理解异步，可以自行运行并思考这些问题；它们不阻塞工程推进。
此示例准备完成不等于整个 Phase B 已完成。

参考：[Python 3.12：协程与任务](https://docs.python.org/3.12/library/asyncio-task.html)。
