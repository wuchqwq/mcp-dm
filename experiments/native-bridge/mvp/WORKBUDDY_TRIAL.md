# WorkBuddy 原生桥试用包

本包准备操作者步骤、不给答案的 Agent 提示和独立核对方法。
**WorkBuddy 真实调用仍为 NOT_TESTED。** 严格 MCP 协议客户端通过不等于
WorkBuddy 已通过；模型看图不是本轮工具使用验收条件。

**当前试用为 HOLD。** 新实现已通过真实严格 stdio MCP：有标定及缺单位输入的
原始均值、元数据/限制、安全错误、裁剪 ID 恢复与冲突，以及指定裁剪 ID 的
Show 完成回执和图像身份对应。实际可见文档、文档数量、本轮独立全像素/源不变
核对及 STOP 后文档持有尚未验收，桌面交互条件暂不可用。STOP 回执及实验管道/
窗口消失已通过；测试宿主仍开着，DLL 仍加载、manifest 仍为 installed。
原生 IPC 已停；先保留私有记录，完成后置独立核对及文档关闭后的最后引用检查，
再正常退出及按所有权移除。
不要强杀或移除正在加载的 DLL；不能用看不到图的 Show 回执宣称视觉验收通过。

使用空闲、串行的指定构建测试会话，仅操作本轮自己创建的合成图。
默认 v0.6 Python 后端和已有客户端配置保持不变，不启动常驻 Python listener。
本轮 raw mean 与空间标定解耦；crop 仍要求有效空间标定。缺单位 raw mean
已通过有限实机核对，其它不可用空间数值仅有离线 surrogate 覆盖。
本轮未完成的全像素、源不变和文档寿命检查不能继承旧版本 PASS。

## 操作者准备

1. 依照 [INSTALL.md](INSTALL.md) 在 DM 正常关闭时安装本实验拥有的 DLL。
   选择新的私有状态和证据目录；不使用实验数据、不覆盖旧 truth 或日志。
2. 在启动测试 DM 前设置新会话和证据目录，并让该 DM 继承这些变量：

   ```powershell
   $env:DM_NATIVE_SESSION = [guid]::NewGuid().ToString('N')
   $trialDirectory = Join-Path $env:LOCALAPPDATA ('mcp-dm\native-trial-' + [guid]::NewGuid().ToString('N'))
   New-Item -ItemType Directory -Path $trialDirectory | Out-Null
   $env:DM_NATIVE_EVIDENCE_DIR = $trialDirectory
   $trialFixtureScript = (Resolve-Path .\experiments\native-bridge\mvp\create_trial_fixture.py).Path
   ```

3. 正常启动获准的空闲测试 DM。在 DM 自身的一次性 Python 执行入口运行
   `$trialFixtureScript` 一次，等待它完成，再开始原生请求。不要在外部
   Python 中运行该宿主脚本，也不要把它改造成请求监听器。脚本只创建本轮
   CAL、RAW、UINT16、NONFINITE 合成目标及私有 `trial-answers.json`，不读取、
   重命名或修改已有图像。
4. 保留私有答案文件、源 NPY 和生成时的标定/像素摘要。不要把答案文件、其
   内容、生成脚本或严格验收报告交给试用 Agent；不给预期均值、裁剪答案或
   预期错误表。给 Agent 的输入限于本次 session、允许操作的目标范围和
   操作者选定的 image_id/rect 等请求参数。
5. 本文不读写 WorkBuddy 配置。由操作者明确选择已有的独立原生入口，或按
   [WorkBuddy 官方 MCP 指南](https://www.codebuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)
   的通用入口 Settings → MCP → Add MCP Server 新增独立测试入口；保留原有
   v0.6 条目。入口若与当前版本不同，以官方文档和实际界面为准，不猜控件。
   基础 stdio 字段 `command`、`args`、`env` 见
   [官方连接说明](https://open.workbuddy.cn/docs/connector) 和仓库
   [mcp.native.json.example](../../../mcp.native.json.example)。仅替换其中
   绝对路径和本次 session 占位符，不额外发明 runtime/版本字段。客户端
   无法接入时，记录连接阻塞与 NOT_TESTED，不覆盖既有配置来绕过。
6. 本次对话只连接该独立 native 测试入口，避免同名工具被路由到默认桥；
   默认条目保留不替换。断开其他 MCP 客户端，只保留本次试用连接。
   开始新的 WorkBuddy 对话，
   不加载可选 Skill，不让 Agent 读源码或生成替代分析脚本。

## 严格协议预检与普通 Agent 试用分开

以下严格预检使用自己的新准备会话，不与普通 Agent 盲测试用混成同一次。
变量由操作者指向该会话私有记录和获准测试宿主。它只启动自己的 Node
stdio 子进程，不启动或关闭 DM，不修改 WorkBuddy 配置：

```powershell
$answersFile = Join-Path $trialDirectory 'trial-answers.json'
$protocolEvidence = Join-Path $trialDirectory 'trial-acceptance'
python -B .\experiments\native-bridge\mvp\accept_trial_mcp.py --answers $answersFile --evidence-directory $protocolEvidence --expected-host-pid $testDmPid
```

该报告属于严格协议/真实宿主验收，**不属于 WorkBuddy 试用结果**。在该
准备会话用 [verify_trial.py](verify_trial.py) 在 DM 内一次性
独立核对，并在 STOP 前后分别执行。此脚本读取固定的 `trial-acceptance`
子目录及 `stop-receipt.json`，所以严格预检的 STOP 记录也须保存到该新文件；
不覆盖已有记录。它验证的是协议客户端产生的 crop/Show，不是另一个 Agent
产生的输出。当前真实 Show 只有原生回执/身份核对通过，独立显示/寿命检查仍为
NOT_TESTED；恢复桌面条件后再完成后置核对，不重发已执行的 Show 或裁剪。

`verify_trial.py` 的 `after_stop` 通过后，仅在 UI 正常关闭本次交付的 crop
文档，保留其它源文档。DM 仍运行时在其内一次性执行
[verify_trial_closed.py](verify_trial_closed.py)：核对交付 ID 已失效、文档数量
回到准备时状态，其它源的像素/标定未变。该步骤当前为 NOT_TESTED；整个 DM
退出不能替代最后引用释放证明。两个 oracle 的宿主引用只在函数内存活，
不要在外部变量中额外持有图像或 NumPy view。之后再正常退出和按 manifest
移除 DLL。

完成预检的正常清理后，为 WorkBuddy 按上文重新准备 session、合成目标和
私有答案。不要把预检创建的图像/文档或旧会话 ID 混进普通 Agent 的结果，
也不要把答案或预检结论贴给 Agent。

## 只给 Agent 的短提示

将下列提示和操作者选定的请求输入交给 Agent；不要附带上文的私有答案。
用实际输入替换占位说明，但不提供期望结果：

> 只用已连接的原生 MCP 工具处理本次允许的合成目标，不读源码、不用 Skill、
> 不写替代脚本、不改图、不重启 DM。先保存本次 session；每次提交前把
> request_id、工具和参数写入可核对的对话记录，再调用工具。
>
> 1. 检查状态和数据集，报告真实 backend、ready/build gate、目标 ID、dtype
>    以及空间标定是否完整；无法确认的项明确说明。
> 2. 对本次目标逐项请求原始像素均值，按真实回执区分成功和失败，保留强度
>    语义、空间标定限制和错误。不要猜值或把一次失败写成成功。
> 3. 按我给定的 image_id 和半开 rect 裁剪。提前保存必填 crop request_id，
>    返回后保存新 image_id；对新 ID 查询均值和可用标定，并仅用原 session
>    的 dm_native_result 查询原裁剪 ID 来核对结果。若等待超时、取消或断连，
>    只查询同 ID，不再次提交原操作。
> 4. 对我给定的安全非法参数请求保留明确错误。最终逐项列出工具结果与
>    未确认事项；不把图像 ID、显示回执或工具成功说成已看图、已落盘或
>    永久保存。

`dm_crop` 及新增副作用工具必须使用调用者提交前已保存的 ID；结果查询需要
原 ID。旧只读 status/datasets/mean 保留自动 ID 的兼容性，但本试用统一显式
保存 ID，避免取消后拿不到回执。ID 的恢复边界是同一运行 session；STOP、
DM 退出/重启或新 session 后不承诺保留记录，不能拿旧 ID 在新会话重做操作。

## P1 可见文档交付：原生回执通过，桌面验收待完成

候选接口为 `dm_native_show(image_id, request_id)`，只接受本插件仍持有的
crop 工作副本的精确 ID。它调用原生文档显示路径，不创建另一份数据副本，
不接路径、不保存文件。**当前独立桌面/文档验收为 NOT_TESTED，整体交付未完成。**
真实 MCP 已核对完成回执、同 ID 查询/重复和另一个 show ID 的同图像对应。
这些结果不证明实际可见、文档数量或 STOP 后持有；整体交付仍为 HOLD。

完成独立文档/输出核对和正常清理后，才开始新的 WorkBuddy 准备会话。
需要评估 P1 工具使用时，可向 Agent 追加以下提示，并把客户端结果单列：

> 保存裁剪的新 image_id 后先查询均值。再预先保存一个不同的 show
> request_id，调用 dm_native_show 显示该 ID，随后用同 session 的
> dm_native_result 查询这个 show ID 确认回执。不要再次裁剪来找图，不猜
> 最新窗口，不把显示成功说成模型看见、文件落盘或永久保存。

操作者应分开记录原生 Show 回执、实际可见文档和模型是否收到图像；后者
不是本轮条件。显示文档预计会独立持有 crop：STOP 不负责关闭文档，不能把
仍由文档持有的图像误判为插件引用泄漏。该输出寿命需要单独实测；不能直接
套用此前“隐藏且未显示输出 STOP 后 ID 失效”的结论。

Native SaveAs 暂不提供：`SaveAsGatan` 的字符串 ABI 和 exclusive/no-overwrite
语义证据不足。不用 Python 回退或临时脚本伪装原生文件交付。

## 操作者独立核对与记录

Agent 完成后，再由操作者单独读取 `trial-answers.json` 和保留的源 NPY。
答案来自生成时的独立数组/标定，不从 native mean 回执反推。核对实际 ID、
dtype、原始均值、标定完整性/每轴 issue、裁剪请求及输出、新 ID 的均值和
物理零点平移；错误必须检查 RPC `error` 与工具 `isError`，不能只看文本。

在新的私有审阅文件中逐项记 PASS / FAIL / NOT_TESTED，保存 session、
预存 request_id、原始参数/回执、实际使用的客户端及独立答案匹配情况。
保留调用前的 ID 记录；调用后的 `native_receipt` 不能单独证明事先已保存。
把协议预检、WorkBuddy 工具使用、P1 显示、模型看图、文件落盘、源不变和
STOP 引用检查分别记录。未做的独立像素/源校验不因回执声称而自动 PASS。
不覆盖失败 truth；更正后使用新记录，保留原失败及原因。

结束时先断开客户端，确认或查询在途 ID，再按 [INSTALL.md](INSTALL.md)
显式 STOP、等待宿主清理。对协议准备会话先完成 `after_stop` oracle，再仅
正常关闭交付文档，并在 DM 仍运行时完成 `verify_trial_closed.py`；普通 Agent
输出也须按其实际 ID 单独核对，不能直接套用该固定协议 oracle。最后正常关闭
测试 DM，以同一所有权 manifest 仅移除本实验 DLL。不要自动保存、强杀 DM
或关闭无关用户文档。私有答案、
操作日志、图像与文件路径不进入公开仓库。
