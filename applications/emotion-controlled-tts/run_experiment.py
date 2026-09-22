# -*- coding: utf-8 -*-
"""
A/B 情感控制对比实验复现脚本 (run_experiment.py)
----------------------------------------------------------------------
本脚本用于独立、端到端重现【无情感控制(Baseline)】与【Jev情感控制】对比音频。
包含 CUDA 显存主动释放逻辑，杜绝长批次推理导致的内存置换降速。
"""

import os
import sys
import time
import soundfile as sf
import torch

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_TTS_DIR = r"D:\42427\TTS\index-tts"
if INDEX_TTS_DIR not in sys.path:
    sys.path.insert(0, INDEX_TTS_DIR)

os.environ["USE_MODELSCOPE"] = "true"
if "UV_CACHE_DIR" not in os.environ:
    os.environ["UV_CACHE_DIR"] = r"D:\uv_cache"

from indextts.infer_v2_5 import IndexTTS2

EXPERIMENTAL_CASES = [
    {
        "id": 1,
        "name": "part1_self_reproach",
        "title": "第 1 部分（残酷自省与自厌抑郁）",
        "text": "全都是借口……说什么不能留在主战场帮忙，固执己见的不让真希学姐去杀<羂|JVAN4>索，自以为是的满足一己私欲，放任伙伴无意义死去……",
        "jev_emo": [0.0, 0.30, 0.70, 0.10, 0.75, 0.85, 0.0, 0.15], # 抑郁0.85, 自厌0.75, 哀0.70
        "dur_jev": 0.95,
        "dur_base": 1.0,
    },
    {
        "id": 2,
        "name": "part2_cold_resolve",
        "title": "第 2 部分（冷酷担当与清算觉醒）",
        "text": "是我想亲手<了|LIAO3>结<羂|JVAN4>索的私心，造成了现在的状况。我的错，就由我来终结！",
        "jev_emo": [0.0, 0.85, 0.10, 0.0, 0.20, 0.20, 0.0, 0.65], # 杀意愤怒0.85, 冷静0.65
        "dur_jev": 1.05,
        "dur_base": 1.0,
    },
    {
        "id": 3,
        "name": "part3_domain_expansion",
        "title": "第 3 部分（特级威压与领域咏唱）",
        "text": "领域展开……！<真|ZHEN1><赝|YAN4>相爱。",
        "jev_emo": [0.0, 0.92, 0.0, 0.0, 0.0, 0.0, 0.0, 0.70], # 威压0.92, 平静0.70
        "dur_jev": 0.88,
        "dur_base": 1.0,
    },
]

REF_AUDIO = os.path.join(CURRENT_DIR, "prompts", "yuta_ref.wav")
AUDIO_OUT_DIR = os.path.join(CURRENT_DIR, "audio")


def main():
    os.makedirs(AUDIO_OUT_DIR, exist_ok=True)
    print("=" * 70)
    print("      【Jev + IndexTTS 2.5】 情感控制 A/B 独立对比实验套件")
    print("=" * 70)
    print(f">> 音色基准文件: {REF_AUDIO}")
    print(f">> 音频输出目录: {AUDIO_OUT_DIR}\n")

    if not os.path.exists(REF_AUDIO):
        print(f"[错误] 参考音色文件不存在: {REF_AUDIO}")
        sys.exit(1)

    start_t = time.time()
    tts = IndexTTS2(
        cfg_path=os.path.join(INDEX_TTS_DIR, "checkpoints", "config.yaml"),
        model_dir=os.path.join(INDEX_TTS_DIR, "checkpoints"),
        use_bf16=True,
        use_qwen_emo=False,
    )
    tts.low_vram = False
    print(f">> 模型加载完成，耗时: {time.time() - start_t:.2f}s\n")

    for item in EXPERIMENTAL_CASES:
        pname = item["name"]
        title = item["title"]
        text = item["text"]
        jev_emo = item["jev_emo"]

        print("----------------------------------------------------------------------")
        print(f"▶ 实验用例: {title}")
        print(f"   对白文本: \"{text}\"")
        print("----------------------------------------------------------------------")

        # 1. Baseline: 无情感控制 (emo_vector = None)
        out_a = os.path.join(AUDIO_OUT_DIR, f"{pname}_A_no_emotion.wav")
        print(f"   >> 正在生成 [版本 A: 无情感控制] ...")
        t_a = time.time()
        res_a = tts.infer(
            spk_audio_prompt=REF_AUDIO,
            text=text,
            output_path=None,
            lang="ZH",
            emo_audio_prompt=None,
            emo_alpha=1.0,
            emo_vector=None,
            use_emo_text=False,
            use_random=False,
            interval_silence=200,
            verbose=False,
            max_text_tokens_per_segment=120,
            duration_factor=item["dur_base"],
            temperature=0.70,
            top_p=0.80,
            top_k=30,
            num_beams=3,
            repetition_penalty=10.0,
            do_sample=True,
            max_mel_tokens=3000,
        )
        if res_a:
            sr, w = res_a
            if w.ndim > 1:
                w = w.squeeze()
            sf.write(out_a, w, sr, subtype="PCM_16")
            print(f"   ✔ [版本 A] 就绪: {os.path.basename(out_a)} ({len(w)/sr:.2f}s, 耗时 {time.time() - t_a:.2f}s)")

        torch.cuda.empty_cache()

        # 2. Jev: 注入 8 维情绪向量
        out_b = os.path.join(AUDIO_OUT_DIR, f"{pname}_B_with_jev_emotion.wav")
        print(f"   >> 正在生成 [版本 B: Jev 情感控制] ... (向量: {jev_emo})")
        t_b = time.time()
        cur_vec = tts.normalize_emo_vec(jev_emo, apply_bias=True)
        res_b = tts.infer(
            spk_audio_prompt=REF_AUDIO,
            text=text,
            output_path=None,
            lang="ZH",
            emo_audio_prompt=None,
            emo_alpha=1.2,
            emo_vector=cur_vec,
            use_emo_text=False,
            use_random=False,
            interval_silence=200,
            verbose=False,
            max_text_tokens_per_segment=120,
            duration_factor=item["dur_jev"],
            temperature=0.72,
            top_p=0.82,
            top_k=30,
            num_beams=3,
            repetition_penalty=10.0,
            do_sample=True,
            max_mel_tokens=3000,
        )
        if res_b:
            sr, w = res_b
            if w.ndim > 1:
                w = w.squeeze()
            sf.write(out_b, w, sr, subtype="PCM_16")
            print(f"   ✔ [版本 B] 就绪: {os.path.basename(out_b)} ({len(w)/sr:.2f}s, 耗时 {time.time() - t_b:.2f}s)\n")

        torch.cuda.empty_cache()

    print("=" * 70)
    print(">> [全部就绪] 实验对比音频已完整输出至 audio/ 目录！")
    print("=" * 70)


if __name__ == "__main__":
    main()
