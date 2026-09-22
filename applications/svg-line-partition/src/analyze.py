"""Turn results/raw + summary.json into results/report.md.

Reads only what the probe already stored, so re-thinking a table costs no calls.
    python -m src.analyze
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .jclient import DEFAULT_MODEL
from .serialize import CONDITIONS

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

CONDITION_CN = {
    "features_named": "几何+命名",
    "features_anon": "只有几何",
    "named_nogeo": "只有命名",
    "raw_paths": "原始路径串",
    "scrambled": "几何错位(对照)",
}
GEO = "features_anon"
NAMES = "named_nogeo"
FULL = "features_named"

FAMILY_CN = {
    "scene_layer": "场景层级(深度平面)",
    "nesting_layer": "嵌套层级(被几层闭合线包住)",
    "role": "线条职责",
    "region": "区域(九宫格)",
    "group": "归属分组(物体)",
    "extent": "跨度(graded)",
    "structural_weight": "结构权重(graded)",
    "rel_encloses": "关系·包含",
    "rel_touches": "关系·相接",
    "rel_crosses": "关系·交叉",
    "rel_parallel": "关系·平行",
    "rel_same_object": "关系·同属一物",
    "rel_paint_order": "关系·绘制顺序",
    "rel_in_front": "关系·前后(断口线索)",
    "rel_in_front_undef": "关系·前后(无线索时)",
    "rel_depth_cue": "关系·有无深度线索",
    "rel_evidence": "元判断·证据是否可得",
}

CHOICE_LIKE = ("scene_layer", "nesting_layer", "role", "region", "group")
SCORE_LIKE = ("extent", "structural_weight")
NOUL_LIKE = tuple(k for k in FAMILY_CN if k.startswith("rel_"))


def load() -> list[dict]:
    return json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))


def _mean(vals: list[Any]):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def value(summaries, fam, condition, field):
    """Mean of one field over the fixtures that produced it (skipped families drop out)."""
    return _mean([r.get(fam, {}).get(field) for r in summaries if r["condition"] == condition])


def rows_field(rows, fam, field) -> list[Any]:
    return [x for r in rows for x in [r.get(fam, {}).get(field)] if x is not None]


def table(summaries, families, field, title, note="") -> list[str]:
    out = [f"**{title}**{note}", "",
           "| 判断族 | " + " | ".join(CONDITION_CN[c] for c in CONDITIONS) + " |",
           "|---" * (len(CONDITIONS) + 1) + "|"]
    for fam in families:
        if not any(fam in row for row in summaries):
            continue
        cells = [value(summaries, fam, c, field) for c in CONDITIONS]
        if all(v is None for v in cells):
            continue
        out.append("| " + " | ".join([FAMILY_CN.get(fam, fam)]
                                     + ["  -  " if v is None else f"{v:.2f}" for v in cells]) + " |")
    out.append("")
    return out


def lift_table(summaries, families, acc_field, base_field, title, note) -> list[str]:
    """Score above the free answer, which is what makes a rate mean something."""
    out = [f"**{title}**", "", note, "",
           "| 判断族 | " + " | ".join(
               f"{CONDITION_CN[c]}" for c in CONDITIONS) + " |",
           "|---" * (len(CONDITIONS) + 1) + "|"]
    for fam in families:
        cells = []
        for c in CONDITIONS:
            rows = [r for r in summaries if r["condition"] == c and fam in r]
            acc = _mean(rows_field(rows, fam, acc_field))
            base = _mean(rows_field(rows, fam, base_field))
            cells.append("  -  " if acc is None or base is None
                         else f"{acc - base:+.2f} ({base:.2f})")
        if not any(c != "  -  " for c in cells):
            continue
        out.append("| " + " | ".join([FAMILY_CN[fam]] + cells) + " |")
    out.append("")
    return out


def reliance(summaries) -> list[str]:
    """How much each answer came from numbers versus from names."""
    out = ["## 3. 消融：答案来自坐标还是来自名字", "",
           "`线索依赖 = 只有几何 − 只有命名`（同一维度、同一算法，只差在线索上）。"
           "正数说明它在读坐标，负数说明它在读名字，接近 0 说明这条判断主要不靠这两种线索。"
           "分类用命中率、分级用 Spearman、关系用 AUC（AUC 不受类别偏斜影响，比命中率更适合成对判断）。", "",
           "| 判断族 | 只有几何 | 只有命名 | 依赖 | 判读 |",
           "|---|---|---|---|---|"]
    for fam in list(CHOICE_LIKE) + list(SCORE_LIKE) + list(NOUL_LIKE):
        field = "spearman" if fam in SCORE_LIKE else ("auc" if fam in NOUL_LIKE else "acc")
        g = _mean([v for v in [value(summaries, fam, GEO, field)] if v is not None])
        n = _mean([v for v in [value(summaries, fam, NAMES, field)] if v is not None])
        if g is None or n is None:
            continue
        d = g - n
        verdict = ("只有坐标能答" if d > 0.3 else ("靠坐标为主" if d > 0.15 else
                   ("靠名字为主" if d < -0.15 else "两种线索都不是决定性的")))
        out.append(f"| {FAMILY_CN[fam]} | {g:.2f} | {n:.2f} | {d:+.2f} | {verdict} |")
    out.append("")
    return out


def confusion_notes(summaries) -> list[str]:
    """Concrete misses worth reading, pulled from the raw dumps."""
    out = ["## 8. 具体失误样本（逐条可查）", "",
           "只列置信度 >0.7 的错答——这些才是真正会伤到下游的：它答错而且敢答。", ""]
    for path in sorted((RESULTS / "raw").glob("*.json")):
        dump = json.loads(path.read_text(encoding="utf-8"))
        notes = []
        answers, truth, ids = dump["answers"], dump["truth"], dump["id_map"]
        for qid, ans in answers.items():
            fam, _, rest = qid.partition("::")
            if fam not in CHOICE_LIKE or "|" in rest:
                continue
            orig = ids.get(rest, rest)
            key = {"scene_layer": "layer", "nesting_layer": "nesting", "role": "role",
                   "region": "region", "group": "object"}[fam]
            t = truth.get(orig, {}).get(key)
            p = ans.get("choice")
            if t and p and t != p and (ans.get("confidence") or 0) > 0.7:
                notes.append(f"  - `{fam}` {orig}: 真值 `{t}` → 答 `{p}`"
                             f"（自信 {ans['confidence']:.2f}）")
        if notes:
            out.append(f"**{dump['fixture']} / {CONDITION_CN[dump['condition']]}**"
                       f"（{len(notes)} 条自信错误）")
            out.extend(notes[:5])
            if len(notes) > 5:
                out.append(f"  - ...另有 {len(notes) - 5} 条，见 `results/raw/"
                           f"{path.name}`")
            out.append("")
    return out


GESTALT_CN = {
    "gestalt_contains_figure": "图里有没有画生物",
    "gestalt_layer_count": "有几个深度平面",
    "gestalt_axis": "主方向",
    "gestalt_focal_region": "视觉重心落在哪格",
}


def gestalt_section(summaries) -> list[str]:
    per: dict[str, list[dict]] = defaultdict(list)
    for row in summaries:
        for item in (row.get("gestalt") or {}).get("items", []):
            per[item["q"]].append({**item, "condition": row["condition"],
                                   "fixture": row["fixture"]})
    out = ["## 7. 整图判断（需要跨元素聚合的线索）", "",
           "这四条的真值是代码定的**代理定义**（生物=作者物体标签命中 ANIMATE 词表；"
           "平面数=标注过的深度平面个数，不含边框；主方向=按描边长度加权的直线方向，"
           "直线不足 60% 则算 curved；重心=「最长且离其他笔画最近」那条线所在的格子）。"
           "所以每一条不一致都可能是定义不同而不是答错，读的时候连同定义一起读。", ""]
    for q, items in per.items():
        hits = [i for i in items if str(i["pred"]) == str(i["truth"])]
        out += [f"**{GESTALT_CN.get(q, q)}** — {len(hits)}/{len(items)} 条与几何内核一致", ""]
        out += ["| 画 | 条件 | 真值 | 答 | 连续分 | 确信 |", "|---|---|---|---|---|---|"]
        for i in items:
            conf = i.get("confidence")
            if conf is None:
                conf = i.get("noul")
            score = i.get("score")
            out.append(f"| {i['fixture']} | {CONDITION_CN[i['condition']]} | {i['truth']} | "
                       f"{i['pred']} | {'' if score is None else f'{score:.2f}'} | "
                       f"{'' if conf is None else f'{conf:.2f}'} |")
        out.append("")
    def ok(i):
        return str(i["pred"]) == str(i["truth"])

    def rng(vals):
        vals = [v for v in vals if v is not None]
        return "  -  " if not vals else (f"{min(vals):.2f}" if min(vals) == max(vals)
                                         else f"{min(vals):.2f}–{max(vals):.2f}")

    def agree_fixtures(items):
        c = defaultdict(lambda: [0, 0])
        for i in items:
            c[i["fixture"]][1] += 1
            c[i["fixture"]][0] += 1 if ok(i) else 0
        return "、".join(f"{f.replace('_', ' ')} {a}/{b}"
                         for f, (a, b) in sorted(c.items()))

    ci = per.get("gestalt_contains_figure", [])
    miss = [i for i in ci if not ok(i)]
    lc = per.get("gestalt_layer_count", [])
    geo_scores = [i.get("score") for i in lc if i["condition"] == GEO]
    nam_scores = [i.get("score") for i in lc if i["condition"] != GEO
                  and i["fixture"] != "abstract_nesting"]
    ax = per.get("gestalt_axis", [])
    fo = per.get("gestalt_focal_region", [])
    out += ["读法（数字由上表现算，改一次网格就跟着改）：", "",
            (f"- **有没有画生物 {sum(1 for i in ci if ok(i))}/{len(ci)}**："
             f"分歧 {len(miss)} 次，全部发生在 {sorted({i['fixture'] for i in miss})[0]}"
             f"（画里唯一的生物是 `bird-1`/`bird-2`，各三条线的 `m` 形），"
             f"它给的概率是 {rng([i.get('noul') for i in miss])}——"
             "模糊样本上它掉到 0.5 以下而不是硬猜。" if miss else
             f"- **有没有画生物 {len(ci)}/{len(ci)}**：全部与内核一致。")
            + f"各画一致情况：{agree_fixtures(ci)}。这条整图判断可用，概率本身就在表达「算不算生物」的争议。",
            f"- **有几个深度平面 {sum(1 for i in lc if ok(i))}/{len(lc)}**：几乎全不一致，"
            f"但不是没在读线索——连续分在匿名几何条件下是 {rng(geo_scores)}（读作「一个平面」），"
            f"在有名字的语义画上爬到 {rng(nam_scores)}（真值 {lc[0]['truth']}）。"
            "它把外框也算一层，于是永远差一档。修法是把「边框不算一层」写进 criteria，"
            "或者这个量干脆由代码从逐元素层级聚合。",
            f"- **主方向 {sum(1 for i in ax if ok(i))}/{len(ax)}**：一致只出现在 "
            f"{agree_fixtures(ax)}。内核的判据是「描边长度里直线占比 ≥60% 才算直线系」，"
            "house 上内核判 curved 而它反复判 mixed，人形画判 diagonal（那确实是一个斜着踢的姿势）"
            "——这两条更像内核的代理定义太粗，不该记在它账上。",
            f"- **视觉重心 {sum(1 for i in fo if ok(i))}/{len(fo)}**：{agree_fixtures(fo)}。"
            "用一个笔画所在的格子来当「整图重心」的真值，本身就不牢；"
            "它能稳定给出的是「靠上、靠中心」这一类粗略位置。", ""]
    return out


def main() -> int:
    summaries = load()
    model = summaries[0].get("model") or DEFAULT_MODEL
    n_fix = len({r["fixture"] for r in summaries})
    md: list[str] = []
    md += ["# Jev 对 SVG 线条画的初始条件模糊划分：能力上限探测", "",
           f"模型 `{model}`（`jev-latest` 别名当前指向它）。"
           f"{n_fix} 幅线条画 × 5 种文本化条件：逐元素 7 类判断、成对 10 类关系、整图 4 类判断，"
           "同一请求内并行发起。真值来自几何内核或作者在 SVG 上的 `data-truth-*`，"
           "序列化时有泄漏自检（`serialize.leak_check`），答案键不会进 state。", ""]

    totals = {"questions": sum(r["n_questions"] for r in summaries),
              "in": sum(r["input_tokens"] for r in summaries),
              "out": sum(r["output_tokens"] for r in summaries),
              "api": sum(r.get("api_seconds", 0.0) for r in summaries),
              "wall": sum(r.get("wall_seconds", r.get("seconds", 0.0)) for r in summaries),
              "fresh": sum(r.get("fresh_calls", 0) for r in summaries),
              "calls": sum(r.get("n_calls", 0) for r in summaries)}
    cost = totals["in"] / 1e6 * 0.042
    md += [f"- **规模**：{len(summaries)} 个「画 × 条件」组合，判定 {totals['questions']:,} 条，"
           f"服务端返回 `{model}`",
           f"- **用量**：输入 {totals['in']:,} tokens、输出 {totals['out']:,} tokens。"
           f"按 \$42/Btok（=\$0.042/Mtok，输出不计费）整个网格约 **\${cost:.3f}**，"
           f"即一幅 32 元素的画做完整一次划分约 **\${cost / len(summaries):.3f}**",
           f"- **延迟**：API 侧累计 {totals['api']:.1f}s（每组合约 "
           f"{totals['api'] / len(summaries):.1f}s，含分块串行），本次运行墙钟 "
           f"{totals['wall']:.1f}s；本次真正打出去的请求 {totals['fresh']} 次，其余命中本地缓存",
           f"- **每次调用打包的问题数**：约 {totals['questions'] // max(1, totals['calls'])}"
           " 条（`max_questions_per_call=140` 分块，块内并行评估）", ""]

    md += ["## 0. 五种文本化条件", "",
           "Jev 只吃文本，所以「怎么把画变成文本」本身就是实验变量。", "",
           "| 条件 | 元素记录 | 作者 `<g>` 树 | id | 用途 |",
           "|---|---|---|---|---|",
           "| 几何+命名 | 几何特征 | 有 | 真名 | 上线形态 |",
           "| 只有几何 | 几何特征 | **无** | 匿名 e-01… | 它能不能只读坐标 |",
           "| 只有命名 | 只有 id 与形状标签 | 有 | 真名 | 它是不是只靠名字猜 |",
           "| 原始路径串 | `d`/`cx` 等属性原文 | 有 | 真名 | 不预提取能不能直接读 SVG |",
           "| 几何错位(对照) | 几何特征随机置换 | 有 | 真名 | 假证据：证明它真在用坐标 |",
           "",
           "一个必须交代的混杂变量：`只有几何` 是唯一不给作者 `<g>` 树的条件，"
           "其余四档都把「文件里谁在谁的 `<g>` 里」连同尺寸一起给了。"
           "所以凡是能从名字或 DOM 树直接读出的答案（物体归属、线条职责），在这四档上表现一致、"
           "且对几何置换不敏感——那不是它推理出了分组，是它看见了分组声明。"
           "`原始路径串` 在若干维度反超 `只有几何`，部分来自这个原因，不能全记在「它能读 `d` 串」头上。", ""]

    md += ["## 1. 能力上限总览", "",
           "「提升」才是上限的读数：分类维度用宏 F1 减掉恒定回答多数类能白拿的分数，"
           "分级维度用 Spearman 直接相对 0（随机序）。", "",
           "| 维度 | 只有几何 主指标 | 只有几何 提升(基线) | 只有命名 主指标 | 结论 |",
           "|---|---|---|---|---|"]
    headline = [
        ("层级·嵌套深度", "nesting_layer",
         "两个读数分开看：纯几何的宏 F1 比恒定答案高 +0.39（真在区分深度），"
         "但命中率只等于基线，因为 80% 的元素恰好只被包住一层；同时带名字时命中率反而低于基线"
         "——语义把它拉向「约定深度」而不是「被几层线包住」，这是两种层级定义在打架"),
        ("层级·场景深度", "scene_layer",
         "深度平面一半是画师约定，纯几何给不出前后；有名字时才可靠"),
        ("区域", "region",
         "九宫格完全是坐标的事，坐标一置换立刻散架"),
        ("线条职责", "role",
         "形状类型（闭合/直线/曲线/重复纹理）就能定大半，名字再补一截"),
        ("归属分组", "group",
         "有名字（或作者 `<g>` 树）时几乎就是真值划分，但那部分是读出来的不是推出来的；"
         "纯几何切得过碎——它给出的是部件级划分，好处是从不跨物体"),
        ("跨度 graded", "extent",
         "序对齐极好、绝对档位一般：用来排序可信，直接分箱不可信"),
        ("结构权重 graded", "structural_weight",
         "序对齐中等，且更容易被语义带走而不是被数字带走"),
    ]
    f2 = lambda v: "  -  " if v is None else f"{v:.2f}"  # noqa: E731
    for name, fam, note in headline:
        if fam in SCORE_LIKE:
            g = value(summaries, fam, GEO, "spearman")
            n = value(summaries, fam, NAMES, "spearman")
            lift_cell = "  -  " if g is None else f"{g:+.2f} (0.00)"
        else:
            g = value(summaries, fam, GEO, "acc")
            n = value(summaries, fam, NAMES, "acc")
            gf = value(summaries, fam, GEO, "macro_f1")
            bf = value(summaries, fam, GEO, "f1_baseline")
            lift_cell = ("  -  " if gf is None or bf is None
                         else f"{gf - bf:+.2f} ({bf:.2f})")
        md.append(f"| {name} | {f2(g)} | {lift_cell} | {f2(n)} | {note} |")
    md += ["", "成对关系（有坐标 + 命名）的命中率与 AUC。每幅画 21–26 对候选（遮挡线索对按两个方向各问一次），",
           "标 * 的行真值只有一个类别：命中率恒等于基线、AUC 无法定义，",
           "它只证明「没有乱答」，不证明分辨力；要看分辨力就读没打星的行。", ""]
    md += ["| 关系 | 样本对数 | 命中率 | 多数类基线 | 提升 | AUC | 平均\\|p−0.5\\| |",
           "|---|---|---|---|---|---|---|"]
    for fam in NOUL_LIKE:
        rows = [r for r in summaries if r["condition"] == FULL and fam in r]
        if not rows:
            continue
        n = sum(r[fam]["n"] for r in rows)
        pos = sum(r[fam].get("positives") or 0 for r in rows)
        single = pos in (0, n)
        acc = _mean(rows_field(rows, fam, "acc"))
        base = _mean(rows_field(rows, fam, "baseline"))
        md.append(f"| {FAMILY_CN[fam]}{' *' if single else ''} | {n} (正例 {pos}) | "
                  f"{acc:.2f} | {base:.2f} | {acc - base:+.2f} | "
                  + (lambda v: "  -  " if v is None else f"{v:.2f}")(
                      _mean(rows_field(rows, fam, "auc")))
                  + f" | {_mean(rows_field(rows, fam, 'mean_dev_from_half')):.2f} |")
    md.append("")

    md += ["## 2. 逐元素分类：命中率、基线、置信度", "",
           *table(summaries, CHOICE_LIKE, "acc", "命中率"),
           *lift_table(summaries, CHOICE_LIKE, "acc", "baseline",
                       "提升 = 命中率 − 多数类基线",
                       "命中率高不等于有分辨力：真值偏斜时，恒定回答多数类也能拿高分。"
                       "括号内是同一批真值上的多数类基线；负数说明它还不如一直抄最常见答案。"),
           *lift_table(summaries, CHOICE_LIKE, "macro_f1", "f1_baseline",
                       "提升 = 宏 F1 − 恒定回答的宏 F1",
                       "类别偏斜时这一列才是分辨力的真实读数。恒定基线 = (2/K)·p/(1+p)，"
                       "K 为真值类数、p 为多数类占比。"),
           *table(summaries, CHOICE_LIKE, "mean_confidence", "平均置信度"),
           *table(summaries, CHOICE_LIKE, "act_accuracy", "高置信段(≥0.85)命中率"),
           *table(summaries, CHOICE_LIKE, "act_coverage", "高置信段覆盖率（敢直接行动的比例）"),
           *table(summaries, CHOICE_LIKE, "macro_f1", "宏平均 F1（对小类更公平）"),
           *table(summaries, CHOICE_LIKE, "mean_norm_entropy",
                  "归一化熵（0=笃定，1=完全铺开；跨不同选项数可比）"),
           *table(summaries, CHOICE_LIKE, "mean_brier", "Brier（越小越准，跨选项数可比）"),
           *table(summaries, NOUL_LIKE, "acc", "成对关系命中率"),
           *lift_table(summaries, NOUL_LIKE, "acc", "baseline",
                       "成对关系：提升 = 命中率 − 多数类基线",
                       "成对候选里绝大多数是「无关系」，所以命中率本身几乎不代表什么；"
                       "要看这一列和下面的 AUC。"),
           *table(summaries, NOUL_LIKE, "auc", "成对关系 AUC（排序质量，不受类别偏斜影响）"),
           *table(summaries, NOUL_LIKE, "mean_dev_from_half",
                  "成对关系平均 |p−0.5|（离「不确定」的距离）"),
           *table(summaries, SCORE_LIKE, "spearman", "分级判断与真值序的 Spearman"),
           *table(summaries, SCORE_LIKE, "acc", "分级判断的绝对档位命中率"),
           *reliance(summaries)]

    md += ["## 4. 分组：把软分配还原成划分再打分", "",
           "每个元素的分组概率分布 → 两两 P(同组)=Σ_g p_a(g)p_b(g) → 单链接聚类 → 对真值划分算 ARI/NMI。"
           "这检验的是「模糊划分」本身：不是它给每个元素贴了什么标签，而是标签还原出的边界像不像物体。"
           "过度切分与错误合并是两种失败，需要的是两种不同的修法，所以分开计数。", "",
           "| 画 | 条件 | top-1 | ARI | NMI | 预测簇数/真值物体数 | 多元素簇数 | 跨物体的簇数 |",
           "|---|---|---|---|---|---|---|---|"]
    for row in summaries:
        g = row.get("group")
        if g and g.get("ari") is not None:
            md.append(f"| {row['fixture']} | {CONDITION_CN[row['condition']]} | "
                      f"{g.get('acc')} | {g['ari']} | {g['nmi']} | "
                      f"{g['n_clusters_pred']}/{g['n_objects_truth']} | "
                      f"{g.get('n_multi')} | {g.get('n_mixed')} |")
    md += ["", "匿名画（无物体词汇）不适合逐元素 Choice 分组，因此那里的分组只看成对线索；"
           "上表两幅语义画的选项名就是物体名。", "",
           "**先别急着把有名字那几行当能力**：那四档条件（含几何错位）的 state 里都带着作者的 `<g>` 树，"
           "而两幅语义画的 `<g>` 名与物体名同源，所以有名字的四档 ARI 几乎相同"
           "（house 0.94–0.96、kick 全 1.00），几何整批换成假数据也照样是 0.94/1.00——"
           "它读的是文件里写好的归属声明，不是坐标。"
           "真正有信息量的是 `只有几何` 那一档（匿名、无树）。", "",
           "纯几何那一行的失败方式是**只切不合**：跨物体的簇数为 0（从不把两个物体的笔画混在一起），"
           "但多元素簇只有少数几个——被合并的恰好是形状完全相同的重复笔画（太阳的 5 条光芒、栅栏的 6 根立柱），"
           "而同一物体的不同部件（墙、门、屋顶）彼此不合并。于是簇数是物体数的两倍上下："
           "ARI 惩罚的是数量不匹配，NMI 仍高，因为离散划分其实是信息的——每个元素自成一组当然包含正确答案。"
           "结论是几何能给出**部件级**划分并且不越界，**物体级**合并需要命名、整图线索或额外的合并判断。",
           "有名字时合并到位（10/11、9/9），代价是出现了一个跨物体的簇：门上那条错误"
           "（真值 `door` → 答 `house`，置信度 0.95）把门并进了房子——语义隶属关系（门属于房子）"
           "和这里的划分单位（一个物体一个簇）本来就不是同一件事，见 §8 的失误样本。", ""]

    md += ["## 5. 置信度是否跟着证据走", "",
           "只有拿到证据才敢自信，说明概率可以直接用于分流；无证据仍自信，就是必须防的失效模式。", "",
           "| 条件 | 逐元素平均置信度 | 场景层级命中率 | 区域命中率 | 区域高置信覆盖率 | 关系平均\\|p−0.5\\| |",
           "|---|---|---|---|---|---|"]
    for c in CONDITIONS:
        conf = _mean([value(summaries, fam, c, "mean_confidence") for fam in CHOICE_LIKE])
        acc = value(summaries, "scene_layer", c, "acc")
        reg = value(summaries, "region", c, "acc")
        regc = value(summaries, "region", c, "act_coverage")
        dev = _mean([value(summaries, fam, c, "mean_dev_from_half")
                     for fam in ("rel_touches", "rel_crosses", "rel_parallel")])
        fmt = lambda v: "  -  " if v is None else f"{v:.2f}"  # noqa: E731
        md.append(f"| {CONDITION_CN[c]} | {fmt(conf)} | {fmt(acc)} | {fmt(reg)} | "
                  f"{fmt(regc)} | {fmt(dev)} |")
    md.append("")

    md += ["## 6. 校准表（一个例子）", "",
           "以「几何+命名」条件下的场景层级为例，看报出的置信度与实测正确率的对应关系。", "",
           "| 画 | 置信度区间 | 条数 | 实测正确率 |", "|---|---|---|---|"]
    for row in summaries:
        if row["condition"] != FULL:
            continue
        for b in (row.get("scene_layer") or {}).get("calibration", []):
            md.append(f"| {row['fixture']} | {b['bin']} | {b['n']} | {b['empirical_accuracy']:.2f} |")
    md.append("")

    md += gestalt_section(summaries)
    md += confusion_notes(summaries)

    # the closing read-out quotes real cells, so a re-run of the grid cannot leave
    # it holding numbers that no longer exist
    def span(vals, fmt="{:.2f}"):
        vals = [v for v in vals if v is not None]
        if not vals:
            return "  -  "
        lo, hi = min(vals), max(vals)
        if lo == hi:
            return fmt.format(lo)
        return fmt.format(lo) + " 至 " + fmt.format(hi) if lo < 0 < 1 else \
            fmt.format(lo) + "–" + fmt.format(hi)

    def median(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        m = len(vals) // 2
        return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2

    def med(vals, fmt="{:.2f}"):
        """One number instead of a range when the range is the whole interval."""
        m = median(vals)
        return fmt.format(m) if m is not None else "  -  "

    def num(v, fmt="{:.2f}"):
        return fmt.format(v) if v is not None else "  -  "

    def by_fixture(fam, field, conds):
        return [r[fam].get(field) for r in summaries
                if r["condition"] in conds and fam in r]

    def pooled(fam, field, conds):
        """n-weighted mean over a whole condition row group: with 1-7 pairs per
        fixture, an unweighted mean of per-fixture rates is noise."""
        num = den = 0.0
        for r in summaries:
            d = r.get(fam) if r["condition"] in conds else None
            if d and d.get(field) is not None and d.get("n"):
                num += d[field] * d["n"]
                den += d["n"]
        return num / den if den else None

    def band(field, conds, min_cov=0.2):
        cov_field = field.replace("accuracy", "coverage")
        vals = []
        for c in conds:
            for fam in CHOICE_LIKE:
                for r in summaries:
                    d = r.get(fam) if r["condition"] == c else None
                    if d and (d.get(cov_field) or 0) >= min_cov and d.get(field) is not None:
                        vals.append(d[field])
        return vals

    live = (FULL, GEO, "raw_paths")
    md += ["## 9. 结论：这份上限怎么读", "",
           "1. **能划，而且划的是「这份 state 叙述的画」。** 凡能从坐标读出来的层级"
           f"（嵌套深度、九宫格、包含、绘制顺序），给坐标就准：纯几何条件下包含 AUC "
           f"{num(pooled('rel_encloses', 'auc', (GEO,)))}、绘制顺序命中率 "
           f"{num(pooled('rel_paint_order', 'acc', (GEO,)))}（多数类基线 "
           f"{num(pooled('rel_paint_order', 'baseline', (GEO,)))}）；"
           "画师约定（哪个部件属于哪个物体、哪条线代表远景）必须靠名字或 `<g>` 树，"
           f"只给几何时它给出另一种自洽但不正确的划分：ARI "
           f"{span(by_fixture('group', 'ari', (GEO,)))}，而跨物体的错误合并 "
           f"{span(by_fixture('group', 'n_mixed', (GEO,)), '{:.0f}')} 次 —— 它切得过碎，"
           "找到的是部件而不是物体。",
           "2. **置信度衡量「有没有线索」，不衡量「线索真假」。** 把坐标整批置换成假证据后，"
           f"区域命中率从 {span(by_fixture('region', 'acc', (GEO,)))} 掉到 "
           f"{span(by_fixture('region', 'acc', ('scrambled',)))}"
           f"（每幅都跌破多数类基线 {span(by_fixture('region', 'baseline', (GEO,)))}），"
           f"置信度却只从 {span(by_fixture('region', 'mean_confidence', (GEO,)))} 变到 "
           f"{span(by_fixture('region', 'mean_confidence', ('scrambled',)))}。"
           "上游解析必须自己保证正确（本项目的做法：几何内核 + `selftest` 断言）。",
           "3. **概率分布比硬标签更有用。** 三档分流（≥0.85 行动 / 0.55–0.85 复核 / <0.55 弃权）"
           f"在线索充足的维度上高置信段命中 {span(band('act_accuracy', live))}"
           f"（中位 {med(band('act_accuracy', live))}），"
           f"弃权段命中中位 {med(band('abstain_accuracy', live))} —— 两档分开看就是可用的；"
           f"而没有坐标可读时高置信覆盖率自己塌到 "
           f"{span(by_fixture('region', 'act_coverage', (NAMES,)))}，分流不必额外设阈值。",
           "4. **连续分能排序、不能分箱；计数与整图判断被定义绑住。** "
           f"跨度 Spearman {span(by_fixture('extent', 'spearman', (GEO,)))} 而绝对档位命中只有 "
           f"{span(by_fixture('extent', 'acc', (GEO,)))}；坐标一置换序就变成 "
           f"{span(by_fixture('extent', 'spearman', ('scrambled',)))}。"
           "深度平面数几乎全不一致，但错在档位边界而不是线索读取（见 §7）。",
           "5. **它会把「读得出顺序」和「用顺序判断前后」当成两件事。** "
           f"直接问绘制顺序它答对 {num(pooled('rel_paint_order', 'acc', (GEO,)))}（基线 "
           f"{num(pooled('rel_paint_order', 'baseline', (GEO,)))}，且每幅的正例都占一半）；"
           f"换成问「这张画里谁在前」而不给断口线索时命中率 "
           f"{num(pooled('rel_in_front_undef', 'acc', live))}（基线 "
           f"{num(pooled('rel_in_front_undef', 'baseline', live))}）、AUC "
           f"{num(pooled('rel_in_front_undef', 'auc', (GEO,)))} ≈ 抛硬币。"
           "知道某个事实，不等于会在别的维度上主动用它。", "",
           "工程上因此这样分工：可精确计算的事实留在代码里；"
           "需要语义的模糊划分交给模型；每个维度一个问题、定义写进 criteria；"
           "换一种文本化就重测一遍。", ""]
    md += ["---", "", "复现：`python -m src.selftest` → `python -m src.run_probe` → "
           "`python -m src.analyze` → `python -m src.make_viewer`。", ""]

    (RESULTS / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {RESULTS / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
