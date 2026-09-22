# Jev + IndexTTS 2.5：乙骨忧太台词心智与多阶段情感控制系统

本项目位于 `d:\42427\Jev\jev-yuta-indextts\`，实现了由 **TypeSafe Jev (System One)** 认知引擎驱动本地 **IndexTTS 2.5** 进行高精分段情绪控制与声学渲染的完整流水线。

---

## 一、 人设背景与心智认知剖析 (Ground Truth)

### 1. 角色档案
* **角色**：乙骨忧太（Yuta Okkotsu）
* **定位**：现代仅次于五条悟的特级咒术师 / 纯爱战神
* **核心心智特征**：
  * **克制与负罪感**：表面温和谦逊，但对自己极度苛刻，绝不逃避因个人决断引发的牺牲；
  * **冷酷与杀伐担当**：一旦进入战斗或意识到必须承担罪责，神态瞬间冷冽，甘愿为了结咒术宿命而化身“怪物”；
  * **纯爱与极端守护**：对同伴（真希、狗卷、熊猫、虎杖等）有极深执念，不愿让同伴弄脏双手。

### 2. 第249话新宿决战场境与独白心理 (日文原作对照)
* **台词文本 (日文原作版)**：
  > 「全部言い訳だ。本隊に残れない理由を並べ、頑なに真希さんに羂索を任せなかったのも、独り善がりの私欲を満たし、仲間を無意味に死なせてしまった。僕が、僕の手で羂索を終わらせたかった……その私心が、今の状況を招いたんだ。僕の過ちは、僕自身で清算する。領域展開――真贋相愛。」
* **心理演进轨迹**：
  1. **阶段 1：自責と抑鬱の残酷な内省**（`0.0s ~ 14.52s`）
     * 心理：撕碎“合理后撤”的掩饰，痛斥自己不想让真希弄脏手的一己私欲。
     * 声学表现：声音低沉、压抑、自语颤抖，气音较重。
     * 情绪向量：以 `melancholic` (0.86) 与 `disgusted` (0.76) 为主导，辅以 `sad` (0.75)。
  2. **阶段 2：冷徹な引受と清算の覚悟**（`14.97s ~ 27.21s`）
     * 心理：瞬间切断迷惘，“我的过错由我自身来清算”。冷酷、纯粹的担当与杀意。
     * 声学表现：语调变硬、节奏紧绷收缩、字句清晰果断。
     * 情绪向量：以 `angry` (0.75) 与 `calm` (0.58) 结合。
  3. **阶段 3：呪力全開と領域詠唱**（`27.76s ~ 30.46s`）
     * 心理：拔剑结印，特级咒力全开。「領域展開――真贋相愛」。
     * 声学表现：中气磅礴、庄严肃穆、威压拉满。
     * 情绪向量：`angry` (0.92) + `calm` (0.63)。

---

## 二、 音频处理与工程防御规范

### 1. 长音频截取必要性
* **原音频**：`D:\Downloads\9月22日.mp3` 全长 **144.43 秒**。
* **截取原因**：IndexTTS 2.5 的零样本音色编码器最佳输入窗口为 **4~10 秒**。直接灌入超过 1 分钟的长音频不仅会剧烈增加显存占用，更会导致长音频前后起伏、语速波动与底噪互相稀释污染。
* **工程截取结果**：
  * `prompts/ref_clip_mid_30s.wav` (10.0s，中段能量最充沛且无爆音区间) $\to$ 已锁定为默认基准 `prompts/yuta_ref.wav`。

### 2. 多阶段切片与气口缝合
* 若将整段长对白作为单一文本直接合成，IndexTTS 全局平均化会导致“自责”与“领域爆发”互相抹平。
* Jev 裁决出 3 阶段独立参数后，按阶段分别推理，并在段落之间精准插入 **400ms** 与 **550ms** 戏剧级呼吸停顿，无缝拼合成最终音频。

---

## 三、 生成交付资产

* **【重点推荐】A/B 情感控制独立对比实验套件**：
  [`d:\42427\Jev\jev-yuta-indextts\ab_comparison_experiment\`](../../assets/zh/)
  * 内含：前两个部分（自责抑郁 vs 冷酷担当）的【无情感控制 A】与【Jev 情感控制 B】完整对照音频组。
  * 说明文档：[`ab_comparison_experiment/README.md`](../../assets/zh/AB_COMPARISON_EXPERIMENT.md)
  * 一键复现：[`ab_comparison_experiment/run_experiment.bat`](../../applications/emotion-controlled-tts/run_experiment.bat)
* **中文纯单次生成版（100% 绝对不分段・单一连续音频・无任何拼接痕迹）**：
  [`d:\42427\Jev\jev-yuta-indextts\outputs\yuta_pure_oneshot_zh.wav`](../../assets/audio/continuous_zh.wav)
  * 时长：`21.68 秒` | 采样率：`22050 Hz`
  * 特性：底层 `segments count: 1`，全程单次自回归连续吐字，零冷启动拼接；多音字注入 `<羂|JVAN4>`、`<了|LIAO3>`、`<真|ZHEN1><赝|YAN4>`，助词更正为标准的轻声“的”。
* **日文连续一体版（日文推荐・一气呵成）**：
  [`d:\42427\Jev\jev-yuta-indextts\outputs\yuta_continuous_ja.wav`](../../assets/audio/continuous_ja.wav)
  * 时长：`25.76 秒` | 采样率：`22050 Hz`
* **历史版本（对照存档）**：
  * 中文长句版：[`outputs/yuta_continuous_zh.wav`](../../assets/audio/continuous_zh.wav) (19.73s)
  * 中文初版：[`outputs/yuta_domain_expansion.wav`](../../assets/audio/domain_expansion_zh.wav) (25.11s)
  * 日文初版：[`outputs/yuta_domain_expansion_ja.wav`](../../assets/audio/domain_expansion_ja.wav) (30.46s)
* **一键运行脚本**：
  * `run_pipeline.bat`（默认运行日文版生成）
  * 命令行指定参数：
    ```powershell
    D:\42427\TTS\index-tts\.venv\Scripts\python.exe run_pipeline.py --lang JA
    ```
