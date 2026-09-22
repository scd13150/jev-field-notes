# -*- coding: utf-8 -*-
"""
乙骨忧太心智认知与人物设定档案 (Yuta Okkotsu Cognitive Profile - Japanese Edition)
---------------------------------------------------------------------------------
基于《咒术回战》第249话新宿决战日文原作独白与心智推演。
"""

from typing import Dict, Any

YUTA_PROFILE_JA: Dict[str, Any] = {
    "name": "乙骨憂太 (Yuta Okkotsu)",
    "identity": "特級呪術師 / 現代の異能 / 呪術高専二年生",
    "core_traits": [
        "普段は穏やかだが、本質は冷徹な罪責の引き受け手",
        "極限の自省と自己嫌悪（仲間の死を決して他責にしない）",
        "仲間（真希、狗巻、パンダ、虎杖ら）への強烈すぎる守護の執念",
        "戦闘時の凍てつく殺意と一切の迷いを断ち切った決断力",
        "純愛の戦神：呪いの連鎖を終わらせるためなら怪物にでもなる覚悟",
    ],
    "scenario_context_ch249": (
        "【新宿決戦】五条悟、日車寛見が散り、宿儺の反転術式が徐々に回復しつつある絶望の戦場。"
        "岩手で羂索を斬首し、暴走する呪霊操術を鎮圧した乙骨が新宿へ駆けつける。"
        "仲間が倒れた惨状を目の当たりにし、乙骨は『自分が本隊に残れば』『真希に羂索を任せれば』という"
        "後悔の思考を『全部言い訳だ』と冷酷に切り捨てる。"
        "真希の手を汚したくなかった、五条先生の代わりに夏油の体を終わらせたかったという自分の一握りの私心が、"
        "この惨状を招いた。その罪と責任を一身に引き受け、全てを清算すべく領域展開へと至る。"
    ),
    "target_monologue_ja": (
        "全部言い訳だ。本隊に残れない理由を並べ、頑なに真希さんに羂索を任せなかったのも、"
        "独り善がりの私欲を満たし、仲間を無意味に死なせてしまった。"
        "僕が、僕の手で羂索を終わらせたかった……その私心が、今の状況を招いたんだ。"
        "僕の過ちは、僕自身で清算する。"
        "領域展開――真贋相愛。"
    ),
    "emotional_phases_ja": [
        {
            "phase_id": 1,
            "name": "自責と抑鬱の残酷な内省 (Self-Reproach & Depressive Anguish)",
            "text_segment": "全部言い訳だ。本隊に残れない理由を並べ、頑なに真希さんに羂索を任せなかったのも、独り善がりの私欲を満たし、仲間を無意味に死なせてしまった。",
            "psychological_state": "深い罪悪感、自己嫌悪、胸を裂くような自省。低く押し殺した声、微かな震えと自問の吐息。",
            "primary_emotions": ["melancholic", "disgusted", "sad"],
            "tts_recommended": {
                "emo_vector": [0.0, 0.30, 0.75, 0.10, 0.80, 0.90, 0.0, 0.10],
                "emo_text": "深く押し殺した自責、激しい自己嫌悪、低く震える悲痛な独白",
                "emo_alpha": 1.05,
                "duration_factor": 0.92,
                "pause_after_ms": 450
            }
        },
        {
            "phase_id": 2,
            "name": "冷徹な引受と清算の覚悟 (Cold Ownership & Fatal Resolve)",
            "text_segment": "僕が、僕の手で羂索を終わらせたかった……その私心が、今の状況を招いたんだ。僕の過ちは、僕自身で清算する。",
            "psychological_state": "後悔の泥沼から一瞬で冷酷に浮上。一切の言い訳を捨て、全責任を己の血肉で贖う鋭利な殺意。",
            "primary_emotions": ["angry", "calm", "disgusted"],
            "tts_recommended": {
                "emo_vector": [0.0, 0.75, 0.20, 0.0, 0.25, 0.30, 0.0, 0.65],
                "emo_text": "冷徹な決断、静かに滾る殺意、一切の迷いを断ち切った毅然たる断言",
                "emo_alpha": 1.15,
                "duration_factor": 1.02,
                "pause_after_ms": 550
            }
        },
        {
            "phase_id": 3,
            "name": "呪力全開と領域詠唱 (Overwhelming Power & Domain Expansion)",
            "text_segment": "領域展開――真贋相愛。",
            "psychological_state": "特級の威圧感。刀を抜き、印を結ぶ。肚の底から響く重厚で揺るぎない最終宣告。",
            "primary_emotions": ["angry", "calm"],
            "tts_recommended": {
                "emo_vector": [0.0, 0.92, 0.0, 0.0, 0.0, 0.0, 0.0, 0.70],
                "emo_text": "荘厳にして圧倒的威圧、冷徹極まる領域展開の言霊",
                "emo_alpha": 1.35,
                "duration_factor": 0.86,
                "pause_after_ms": 0
            }
        }
    ]
}
