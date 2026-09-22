# 火柴人格斗 · 战斗系统总结

> 本文按模块与章节完整记录 `stick-figure-jev` 的设计、实现、测量与已知短板。
> 所有数值均来自当前代码与本仓库实测输出，不来自推测；每个"为什么这样设"都给出
> 它被量出来的那一次。用户文档请看 [`README.md`](../../README.md)，本文是工程侧底账。

目录

1. [目标与验收约束](#1-目标与验收约束)
2. [分层架构与依赖方向](#2-分层架构与依赖方向)
3. [引擎层：世界、几何与帧数据](#3-引擎层世界几何与帧数据)
4. [引擎层：防御、打击、连招、投技、弹道](#4-引擎层防御打击连招投技弹道)
5. [JEV 决策层：状态、问题、策略、脑](#5-jev-决策层状态问题策略脑)
6. [表现层与输入](#6-表现层与输入)
7. [测量：台账指标与实测结果](#7-测量台账指标与实测结果)
8. [博弈三角闭环的根因链](#8-博弈三角闭环的根因链)
9. [测试清单](#9-测试清单)
10. [已知短板与延后项](#10-已知短板与延后项)
11. [运行手册](#11-运行手册)
12. [结论修正日志](#12-结论修正日志)

---

## 1. 目标与验收约束

原始需求逐条对照当前落点：

| 需求 | 落点 | 状态 |
| --- | --- | --- |
| 玩家操控火柴人 vs JEV 火柴人，类实时反应 | `public/` + `JevBrain` 流水线（非阻塞、逐帧执行计划） | 已实现；浏览器画面仅做到结构级验证，见 §11 |
| 实现方式遵循 `typesafe-ai` 最佳实践 | 规则/执行归代码，语义判断归模型；一次请求组合 6 个独立判断；阈值改动不重跑推理 | 已实现，见 §5 |
| 可搭配技能 + 碰撞机制，探寻连招上限 | `MOVES[].cancelOn/cancelInto` 技能图 + AABB 判定 + `DAMAGE_SCALE`/`MAX_JUGGLE` 上限 | 已实现，实测上限 5 段 |
| 密钥只在本地环境变量 | `TYPESAFE_API_KEY` 只被 `server/server.js` 与 `src/jev/client.js`（Node 侧）读取；浏览器只调 `/api/jev` | 已实现 |
| 制作阶段用双 JEV 模型操控两个火柴人 | `scripts/spar.mjs` 无头双脑对战 + 池化台账；`--model1/--model2` 支持 A/B 两个模型标签 | 已实现 |

核心重定向（用户原话）：**"最重要的火柴人对战就不行，不是表现层问题，技能连招和精彩对战，jev 的博弈选择呢"** —— 因此本轮全部工作集中在博弈选择与连招可达成性，不做主观视觉打磨。

---

## 2. 分层架构与依赖方向

```
src/engine/constants.js   纯可调参数（无 I/O、无全局，Node 与浏览器同一份）
src/engine/moves.js       招式表：帧数据 + 技能图（cancelOn/cancelInto）
src/engine/engine.js      定步 60Hz 模拟：几何、命中、防御、硬直、击倒、弹道、资源
src/jev/state.js          world -> 单个视角的有序无关观测袋
src/jev/questions.js      问题包：2 choice + 3 noul + 1 score
src/jev/policy.js         answers -> plan（compilePlan）；plan + 实时 world -> 逐帧输入（executePlan）
src/jev/brain.js          非阻塞流水线：getInput / stepWorld / observe + 重规划触发器
src/jev/client.js         Node 侧 JEV HTTP 客户端（持密钥）
src/jev/mock.js           离线孪生 decider（免费、确定性，用于 CI 与调参）
server/server.js          静态托管 + /api/jev 决策代理 + /api/config
public/client.js view.js  画布游戏循环、输入映射、HUD、姿态绘制
scripts/spar.mjs          无头双 JEV 池化对战 + 战斗台账
scripts/probe.mjs         在线端点连通性探测
test/engine.test.mjs      32 例引擎规则
test/jev.test.mjs         20 例决策层规则
```

依赖方向是单向的：`jev/*` 依赖 `engine/*`，`engine/*` 不反向依赖任何决策代码。
`policy.js` 通过 `import { attackBox, hurtbox, overlap } from "../engine/engine.js"`
复用引擎自己的几何函数，而不是另写一套距离公式——这是刻意的：**判定几何只有一个真值来
源**，否则反射会对着一个谎言出招。

`src/engine/index.js`、`src/jev/index.js` 只是再导出桶文件。

---

## 3. 引擎层：世界、几何与帧数据

### 3.1 定步循环与确定性

`stepWorld(world, inputs)` 每 tick 顺序执行：计时器（含 hitstop 冻结）→ 输入→意图 →
动作推进 → 物理 → 身体互相推挤 → 命中/弹道结算 → 事件推送。固定步长、纯函数、无全局，
因此同一输入序列必然复现同一战局；mock 池化 64 场两次跑出逐字节相同输出即为该性质的验证。

`world.events` 是**唯一**的战局叙事来源：`attack_start / hit / block / whiff / throw /
launched / counter_hit / projectile / shot_evaded / burst / jump / dash / ko`。台账只从事件
流派生指标，绝不从帧数据反推，这样"改一条策略"能被证伪而不是被解释掉。

### 3.2 arena 与身体几何

| 参数 | 值 | 含义 |
| --- | --- | --- |
| `ARENA.width` | 900 | 场地宽 |
| `ARENA.wallPad` | 40 | 贴墙边界 |
| `FIGHTER.halfWidth` | 22 | 站立受击框半宽 |
| `FIGHTER.bodyHeight` | 120 | 站姿受击框高 |
| `FIGHTER.crouchHeight` | 66 | 蹲姿受击框高 |
| `FIGHTER.startHP` | 1300 | ≈25 下实打，保证有立回阶段 |
| `walkSpeed / backSpeed` | 3.4 / 2.6 | 前进快于后退 |
| `dashSpeed / dashFrames / dashCooldown` | 9.5 / 12 / 24 | |
| `jumpVelocity / gravity / airSpeed` | 15.2 / 0.82 / 4.6 | 约 37 帧滞空、≈170px 弧线 |
| `wakeInvuln` | 18 | 起身无敌帧（投技与连段的天然终点） |

`attackBox()` 以 `f.x + facing * hitbox.x` 为中心、`hitbox.w/h` 为宽高；`hurtbox()` 上界由
`heightOf()` 在站/蹲之间切换。**招式实际能打到人的水平距离** = `hitbox.x + w/2 + 22`，
本文称为"触及"，全表如下（由当前帧数据算出，不是手抄）：

| 招式 | 触及(px) | 备注 |
| --- | --- | --- |
| launcher | 87 | 上段升龙，短 |
| jab | 92 | 安全点戳 |
| airkick | 93 | 空中超打（overhead） |
| **throw** | **98** | 本轮从 74 改来，见 §8 |
| strong | 111 | 主力中远距离点戳 |
| sweep | 115 | 下段 |
| super | 127 | 全气终结 |

### 3.3 招式表（帧数据，60fps）

| 招式 | 类型/高度 | 启动 | 活跃 | 收招 | 伤害 | 受击硬直 | 格挡霸体 | 击退 | 取消于 → 可接 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| jab | strike / high | 4 | 3 | 7 | 42 | 16 | 9 | 3.2 | hit,block → strong, launcher, sweep, fireball, **throw**, super |
| strong | strike / high | 8 | 4 | 14 | 86 | 22 | 12 | 6.0 | hit,block → launcher, fireball, **sweep**, **throw**, super |
| launcher | strike / high | 7 | 5 | 26 | 78 | 26 | 14 | 2.5 / 抬升 16 | hit → jump |
| sweep | strike / **low** | 9 | 4 | 22 | 70 | 24 | 12 | 4.0（倒地） | — |
| fireball | projectile / high | 12 | — | 22 | 55 | 20 | 12 | 5.0 | —（弹速 7.5，寿命 160） |
| airkick | air strike / **overhead** | 5 | 6 | 10 | 64 | 22 | 10 | 4.0 / 4.0 | —（juggleAdd 2） |
| throw | **grab** / unblockable | 3 | 4 | 16 | 120 | 20 | 0 | 6.0（倒地） | —（`lunge: 5`） |
| super | strike / high | 6 | 8 | 20 | 260 | 28 | 18 | 5.0 | hit → —（耗 100 气） |

技能图是**连招的唯一权威**：`cancelInto` 没列的链接，引擎直接拒绝出招，代码从不强制
非法取消。表头注释里写明了三种守卫各自唯一的错答案。

---

## 4. 引擎层：防御、打击、连招、投技、弹道

### 4.1 防御规则 `isBlockingAgainst`

```
必须 grounded；不在 hitstun / attack / knockdown / ko；
guarding = blockstun > 0 || hold.block;           // 霸体保持防御姿态
面向攻击者;
low      → 只有蹲姿防住;
overhead → 只有非蹲姿防住;
其余     → 站防与蹲防按上述高度规则处理
```

本轮定稿的关键一条：**blockstun 保持举盾，但不改变这面盾覆盖的高度**。以前 blockstun
期间一律自动防御且不分高度，导致下段在实盘中数值恒为 0。修完之后，蹲/站的选择就成了
一个必须在被打到之前就下好的**赌注**，高低混合选择才成立。

配套：`CHIP.strikeRatio = 0.10`、`CHIP.projectileRatio = 0.05`，且格挡扣血下限 1 HP——
龟缩安全但不免费，纯防守永不被磨死。

### 4.2 有效霸体帧（本轮分析出的派生性质）

格挡时 `atk.hitstop = def.hitstop = stop`（打点 12、弹道 10），而计时器循环在 hitstop
期间 `continue`，**blockstun 与动作帧数一起冻结**。于是"解冻之后对手还剩几帧不能动"为：

| 被格挡的招式 | blockstun | 冻结 | 解冻后有效霸体帧 |
| --- | --- | --- | --- |
| jab | 9 | 12 | **0**（还倒扣 3） |
| strong | 12 | 12 | **0** |
| sweep | 12 | 12 | **0** |
| airkick | 10 | 12 | **0** |
| fireball | 12 | 10 | 2 |
| launcher | 14 | 12 | 2 |
| super | 18 | 12 | 6 |

这条表是投技修复的前提：**点戳被防住后，"锁帧"整段都花在冻结里，解冻瞬间对手就自由
了**，而且后撤位移也是在解冻后才一次性兑现。任何指望"霸体期间对手不能动"的机制都必须
自己跨过这段位移。

### 4.3 打击结算

- 反击（`def.action.phase === "startup"` 且未被防住）：伤害 ×1.25、硬直 +4 帧，并推送
  `counter_hit` 事件（带 `victimMove`，让台账能说"什么被什么截了"）。
- 连段伤害按 `DAMAGE_SCALE`（15 档，1.0 → 0.15）逐击递减，`MAX_JUGGLE = 8` 封顶空中延
  伸，超限即硬倒地终止连段。**上限是可达但有限的**，实测 5 段。
- 中段命中不推走受击者（只有首击、launch、knockdown 才推），这是"技能图能连上"的前提。
- 击退与相向推挤：`BLOCK_PUSH = { defender 0.5, attacker 0.45 }`——被防住时**双方**都被
  推开，格挡确实买回距离；这也造成 §8 里投技落空的直接原因。

### 4.4 取消窗口 `advanceAction`

`a.cancelOpen = a.hitConsumed && cancelOn.length > 0`，且这一行**提到 hitstop 提前 return
之上**。以前放在其后，等于整个冻结期窗口都是关的——而冻结期正是玩家/AI 狂按的那几帧。
这一处修完，`blocked jab → sweep` 才第一次在实盘中出现过。

### 4.5 投技与 `lunge`

`throw` 现在带 `hitbox {x:46,y:60,w:60,h:80}`（触及 98）与 `lunge: 5`。引擎在动作
`startup` 期间每帧 `f.vx = facing * lunge`，进入 `active` 第一帧归零：起手 3 帧前进 15px。
理由见 §8 第 4 条。投技仍 `unblockable`、只抓 grounded 对手、120 血、直接倒地、不计连段、
不涨气（`meterGain: false`）。

### 4.6 弹道与立回

弹体在启动结束生成，速度 7.5、寿命 160、可互相 clash；被防住按 0.05 削血。若一发弹道
全程没碰到任何人，引擎推送 `shot_evaded`——与"挥空"同构的事实：**一次没被回应的空间控制
就是一次失误**，台账据此统计"224 发火球、120 发什么都没打到"。

### 4.7 资源与反制

`METER = { max 100, gainOnHit 24, gainOnHitTaken 12, gainOnBlock 6, burstCost 50,
superCost 100, burstInvuln 15, burstPush 30 }`。挨打也涨气是翻盘叙事的定量表达：被吃满
一条 4 段路线必须刚好买得起一次 burst，否则"被连一次=一直被连"。burst 只能地面、
hitstun 中、且有气才成立；它清掉排队中的倒地、把双方推开 30px，并中断对手 2 段以上连段计数。

---

## 5. JEV 决策层：状态、问题、策略、脑

### 5.1 `state.js` — 给模型看什么

两条硬规则：

1. **不给像素坐标、不给自身身份**。给的是fighter 相对的意义化观测：`spacing` 分
   `clamp(≤60) / close(≤130) / mid(≤230) / far(≤430) / unsafe`，`hp_pct`、`meter_pct`、
   `clock.ticks_remaining_pct`，以及 `self/foe` 各自的 `state / action{move,phase,cancelOpen}
   / hitstun / blockstun / invuln / juggling / guarding`。System One 在意义上泛化，不在数字上泛化。
2. **观测袋与顺序无关**，任何子集缺失都不影响其余部分——这是"部分回答/超时回答安全"的前提。

`reach` 字典用引擎同款几何算出每招此刻能否打到；`reads` 是派生事实而非帧数据：
`foe_recovering / foe_committing / foe_hitstunned / foe_juggled / self_mid_combo /
self_cancel_open / foe_action_startup / foe_whiffed(punish_frames ≥ 6) / foe_guarding /
foe_guard_stance / self_can_burst / self_can_super`，外加 `incoming_shot_frames`、
`punish_frames`。

### 5.2 `questions.js` — 一次请求，6 个独立判断

| 判断 | 原语 | 用途 |
| --- | --- | --- |
| `intent` | choice（11 选项） | 唯一下一步策略；选项措辞保证代码可确定性映射 |
| `guard_stance` | choice（stand/crouch） | **赌**下一段防守高度；刻意不允许"看见招式再选" |
| `threat_now` | noul | 触发硬防御反射；弹道在飞也算 |
| `punish_window` | noul（投机式："IF 对手挥空/被…") | 决定点戳是否升级为全段路线 |
| `counter_hit` | noul（投机式） | 立回：我能否先手打断（明确写了"互换不算赢"） |
| `aggression` | score(0..2) | 选安全版还是全套路线 |

独立性是关键：一次调用里并行问完，答案彼此不可见；persona 只改写 `intent` 的措辞，
不改原语结构，因此双脑的原始判断可直接比较。

### 5.3 `policy.js` — compilePlan（存判断）+ executePlan（逐帧执行）

`compilePlan` 只做降级与覆盖，全部阈值集中在 `DEFAULT_THRESHOLDS`：

```
threatBlock 0.62 · punishGo 0.45 · minIntentConf 0.3 · maxAggression 1.3
midAggression 0.4 · throwConf 0.35 · superConf 0.4
```

- 低置信 `heavy → poke`、`anti_air/space_control → block`；**`combo` 不降级**（多挥一记
  jab 很便宜，漏掉一次确反才是失误）。
- `throw`/`super` 有各自更高的置信门（16 帧空挥的投技是白送，空大的 super 是整条气）。
- 强威胁读值把 `reset/space_control` 直接改写成 `block`。

`executePlan` 每帧运行，是一条有编号的反射流水线（顺序即优先级）：

| 段 | 内容 | 为什么必须是代码 |
| --- | --- | --- |
| 1 | 已成立的连段推进器：`comboRoute` = 全套 `[jab,strong,launcher,jump]` / 中档 `[jab,strong]` / 保守 `[jab]`；只在真窗口里出下一环；满气收尾 `superEnder` | 取消窗口按帧存在 |
| 1b | burst 反制 | 50 气换一次逃脱，晚 3 帧就没意义 |
| 1c | 我方 blockstun 期间保持举盾与既定高度 | 这几帧不是自由帧 |
| 2 | 硬反射防御（仅在我方自由且无活着的连段时） | — |
| 2a | 挥空确反：`PUNISH_ORDER = [launcher, strong, jab]`，窗口 < 该招总帧数才降级到更轻的那把 | 反制窗口只有 `punish_frames` 帧 |
| 2b | 跳入落点期出 `airkick`（下降段、且对手这几帧还不了手：stun/recovery/龟缩） | 5 帧启动 + 每帧约 9px 下落，顶点起脚必然打空 |
| 2c | 被防住那一击打开的窗口里出"错答案"：蹲防→`throw`，站防→`sweep`，够不着→`jump` | 窗口宽约几帧，任何 ~0.4s 计划都来不及 timed |
| 3 | 策略执行：`combo/poke/heavy/throw/super/burst/block/evade/anti_air/space_control/reset` | — |

`guardCrack(me, foe, allowGrab)` 是三种守卫的统一入口；`grabLocked(foe) =
foeTurtling(foe) && foe.blockstun > 0` 把投技限制成"只打进锁帧"。`case "throw"` 因此不再
是"走过去抓"，而是"用最便宜的招式造出锁帧，再让窗口分支去收"。

弹道应对：`SHOT_LEAD = 12`、`SHOT_RISE = 8` 决定"来得及就跳过去，来不及就举盾"。

### 5.4 `brain.js` — 类实时反应的全部秘密

```
每帧: getInput(world)   // 用当前 plan 对实时 world 出招，绝无 I/O
      stepWorld(...)
      observe(world)    // 满足条件才发一次异步 JEV 调用（在途锁）
```

重规划门：`inFlight` 时不发；`fires >= maxDecisions` 不发；距上次 `minFramesBetween = 12`
帧内不发；`plan == null` 或 `planAge >= ttlFrames = 24` 发；触发事件发——被打到、被 launch、
对手出招、对手发弹、KO、**距离单帧变化 > 36px**。答回来才换 plan，并记录延迟样本、
`rawLog`（状态快照 + 答案 + 编译结果）。这就是"慢模型仍然手感跟得上"的机制：**模型给持续
意图，代码按帧执行**。

### 5.5 `mock.js` 与密钥边界

`makeMockDecider({persona})` 是与真 JEV 同形状、同类型（choice/noul/score + confidence）的
离线孪生，让 CI、调参、复现完全免费且确定。威胁读值刻意只把"来袭弹道"当威胁（`≤12` 帧
时 0.55~0.85，其余 0.12），注释里写明了不把近身对峙算作威胁的原因：那会收敛成双方举盾的
死锁。密钥只出现在 `server/server.js`（`HAS_KEY = Boolean(process.env.TYPESAFE_API_KEY)`）与
Node 客户端；`/api/jev` 服务端构造问题包，浏览器拿不到提示词也拿不到密钥；`/api/config`
只回答 `has_key`。

---

## 6. 表现层与输入

`public/client.js`：键位映射 `KeyA/D` 移动、`KeyW` 跳、`KeyS` 蹲、`Space` 盾、
`KeyJ` jab、`KeyK` strong、`KeyU` launcher、`KeyI` sweep、`KeyO` fireball、`KeyH` airkick、
`KeyT` throw、`KeyG` super、`KeyB` burst；`R` 重开、`M` 切换 人机 / 双 JEV 观战。
启动时 `GET /api/config`，`has_key:false` 就自动挂 mock decider，游戏永远可玩。

`public/view.js`：姿态由 `f.action.moveDef` + `phase` + `state` 通用派生（不存在按招式名
分支的开关），所以新增招式不需要改绘制；`knockdown/ko` 有专门躺地姿态。血条、气条、
命中粒子、事件闪光都从 `world.events` 驱动，与台账同源。

---

## 7. 测量：台账指标与实测结果

`spar.mjs` 的 `ledger(events)` 只吃事件流，池化打印（`--games 64`）。指标定义上的两个
讲究：**出手数与命中数分开统计**（"下段 0 次"是"从没按过"还是"按了都被防"完全不同结论）；
**反击按 `受害者招式 > into -拦截招式` 记**（只记赢家会藏掉"我伸手被反"和"跳入被预备好"两种失误）。

当前实测（`node scripts/spar.mjs --mock --games 64 --seconds 45`，确定性，两次跑出逐字节相同）：

```
  attack started   : 3064   landed 1624   guarded 440   whiffed 464
  defence share    : 21.3%  (target >=22%)
  counter-hit share: 9.4%   (target 8-12%)  strong>into-strong:80  super>into-jab:64  strong>into-fireball:8
  whiff punish     : 312/464 (67.2%), of 0 empty grabs
  throw / burst    : 32 grabs landed, 160 meter escapes
  stance breaks    : 168 lows through a guard, 176 overheads, 144 launches
  space control    : 224 fireballs, 120 never touched anybody; 280 jumps
  super            : 80 full-meter finishes
  combo ceiling    : 5 hits in one string
  moves attempted  : strong 1256  jab 584  super 336  sweep 296  fireball 224  airkick 176  launcher 160  throw 32
  outcomes         : rushdown 16 / counter 16 / zoner 16 / balanced 16
  average round    : 1393 ticks（45 秒时钟里约 23 秒）
```

逐项读法：三条破防边**都非零**（下段 168 / 超打 176 / 投技 32），但量级并不相当——投技仍是
最细的一条边，原因见 §10；投技 `throw 32 attempted → 32 landed → 0 empty grabs`，即"按了就中"，
瓶颈在出手次数而不是命中质量；反击 9.4% 落在目标带内；四个 persona 战绩完全对称，说明没有某个
风格独大；单场平均 23 秒，既不是秒杀也不是互相挠痒。

历史上这些数字曾经的样子：下段 **0**、超打 **0**、投技 **0 命中 / 16 场 0 次成功**、
8 场里有 4 场被记成"平局"（其实是 mock 的决策预算把战局提前掐断）。

---

## 8. 博弈三角闭环的根因链

"三角缺一边"不是一个 bug，是八个叠起来的 bug。每条都给出量到它的那次观测。

| # | 症状 | 量到的原因 | 修法 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 下段实盘恒 0 | blockstun 期间无条件自动防御且不查高度，任何下段都被"顺手"防住 | `isBlockingAgainst` 改为按高度判定，霸体保持举盾不改覆盖 | 修前 0 次；修后 64 场池化 168 次下段命中（§7 台账） |
| 2 | 站/蹲赌注不存在 | 我方 blockstun 一结束立刻放盾，赌注从没被兑现 | 1c 段：锁帧期间保持盾与既定高度 | 引擎测"霸体保持盾但不改覆盖高度" + 决策测"blockstun 中保持既定盾与高度" |
| 3 | `jab→sweep` 从未出现 | `cancelOpen` 在 hitstop 提前 return **之后**才算，冻结期整段窗口关闭 | 把该行提到 return 之前（并在末尾重算） | 引擎测"被防那一击的窗口穿过冻结期仍可取消"；sweep 出手 296 |
| 4 | 中距离没有混合选择 | `strong.cancelInto` 里没有下段，也没有投技 | 加入 `sweep`、`throw` | 探针：26 帧"窗口开+对手蹲防+已按投技"被引擎 26 次拒绝；改后窗口从 26 帧塌缩成 2 个真窗口 |
| 5 | 投技 100% 落空（几何） | `throw` 是全表最短攻击（74px），而能取消进它的每一招都更长（jab 92 / strong 111 / sweep 115），且格挡本身送出约 30px 后撤 | 触及改 98（仍短于 strong） | 出招后打点距离仍从 80→120，引出 #6 |
| 6 | 改完仍 6 次全在 120px 落空 | 有效霸体帧为 0（§4.2）：冻结把霸体耗尽，被推迟的后撤恰好在投技出框时兑现 | 新增 `lunge: 5`（起手 3 帧前进 15px） | 探针转为 `throw-start@d80 → GRAB-LANDED@d83` |
| 7 | 16 次"我方自由时按投"全部抓空气 | 每个脑都有"看见投技就跳"的反射，出手瞬间对手 grounded，判定帧已在 20px 空中 | `grabLocked`：投技只允许打进 blockstun 锁帧；`case "throw"` 改为先造锁帧 | `0 empty grabs`，投技 32/32 |
| 8 | 8 场被记成平局 | mock 也吃 `budget 120`，预算把战局在约 1400 tick 掐断，指标全被污染 | mock 且未显式 `--budget` 时置为 `Infinity` | 修后平均回合长度与胜负正常 |

结论：三角的每一边现在都有非零、可复现、被测试钉住的成功路径；投技这条边是最后闭环的，
它需要的是**帧数据（触及/前压）+ 技能图（strong 可接投）+ 策略门（只打锁帧）**三处同时成立。

---

## 9. 测试清单

`npm test` = 52 例（`node --test` 在本机 Node 上报错误结果，必须走 npm）。

**引擎 32 例**：世界初始化与 HP；实打伤害+冻结；防高段只吃削血；下段穿站防/被蹲防；
`jab→strong→launcher` 三段取消并 launch；launcher 取消跳 + 空中延伸（4+ 上限）；伤害衰减
封顶；KO 终止；被防削血比例（打点/弹道）；纯防守不会被削死；反击加成伤害/硬直/事件；
非 startup 不给反击加成；投技破盾（满伤害+倒地+不计连段）；投技能抓起手式但抓不到跳；
投技不能当连段填充/不能打倒地；burst 花 50 清硬直并双方推开；burst 的三种拒绝；
burst 可再次使用；super 花满气且没气不能出；super 伤害与格挡削血；气只由实打积累；
吃满一条路线刚好买得起下一次 burst；挥空被记为确反窗口；空挥投技自报是投技空挥；
跳入超打破蹲防/被站防；被防住把攻击者也推出射程；跳跃带走跳时方向；**霸体保持盾但不改
覆盖高度**；**被防那一击的窗口穿过冻结期仍可取消**；**该窗口距离足以抓住投技**；无人回应
的弹道被公告。

**决策层 20 例**：低置信保 combo、降 heavy；强威胁升级 block；引擎看到实锤才硬防御；
不在即将激活的判定框面前伸手；**起手期的投技是跳过去而不是举盾**；防御读高度（头顶的
airkick 不是威胁）；来袭弹道按剩余空间选择举盾或跳过；空挥招来的窗口出最重的可行确反；
状态把确反窗口以"帧"而非形容词呈现；**每种守卫拿到它唯一防不住的答案**（站→下段、
蹲→跳入、锁帧站→下段、锁帧蹲→近距离投技）；**取消窗口把 crack 记录在案**；**blockstun 中
保持既定盾与高度**；**下降段跳入出超打而非原地落地**；防御高度是计划下的赌注而非查表；
`serializeState` 的 fighter 相对视角；状态暴露新读值与触及；策略只在划算时出招（含
"不给自由对手按投技、给锁帧对手按投技"）；满气终结不在首命中就收线；JEV 脑能压着被动
对手打（流水线通）；双脑同时决策并记录延迟。

---

## 10. 已知短板与延后项

- **防御率 21.3% 卡在 ≥22% 目标下沿**，故意不去调：唯一杠杆是提高 mock 的举盾概率，而那
  正好喂养被这套台账测量的龟缩行为，等于用削弱被测对象换取绿灯。
- **tick throw 转化率 32/32 是构造使然**（只打进锁帧，锁帧无法回应）。规则本身正确，但
  这意味着反制存在于"要不要在投技射程内继续举盾"这个决策里，而 persona 启发式尚未建模
  它。真人带真实反应时间是它的外部检验。
- **最大反击漏洞 `super > into jab`（64 次）**：super 只有 6 帧启动且能取消自任何命中，会
  截到不是冲它去的点戳。收紧它是帧数据议题，不是策略议题。
- 投技这条边量级仍最小（64 场 32 次 vs 下段 168）。上限来自"在 98px 内被防住的中距离点
  戳"次数，属于 plan 的 aggression 侧，不是规则缺失。
- 尚未实现：回合制/三战两胜、空中防御、角落收益、挥空取消诱饵、给 JEV 读的帧优势信号、
  第二套角色招式、burst(50) 与 super(100) 的气资源争夺、联机。
- 表现层缺口（用户已明确排除在本轮之外）：无动画过渡、无镜头、无音效、无命中定格表现。

---

## 11. 运行手册

```bash
cd stick-figure-jev
export TYPESAFE_API_KEY=...            # 只被 Node 侧读取
npm test                               # 52 例，离线、免费
node scripts/probe.mjs                 # 在线端点连通性（花少量预算）
node scripts/spar.mjs --mock --games 64 --seconds 45   # 台账，确定性
node scripts/spar.mjs --mock --fast --p1 rushdown --p2 counter
node scripts/spar.mjs --live --p1 counter --p2 rushdown --model1 jev-latest --model2 jev-1.13.0 --json spar-ab.json
node server/server.js                  # http://127.0.0.1:8787（PORT 可覆盖）
```

- `--fast` 只影响**实时观战**的节奏（`spar.mjs` 里 `if (useLive && !opts.fast)` 才插入延迟），
  对结果、台账与确定性都没有影响；`--mock` 下加不加都一样。

- `spar` 默认 `budget 120`/脑；mock 且未显式传 `--budget` 时自动置 `Infinity`（见 §8 第 8 条）。
- 服务器无密钥时 `has_key:false`，浏览器自动挂 mock 脑，**用它做零预算验证**。
- 浏览器验证现状：已确认页面加载、两个 fighter 初始化（x=288 / x=612）、`mode:pve`、
  `live:false`、画布 900×340、无控制台错误；**未能截图确认画面**——本环境 in-app 浏览器
  没有可见视口，标签页隐藏时 rAF 暂停，画布尚未产生任何绘制像素。因此"火柴人可见"这一条
  在本轮**没有被目视验证**，需你在打开的窗口里确认。
- `.gitignore` 已覆盖 `node_modules/`、`.env`、`*.log`、`spar-*.json`。整个目录目前仍是
  **未纳入 git 的 untracked 状态**，没有版本安全网。

---

## 12. 结论修正日志

工程记录里必须留下被推翻的说法，否则下一个接手的人会照着错的原因去改代码：

1. 曾把"防御反射的距离 bug"说成**镜像的距离判定写反了**。错。自动面向对手之后该说法不成
   立，真实缺陷是**缺少高度检查**。代码注释已改，此条以 §8#1 为准。
2. 曾报告"投技已经 16 次命中"。错——那是一行 grep 输出被我读反（实际是 `0 grabs landed`）。
   以 §7 的 `throw 32 attempted / 32 landed / 0 empty grabs` 为准。
3. 曾凭推理描述探针输出，并声称要做两项改动（去掉 2c 的 `cancelOpen` 要求、把防御者的
   hitstop 归零以延长霸体）。**两项都没有实施**，代码里 2c 仍然要求 `me.action.cancelOpen`。
   实际落盘的只有 §8 表中的 #1–#8 那几处。
4. 曾断言"后撤是投技落空的原因"并用一次字节级相同的台账证伪它。那次证伪无效：当时所有投技
   请求都被**上游的技能图缺失**拒绝，改触及当然看不出差别。教训已写进 `moves.js` 注释——
   在链路被上游掐断时调下游参数，不构成证据。
5. 文档曾写"5 个判断（1 choice + 3 noul + 1 score）"。实为 **6 个（2 choice + 3 noul +
   1 score）**，`guard_stance` 是后加的；README 与本文均已更正。
