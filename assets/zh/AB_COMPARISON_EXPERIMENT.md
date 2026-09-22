# IndexTTS 2.5 情感控制 A/B 对照实验报告
### —— 基于 TypeSafe Jev (System One) 乙骨忧太心智裁决验证

---

## 一、 实验背景与核心目标

本实验旨在**客观评估与物理验证**：
在本地 IndexTTS 2.5 语音合成引擎中，通过 **TypeSafe Jev (System One)** 认知模型对《咒术回战》乙骨忧太第249话对白进行深层心智剖析，所裁决出的 8 维情感控制向量（`emo_vector`），相较于**完全无外部情感控制的原生基准（Baseline）**，能够产生何种程度的真实听觉差异。

---

## 二、 A/B 对照组实验设计

* **说话人参考音色基准**：`prompts/yuta_ref.wav`（从长音频中截取的 10 秒纯净乙骨忧太少年音原声，整体语势平稳微弱）。
* **对照维度设计**：
  * **版本 A【无情感控制 (Baseline)】**：
    * 参数：`emo_vector = None`, `emo_alpha = 1.0`, `use_emo_text = False`。
    * 机制：底层完全依赖参考音频原本提取的声学全局特征，不施加任何外部情绪向量。
  * **版本 B【Jev 情感控制 (Jev-Driven)】**：
    * 参数：显式注入 Jev 裁决的 8 维连续向量 `[喜, 怒, 哀, 惧, 厌恶, 抑郁, 惊讶, 平静]`，`emo_alpha = 1.2`，并施加匹配该心智阶段的动态语速因子（`duration_factor`）。
    * 机制：通过底层情绪基底矩阵加权投影，强制重塑声带张力与音高包络。

---

## 三、 实验用例与详细参数对照

### 1. 第 1 部分（残酷自省与自厌抑郁）
* **台词文本**：  
  `全都是借口……说什么不能留在主战场帮忙，固执己见的不让真希学姐去杀<羂|JVAN4>索，自以为是的满足一己私欲，放任伙伴无意义死去……`
* **心理基准**：痛陈私心，深重内疚，内心撕扯自厌。
* **参数对比**：
  * **版本 A (无控制)**：`emo_vector = None` | 语速 `1.0x`
  * **版本 B (Jev控制)**：`emo_vector = [0.0, 0.30, 0.70, 0.10, 0.75, 0.85, 0.0, 0.15]`（主导：抑郁 0.85、自厌 0.75、哀伤 0.70）| 语速 `0.95x`
* **试听文件**：
  * 版本 A：[`audio/part1_self_reproach_A_no_emotion.wav`](../../assets/audio/part1_self_reproach_A_no_emotion.wav) (11.18s)
  * 版本 B：[`audio/part1_self_reproach_B_with_jev_emotion.wav`](../../assets/audio/part1_self_reproach_B_with_jev_emotion.wav) (13.57s)
* **听觉差异点**：
  * 版本 A 语调偏向普通的叙述性朗读，语势平缓；
  * 版本 B 注入 Jev 向量后，整体发音显著**下沉发虚、气音加重**，带有明显的**自我唾弃与自省叹息感**。

---

### 2. 第 2 部分（冷酷担当与清算觉醒）
* **台词文本**：  
  `是我想亲手<了|LIAO3>结<羂|JVAN4>索的私心，造成了现在的状况。我的错，就由我来终结！`
* **心理基准**：从自责泥潭拔地而起，罪责全归于己，杀意凝聚，不容置疑的断言。
* **参数对比**：
  * **版本 A (无控制)**：`emo_vector = None` | 语速 `1.0x`
  * **版本 B (Jev控制)**：`emo_vector = [0.0, 0.85, 0.10, 0.0, 0.20, 0.20, 0.0, 0.65]`（主导：冰冷杀意/怒 0.85、决断冷静/平 0.65）| 语速 `1.05x`
* **试听文件**：
  * 版本 A：[`audio/part2_cold_resolve_A_no_emotion.wav`](../../assets/audio/part2_cold_resolve_A_no_emotion.wav) (7.83s)
  * 版本 B：[`audio/part2_cold_resolve_B_with_jev_emotion.wav`](../../assets/audio/part2_cold_resolve_B_with_jev_emotion.wav) (8.54s)
* **听觉差异点**：
  * 版本 A 末尾的“就由我来终结”语气平淡，缺乏生死决战的压迫感；
  * 版本 B 注入 Jev 杀意向量后，**声带骤然收紧发硬，吐字沉稳如刀刻，末尾感叹号的意志决绝感显著爆发**。

---

### 3. 第 3 部分（特级威压与领域咏唱・附赠参考）
* **台词文本**：  
  `领域展开……！<真|ZHEN1><赝|YAN4>相爱。`
* **参数对比**：
  * **版本 A (无控制)**：`emo_vector = None` | 语速 `1.0x`
  * **版本 B (Jev控制)**：`emo_vector = [0.0, 0.92, 0.0, 0.0, 0.0, 0.0, 0.0, 0.70]`（主导：威压 0.92、平静 0.70）| 语速 `0.88x`
* **试听文件**：
  * 版本 A：[`audio/part3_domain_expansion_A_no_emotion.wav`](../../assets/audio/part3_domain_expansion_A_no_emotion.wav) (3.31s)
  * 版本 B：[`audio/part3_domain_expansion_B_with_jev_emotion.wav`](../../assets/audio/part3_domain_expansion_B_with_jev_emotion.wav) (2.52s)

---

## 四、 本实验规避的底层工程暗坑

在本次对比实验的所有音频生成中，全面封死了此前排查出的三大底层缺陷：

1. **撮口呼（ü）字典锁死**：
   * 官方 `checkpoints/pinyin.vocab` 采用 `V` 表示撮口呼。输入必须写为 **`<羂|JVAN4>`**，若误写为 `JUAN4` 会直接被词表丢弃而读错。
2. **多音字“了结”声调锁死**：
   * 显式标注 **`<了|LIAO3>结`**，彻底根除模型将“了”误读为助词轻声 `le`（le结）的顽疾。
3. **助词轻声化规避 `dì` 陷阱**：
   * “固执己见**的**”、“自以为是**的**”统一采用标准轻声字“的（de）”，彻底杜绝分词器误判为大地之 `dì`。
4. **底层解除 40 字硬切限制**：
   * 显式指定 `tts.low_vram = False`，解除 8GB 显卡长句被强制切断的机制。

---

## 五、 实验复现指南

本实验目录具备 100% 自包含性，可通过以下方式一键重新运行本实验并重新生成全部对照音频：

* **方式 1（推荐・双击批处理）**：  
  直接双击运行 [`run_experiment.bat`](../../applications/emotion-controlled-tts/run_experiment.bat)。
* **方式 2（PowerShell 命令行）**：  
  ```powershell
  D:\42427\TTS\index-tts\.venv\Scripts\python.exe d:\42427\Jev\jev-yuta-indextts\ab_comparison_experiment\run_experiment.py
  ```
