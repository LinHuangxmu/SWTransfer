# SolidWorks `GetRemainingDOFs` 验证记录

本文档记录对 `IComponent2.GetRemainingDOFs` 的受控装配实验。目的不是记录 exporter 的分类规则，而是先确认 SolidWorks API 本身返回什么信息。

## API 调用

```csharp
int remainingDOFs = component.GetRemainingDOFs(
    out int R1Status, out MathPoint RPoint1,
    out int R1DirStatus, out MathVector RDir1,
    out int R2Status, out MathPoint RPoint2,
    out int R2DirStatus, out MathVector RDir2,
    out int L1Status, out MathVector LDir1,
    out int L2Status, out MathVector LDir2);
```

typed COM wrapper 返回长度为 13 的元组：

```text
[返回值,
 R1Status, RPoint1, R1DirStatus, RDir1,
 R2Status, RPoint2, R2DirStatus, RDir2,
 L1Status, LDir1,
 L2Status, LDir2]
```

探针脚本：`tools/solidworks_dof_probe.py`

## 已完成实验

所有实验均为两个组件：`Base-1` 和 `Probe-1`。`Base-1` 固定，读取 `Probe-1`；每次改变装配后执行 `Ctrl+B` 重建。

### 01-Fixed

Probe 也执行 `Fix Component`，没有组件间 Mate。

```text
IsFixed      = True
ReturnValue  = 2
R1/R2/L1/L2 Status = 0
```

结果：`dof_0-Fixed.json`

### 02-Revolute

销/孔圆柱面 `Concentric`，端面 `Coincident`，Probe 只能绕共同轴旋转。

```text
IsFixed      = False
ReturnValue  = 0
R1Status     = 1
R1DirStatus  = 1
RPoint1      = 有效点
RDir1        = 旋转轴方向
R2/L1/L2     = 0
```

结果：`dof_02-Revolute.json`

### 03-Cylindrical

只保留销/孔 `Concentric`，不保留端面 Coincident。Probe 可以绕轴旋转并沿轴平移。

重建后：

```text
ReturnValue  = 0
R1Status     = 1
R1DirStatus  = 1
RPoint1      = 旋转轴上的点
RDir1        = 共同轴方向
L1Status     = 1
LDir1        = 与 RDir1 相同
R2/L2        = 0
```

第一次未重建时曾得到 `ReturnValue=2` 且所有状态为 0。

结果：`dof_03-Cylindrical-rebuild.json`

### 04-Prismatic

使用两组互相垂直的平面 `Coincident`，Probe 只能沿一个方向平移。

```text
ReturnValue  = 0
R1/R2        = 0
L1Status     = 1
LDir1        = 实际滑动方向
L2Status     = 0
```

结果：`dof_04-Prismatic.json`

### 05-LimitPrismatic

在纯平移装配中加入 `LimitDistance`，Probe 在限位范围内仍可双向移动。

Limit Mate 启用时：

```text
ReturnValue  = 0
R1/R2/L1/L2 Status = 0
```

将 `LimitDistance1` 设置为 `Suppress -> This Configuration` 并重建后：

```text
ReturnValue  = 0
L1Status     = 1
LDir1        = 实际滑动方向
R1/R2/L2     = 0
```

结果：`dof_05-LimitPrismatic.json`、`dof_05-LimitPrismatic-suppressed.json`

### 06-Free

删除/抑制所有组件间 Mate，Probe 完全自由，可以任意平移和旋转。

```text
IsFixed      = False
ReturnValue  = 2
R1/R2/L1/L2 Status = 0
```

结果：`dof_06-Free.json`

### 07-Planer

只有一组平面 `Coincident`。Probe 理论上可以在平面内两个方向平移，并绕平面法向旋转。

```text
ReturnValue  = 2
R1/R2/L1/L2 Status = 0
```

结果：`dof_07-Planar.json`。文件实际名称是 `07-Planer.SLDASM`。

### 08-Spherical

Base 和 Probe 的球面使用 `Concentric`，Probe 可以绕球心多方向旋转，不能整体平移。

```text
ReturnValue  = 0
R1Status     = 1
R1DirStatus  = 0
RPoint1      = 球心
RDir1        = 不可视为有效唯一轴
R2Status     = 0
L1/L2        = 0
```

改变 Probe 姿态并重建后，`RPoint1` 保持不变，`R1DirStatus` 仍为 0。

结果：`dof_08-Spherical.json`、`dof_08-Spherical-rotated.json`

### 09-子装配体与 Flexible 上下文

测试装配体：

```text
Top.SLDASM
├── Top_Base-1
└── Inner-1-1    ← Inner-1.SLDASM 实例
    ├── Inner_Base-1
    └── Inner_Probe-1
```

在顶层 `Top.SLDASM` 中直接调用：

```text
Top_Base-1
    fixed       = False
    ReturnValue = 0
    L1Status    = 1
    LDir1       = [1, 0, 0]

Inner-1-1
    fixed       = True
    ReturnValue = 2
    R1/R2/L1/L2 Status = 0
```

对 `Inner-1-1` 调用时，查询的是整个 `Inner-1.SLDASM` 实例相对于
`Top.SLDASM` 的运动，不是内部零件的运动。即使内部 `Inner_Probe-1`
能够运动，若子装配体实例本身被固定，`Inner-1-1` 仍可返回全零轴状态。

随后进入 `Inner-1.SLDASM`，对内部组件调用：

```text
Inner_Base-1
    fixed       = True
    ReturnValue = 2
    R1/R2/L1/L2 Status = 0

Inner_Probe-1
    fixed       = False
    ReturnValue = 0
    L1Status    = 1
    LDir1       = [1, 0, 0]
```

这说明：

```text
查询子装配体实例       → 子装配体整体运动
查询子装配体内部组件   → 内部组件在该装配上下文中的运动
```

`GetRemainingDOFs` 可以作用于子装配体实例，因为子装配体实例也是
`IComponent2`。但它不会自动把子装配体内部的关节合并到子装配体实例的
结果中。要分析内部关节，必须递归进入对应的 `.SLDASM` 文档，并保留
组件所属的文档/上下文信息。

### 10-FlexibleLimit：柔性子装配体中的 Limit Mate

在 `Inner.SLDASM` 中给可动的 `Inner_Probe-1` 添加 `LimitDistance`，
并从顶层/内部分别读取结果。

Limit Mate 启用时：

```text
Top_Base-1
    fixed       = False
    R1/R2/L1/L2 Status = 0

Inner_Probe-1
    fixed       = False
    ReturnValue = 2
    R1/R2/L1/L2 Status = 0
```

此时组件在限位区间内仍可能实际移动，但求解器不再报告原来的基础平移
轴。将 Limit Mate 设置为：

```text
Suppress → This Configuration
```

然后执行 `Ctrl+B`，结果恢复为：

```text
Top_Base-1
    L1Status    = 1
    LDir1       = [1, 0, 0]

Inner_Probe-1
    ReturnValue = 0
    L1Status    = 1
    LDir1       = [1, 0, 0]
```

该实验再次确认：Limit Mate 会隐藏或改变基础 R/L 轴输出；抑制后可以
读取基础运动轴，限位范围则需要从 Mate 另行读取。不要删除 Limit Mate，
应使用当前配置抑制，并在读取后恢复。

本次测试还明确了层级限制：截图中的 `Inner-1-1` 仍为固定实例，因此
已经验证了“子装配体/内部组件的查询层级”和“Limit 对内部组件输出的影响”，
但尚未证明顶层外部 Mate 能否在 `Solve as Flexible` 状态下改变内部组件的
完整 DOF。要验证这一点，应将子装配体实例设为 `Solve as Flexible`，重建后
在顶层上下文中查询嵌套的 `Inner_Probe-1`。

## 当前可以确认的作用

`GetRemainingDOFs` 是 SolidWorks 装配求解器的组件运动查询接口。它返回组件在当前装配约束、固定状态和求解状态下，仍可表达的刚体运动信息。

```text
R1/R2       旋转运动候选槽位
RPoint      旋转中心/轴上一点
RDir        旋转轴方向

L1/L2       平移运动候选槽位
LDir        平移方向
```

典型实测：

```text
单轴旋转       R1Status=1, R1DirStatus=1
单轴平移       L1Status=1
圆柱运动       R1Status=1 + L1Status=1
```

## 重要边界

### 首个返回值不是自由度数量

```text
固定组件       ReturnValue=2
完全自由组件   ReturnValue=2
单轴旋转       ReturnValue=0
单轴平移       ReturnValue=0
圆柱运动       ReturnValue=0
```

因此不能写成 `remainingDOFs == 1` 代表一个自由度，或 `== 2` 代表两个自由度。它应被视为 SolidWorks 的结果/状态码，完整官方枚举语义仍未从公开文档中确认。

### `Status=1` 不能单独代表标准旋转副

球面测试中 `R1Status=1` 但 `R1DirStatus=0`。这表示存在旋转运动，但没有一个唯一有效的旋转轴。只有旋转方向状态也有效时，才适合解释成标准单轴 `revolute`。

### 不是通用 6D null-space API

完全自由件和单平面约束件都没有返回完整的多个平移/旋转基。它对单轴旋转、单轴平移和圆柱运动最有用；对于球面、平面或完全自由等多自由度状态，输出不是完整的 6D 自由度基。

### Limit Mate 会影响结果

`LimitDistance` 启用时，Probe 实际仍能在范围内移动，但标准 `L1/L2` 槽位不再报告有效平移。抑制 Limit Mate 后，`L1Status=1` 恢复。

因此实际使用时应：

```text
暂时抑制 LimitDistance/LimitAngle
调用 GetRemainingDOFs
读取基础运动轴
恢复 Limit Mate
另行读取限位范围
```

### 子装配体层级与 Flexible

对顶层子装配体实例调用 `GetRemainingDOFs`，得到的是该实例作为一个
整体相对于父装配体的剩余运动；对内部零件调用，得到的才是该零件在其
所属装配上下文中的剩余运动。刚性或固定的子装配体不会把内部零件的
DOF 自动暴露到根实例结果中。

对于 `Solve as Flexible` 的子装配体，内部组件可以在父装配体上下文中参与
求解。工程实现应递归枚举嵌套 `IComponent2`，并记录每个结果对应的：

```text
父装配体文档
子装配体文档
组件实例路径
Rigid/Flexible 状态
原始 R/L 状态与方向有效标志
```

不能只读取 `.SLDASM` 根组件并假定它代表内部所有关节。

### 必须重建

03-Cylindrical 第一次未重建时返回了过时状态，重建后恢复为 `R1Status=1` 和 `L1Status=1`。读 API 前应执行 `Ctrl+B` 或等效的 `Rebuild`。

## 当前工程判断规则

如果只需要判断是否存在明确单轴关节，目前最可靠的条件是：

```text
旋转：RStatus=1 且 RDirStatus=1 且 Point/Direction 有效
平移：LStatus=1 且 Direction 有效
```

以下情况应视为“存在运动但无法直接表示成单轴关节”：

```text
RStatus=1 但 RDirStatus=0
多个运动状态互相不一致
ReturnValue=2 且所有轴状态为 0
Limit Mate 未抑制
装配未重建或求解状态不可靠
```

## 后续可选实验

### 11-UniversalJoint：两轴万向节

这是研究多轴旋转槽位的进阶测试，不是基本功能验证的必需项。

```text
Base 固定
Base ↔ Frame：第一组圆柱轴 Concentric + 端面 Coincident
Frame ↔ Probe：第二组互相垂直的圆柱轴 Concentric + 端面 Coincident
```

Frame 相对 Base 绕第一根轴旋转，Probe 相对 Frame 绕第二根轴旋转。因此 Probe 理论上有两个旋转自由度，没有平移自由度。

### 12-StaleState：未重建测试

在 `04-Prismatic` 中改变 Probe 位置后，不执行 `Ctrl+B`，立即查询一次，再执行 `Ctrl+B` 查询一次，对比两次结果。

### 13-Overconstrained：过约束测试

在单轴平移模型中增加一个会重复限制同一方向的 Mate，记录 Solver 是否返回状态码变化，以及 SolidWorks 是否显示过约束。

## 结论

`GetRemainingDOFs` 能让 SolidWorks 求解器报告组件当前剩余的、可被识别的旋转/平移运动，并提供相应的轴点和方向；但它不是简单的自由度计数器，也不是通用的完整 6D 自由度基提取器。

对于 exporter，最可靠的用法是：先确定父子关系，重建装配，必要时临时抑制 Limit Mate，然后读取所有 R/L 槽位，只接受状态和几何都有效的单轴结果。

## 已接入 exporter 的大装配体策略

当前程序采用两级 Solver 查询：

```text
第一级：每个组件直接读取一次 GetRemainingDOFs
    ↓
按返回轴向、旋转轴点和 Mate 几何，将单轴运动关联到候选边
    ↓
第二级：只对无法明确关联的边执行临时 Fix/Unfix + 重建查询
```

这样可以避免在大装配体中对每一条 Mate 边都重复修改装配、重建和恢复。
组件级快照也会写入 `graph.json`，并在子装配体展开时变换到实例/世界坐标。

对于双导轨、双轴承等多个边共享同一组件运动的情况，近似同轴的候选边
会保留给 native motion grouping；后续树构建只保留一个实际关节，其余边
作为刚性支撑或闭环边处理。没有唯一轴的球面、平面、完全自由结果不会
被快速路径强行转换成单轴关节。

在 `LiquidHandler_v1` 的实际龙门测试中，组件级 `L1Status=1` 快照正确
落到了滑台的 `Carriage_0 ↔ Linear_Rail` 边，而不是落到丝杆、轴承或电机
支撑边。当前应解释为：

```text
X：一个独立平移 DOF
Y：两个平行支撑模块，保留一个主关节，另一个 1:1 mimic
Z1：一个独立平移 DOF
Z2：一个独立平移 DOF
```

因此 URDF 中会看到 5 个 prismatic joint 记录，但其中一个 Y 关节是
mimic follower，独立控制量是 4 个：`X、Y、Z1、Z2`。Z1/Z2 不再因为
“同轴平行”规则被错误合并。
