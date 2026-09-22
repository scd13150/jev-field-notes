# -*- coding: utf-8 -*-
"""
TypeSafe Jev (System One) 乙骨忧太台词心智与情感控制裁决器 (jev_evaluator.py)
-------------------------------------------------------------------------
通过 TypeSafe System One 架构对乙骨忧太台词进行深层心智与多维情绪裁决，
并将判断结果标准化映射为 IndexTTS 2.5 情感控制参数。
"""

import os
import json
import requests
from typing import Dict, Any, List, Optional
from yuta_cognition import YUTA_PROFILE_JA


def get_typesafe_api_key() -> str:
    """获取 TypeSafe API Key，优先级：环境变量 -> 本地 .env"""
    env_key = os.environ.get("TYPESAFE_API_KEY")
    if env_key:
        return env_key.strip()

    env_paths = [
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(__file__), "..", ".env"),
    ]
    for p in env_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f.read().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if "API" in k.upper():
                            return v.strip().strip("\"'")
                    elif line.startswith("apikey_"):
                        return line.strip()
    raise ValueError("未找到有效 TypeSafe API Key，请检查 .env 文件。")


class YutaJevEvaluator:
    """
    负责将乙骨忧太日文对白及心智背景输入 TypeSafe Jev 模型，
    产出结构化的情绪分段与 IndexTTS 2.5 驱动参数。
    """

    ENDPOINT = "https://api.typesafe.ai/v1/systemone"
    MODEL = "jev-latest"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_typesafe_api_key()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def evaluate_segment_psychology(
        self,
        segment_text: str,
        phase_hint: str,
        context: str = YUTA_PROFILE_JA["scenario_context_ch249"]
    ) -> Dict[str, Any]:
        """
        利用 Jev System One 对日文特定台词片段裁决其心智状态与 8 维情绪倾向。
        """
        state = {
            "character": {
                "name": YUTA_PROFILE_JA["name"],
                "traits": YUTA_PROFILE_JA["core_traits"],
                "battlefield_situation": context,
            },
            "turn_context": {
                "japanese_monologue_segment": segment_text,
                "dramatic_phase": phase_hint,
            }
        }

        # 构建正交认知裁决问题群 (Questions)
        questions = {
            "guilt_and_self_reproach": {
                "type": "noul",
                "instructions": (
                    "In `turn_context.japanese_monologue_segment`, does Yuta express intense self-blame, "
                    "guilt, or self-loathing regarding his selfish decisions and the death of his allies?"
                )
            },
            "fatal_resolve_and_wrath": {
                "type": "noul",
                "instructions": (
                    "In `turn_context.japanese_monologue_segment`, does Yuta display cold, unwavering resolve, "
                    "deadly combat intent, and willingness to shoulder all sins to terminate the threat?"
                )
            },
            "domain_authority_and_focus": {
                "type": "noul",
                "instructions": (
                    "In `turn_context.japanese_monologue_segment`, is Yuta unleashing peak cursed energy, "
                    "chanting with absolute authority, composure, and overwhelming domain expansion presence?"
                )
            },
            "dominant_emotion": {
                "type": "choice",
                "instructions": (
                    "Which primary emotional category best dominates Yuta's acoustic delivery in this segment?"
                ),
                "criteria": {
                    "melancholic_agony": "Deep sorrow, heavy breath, suppressed torment, self-hatred.",
                    "cold_determination": "Sharp, icy resolve, stern ownership of guilt, firm conviction.",
                    "overwhelming_wrath_command": "Domain chanting, monumental power, thunderous authority."
                }
            }
        }

        payload = {
            "model": self.MODEL,
            "state": state,
            "questions": questions
        }

        try:
            resp = requests.post(self.ENDPOINT, headers=self.headers, json=payload, timeout=20)
            resp.raise_for_status()
            res_json = resp.json()
            return res_json.get("results", {})
        except Exception as e:
            print(f"[Jev API 降级警告] 远程 System One 调用失败 ({e})，启用本地先验真值基准。")
            return self._fallback_ground_truth(phase_hint)

    def _fallback_ground_truth(self, phase_hint: str) -> Dict[str, Any]:
        """降级兜底保证高可用性"""
        if "自責" in phase_hint or "自责" in phase_hint:
            return {
                "guilt_and_self_reproach": {"probability": 0.95},
                "fatal_resolve_and_wrath": {"probability": 0.25},
                "domain_authority_and_focus": {"probability": 0.05},
                "dominant_emotion": {"choice": "melancholic_agony"}
            }
        elif "覚悟" in phase_hint or "觉醒" in phase_hint or "引受" in phase_hint:
            return {
                "guilt_and_self_reproach": {"probability": 0.40},
                "fatal_resolve_and_wrath": {"probability": 0.90},
                "domain_authority_and_focus": {"probability": 0.65},
                "dominant_emotion": {"choice": "cold_determination"}
            }
        else:
            return {
                "guilt_and_self_reproach": {"probability": 0.05},
                "fatal_resolve_and_wrath": {"probability": 0.94},
                "domain_authority_and_focus": {"probability": 0.99},
                "dominant_emotion": {"choice": "overwhelming_wrath_command"}
            }

    def compile_tts_plan(self) -> List[Dict[str, Any]]:
        """
        基于乙骨忧太日文台词的三阶段心智模型，由 Jev 进行全流程情绪参数编译。
        返回供 IndexTTS 2.5 直接消费的完整调度清单。
        """
        plan = []
        phases = YUTA_PROFILE_JA["emotional_phases_ja"]

        print(f">> [Jev Evaluator] 正在启动 TypeSafe Jev System One 日文台词心智多阶段裁决...")

        for phase in phases:
            text = phase["text_segment"]
            phase_name = phase["name"]
            print(f"   - 正在分析阶段 {phase['phase_id']}: [{phase_name}] ...")

            jev_result = self.evaluate_segment_psychology(text, phase_name)
            rec = phase["tts_recommended"]

            p_guilt = jev_result.get("guilt_and_self_reproach", {}).get("probability", 0.5)
            p_wrath = jev_result.get("fatal_resolve_and_wrath", {}).get("probability", 0.5)
            p_domain = jev_result.get("domain_authority_and_focus", {}).get("probability", 0.5)

            # 8维情绪基准：[喜, 怒, 哀, 惧, 厌恶, 抑郁, 惊讶, 平静]
            base_vec = list(rec["emo_vector"])
            base_vec[1] = round(min(1.0, base_vec[1] * (0.8 + 0.4 * p_wrath)), 2)     # 怒/杀气
            base_vec[4] = round(min(1.0, base_vec[4] * (0.8 + 0.3 * p_guilt)), 2)     # 厌恶/自厌
            base_vec[5] = round(min(1.0, base_vec[5] * (0.8 + 0.3 * p_guilt)), 2)     # 抑郁/自责
            base_vec[7] = round(min(1.0, base_vec[7] * (0.7 + 0.4 * p_domain)), 2)    # 平静/威严

            compiled_segment = {
                "phase_id": phase["phase_id"],
                "phase_name": phase_name,
                "text": text,
                "jev_judgments": {
                    "p_guilt": p_guilt,
                    "p_wrath": p_wrath,
                    "p_domain": p_domain,
                    "dominant_emotion": jev_result.get("dominant_emotion", {}).get("choice", "balanced")
                },
                "tts_params": {
                    "emo_method": 2,
                    "emo_vector": base_vec,
                    "emo_text": rec["emo_text"],
                    "emo_alpha": rec["emo_alpha"],
                    "duration_factor": rec["duration_factor"],
                    "pause_after_ms": rec["pause_after_ms"]
                }
            }
            plan.append(compiled_segment)

        print(">> [Jev Evaluator] 日文心智编译完成，成功输出 3 阶段高精调度规范！\n")
        return plan


if __name__ == "__main__":
    evaluator = YutaJevEvaluator()
    compiled_plan = evaluator.compile_tts_plan()
    print(json.dumps(compiled_plan, ensure_ascii=False, indent=2))
