"""Write results/traces/report.md from results/traces/summary.json.

Every number in the prose is read out of the summary, so the text cannot drift
away from the run the way a hand-typed table does. Same reading discipline as
round 1: a rate means nothing before its baseline, and a partition metric means
nothing before the number of classes it had to find.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "traces"

FIXTURES = ("trace_stick", "trace_house_interleaved", "trace_cat_decor")
CONDS = ("order_named", "order_list", "times_only", "order_none", "order_scrambled")
CON_SHORT = {"order_named": "名字+顺序", "order_list": "只有顺序",
             "times_only": "只有时间戳", "order_none": "什么都没给",
             "order_scrambled": "假痕迹"}
CHOICE = ("part", "layer", "region", "motion")
PAIR = ("p_same_part", "p_same_motion", "p_adjacent", "p_after")
CNT = "{:.0f}"
# the deltas that decompose the part row: what the name buys, what the trace
# buys once the name is gone, whether the trace has to be *written* in the list
# order, and what a false trace costs
NAMES = ("order_named", "order_list")
TRACE = ("order_list", "order_none")
TIMES = ("times_only", "order_none")
FAKE = ("order_scrambled", "order_none")

# what each drawing is there to make hard
CHALLENGE = {
    "trace_stick": "按部位顺序画：一个部位的几笔连着画完才换下一个，痕迹与部件基本重合",
    "trace_house_interleaved": "打乱着画：栅栏三根柱子被门、屋顶、窗的活儿隔开，瓦片夹在窗之间",
    "trace_cat_decor": "装饰陷阱：五根一模一样的开曲线，有的算毛有的算胡须，笔顺里还交替出现",
}
TILES = {"trace_stick": 10, "trace_house_interleaved": 7, "trace_cat_decor": 6}


def load() -> list[dict[str, Any]]:
    return json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# reading the summary: one place decides what a missing value looks like
# --------------------------------------------------------------------------- #

def values(rows: list[dict[str, Any]], fam: str, field: str,
           conds: tuple[str, ...] = CONDS, fixtures: tuple[str, ...] = FIXTURES,
           comp: str | None = None) -> list[float]:
    """`comp` picks one of the code comparators, which are nested one level
    deeper than the Jev families."""
    out: list[float] = []
    for r in rows:
        if r["condition"] not in conds or r["fixture"] not in fixtures:
            continue
        node = r.get("comparators", {}).get(comp, {}) if comp else r.get(fam, {})
        v = node.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    return out


def avg(rows: list[dict[str, Any]], fam: str, field: str, cond: str | None = None,
        fixtures: tuple[str, ...] = FIXTURES, comp: str | None = None) -> float | None:
    got = values(rows, fam, field, (cond,) if cond else CONDS, fixtures, comp)
    return round(statistics.fmean(got), 3) if got else None


def single(rows: list[dict[str, Any]], fixture: str, cond: str,
           fam: str, field: str, comp: str | None = None) -> float | None:
    got = values(rows, fam, field, (cond,), (fixture,), comp)
    return round(got[0], 3) if got else None


def s(rows: list[dict[str, Any]], fam: str, field: str, cond: str | None = None,
      fixtures: tuple[str, ...] = FIXTURES, comp: str | None = None,
      fmt: str = "{:.3f}") -> str:
    v = avg(rows, fam, field, cond, fixtures, comp)
    return fmt.format(v) if v is not None else "  -  "


def q(rows: list[dict[str, Any]], fixture: str, cond: str, fam: str, field: str,
      comp: str | None = None, fmt: str = "{:.3f}") -> str:
    v = single(rows, fixture, cond, fam, field, comp)
    return fmt.format(v) if v is not None else "  -  "


def d(rows: list[dict[str, Any]], fixture: str, fam: str, field: str,
      pair: tuple[str, str], fmt: str = "{:+.3f}") -> str:
    a = single(rows, fixture, pair[0], fam, field)
    b = single(rows, fixture, pair[1], fam, field)
    return fmt.format(a - b) if a is not None and b is not None else "  -  "


def mean_dev(rows: list[dict[str, Any]], fam: str, field: str,
             pair: tuple[str, str]) -> str:
    a = [v for v in (single(rows, f, pair[0], fam, field) for f in FIXTURES) if v is not None]
    b = [v for v in (single(rows, f, pair[1], fam, field) for f in FIXTURES) if v is not None]
    if not a or not b:
        return "  -  "
    return "{:+.3f}".format(statistics.fmean(a) - statistics.fmean(b))


def between(rows: list[dict[str, Any]], fam: str, a_field: str, b_field: str,
            cond: str | None = None, fmt: str = "{:.3f}") -> str:
    """Two fields of the same family under the same condition, subtracted —
    a rate minus its own baseline is the only honest way to read a skewed one."""
    a = avg(rows, fam, a_field, cond)
    b = avg(rows, fam, b_field, cond)
    return fmt.format(a - b) if a is not None and b is not None else "  -  "


def cell(rows: list[dict[str, Any]], fam: str, cond: str, field: str,
         fmt: str = "{:.3f}") -> str:
    """Averaged over the three fixtures — the column of an overview table."""
    v = avg(rows, fam, field, cond, comp=fam if fam.startswith(("geom_", "pen_run_")) else None)
    return fmt.format(v) if v is not None else "  -  "


def table(rows: list[dict[str, Any]], fams: tuple[str, ...], field: str,
          title: str, note: str = "") -> list[str]:
    out = [f"**{title}**{('：' + note) if note else ''}", ""]
    out.append("| 维度 | " + " | ".join(CON_SHORT[c] for c in CONDS) + " |")
    out.append("|---" * (len(CONDS) + 1) + "|")
    for fam in fams:
        if not any(fam in r for r in rows):
            continue
        out.append(f"| `{fam}` | " + " | ".join(cell(rows, fam, c, field) for c in CONDS) + " |")
    out.append("")
    return out


def fixture_table(rows: list[dict[str, Any]], fam: str, field: str,
                  title: str, fmt: str = "{:.3f}", comp: str | None = None) -> list[str]:
    out = [f"**{title}**", ""]
    out.append("| 画 | " + " | ".join(CON_SHORT[c] for c in CONDS) + " |")
    out.append("|---" * (len(CONDS) + 1) + "|")
    for f in FIXTURES:
        out.append(f"| `{f}` | "
                   + " | ".join(q(rows, f, c, fam, field, comp, fmt) for c in CONDS) + " |")
    out.append("")
    return out


def gestalt_items(rows: list[dict[str, Any]], cond: str, key: str) -> list[dict[str, Any]]:
    return [i for r in rows if r["condition"] == cond
            for i in r["gestalt"]["items"] if i["q"] == key]


def main() -> int:
    rows = load()
    model = rows[0].get("model") or "?"
    tot_q = sum(r["n_questions"] for r in rows)
    tot_in = sum(r["input_tokens"] for r in rows)
    tot_out = sum(r["output_tokens"] for r in rows)
    cost = tot_in / 1e9 * 42.0
    api = sum(r.get("api_seconds", 0.0) for r in rows)
    strokes = {f: next(r["n_elements"] for r in rows if r["fixture"] == f) for f in FIXTURES}

    def span(fam: str, field: str, cond: str = "order_named") -> str:
        got = [v for v in (single(rows, f, cond, fam, field) for f in FIXTURES) if v is not None]
        return f"{min(got):.0f}–{max(got):.0f}" if got else "  -  "

    md: list[str] = [
        "# 第二轮：把绘画痕迹喂给 Jev，能换回多少分层与部件划分",
        "",
        f"模型 `{model}`；{len(rows)} 个「画 × 痕迹条件」组合，判定 {tot_q:,} 条，"
        f"输入 {tot_in:,} tokens、输出 {tot_out:,} tokens（输出不计费），"
        f"按 \\$42/Btok（=\\$0.042/Mtok）整个网格约 **\\${cost:.3f}**，"
        f"即一幅 22 笔的画做完一整套判定约 \\${cost / len(rows):.4f}；"
        f"服务端累计 {api:.0f}s。",
        "",
        "问题问的是机器重绘 / live2d 真正要的四件事：**部件归属**（这条线属于哪个部件）、"
        "**层级角色**（它是主体、细节、装饰、背景还是辅助线）、**区域划分**"
        "（画布被切成几块，这条线主要落在哪块）、**运动归属**（动画时谁带着它走），"
        "外加一条 Noul：**这根开口的线是不是可以随时挪走装饰**。成对题问两条线"
        "是否同部件、是否同运动件、是否连笔、谁先谁后。",
        "",
        "第一轮消融的是几何怎么写，那一轮的混淆项（`<g>` 分组树）这轮拿掉了："
        "三幅新画全都只有一层 `<g>` 用来统一描边样式，文件里没有任何部件层级可抄。"
        "这一轮消融的是**这幅画是怎么被画出来的这件事怎么写**。",
        "",
        "---",
        "",
        "## 0. 五种痕迹条件与三幅画的挑战",
        "",
        "| 条件 | state 里有什么 | 想分开的是什么 |",
        "|---|---|---|",
        "| `order_named` | 数组顺序 = 笔迹顺序 + `trace_ms` + 元素 id 就是笔画名 | 名字与痕迹同时给（上界） |",
        "| `order_list` | 数组顺序 = 笔迹顺序 + `trace_ms`，id 换成 `s01…` | 只剩痕迹，名字拿掉 |",
        "| `times_only` | 顺序是位置排序（与笔迹无关），`trace_ms` 是真时间；"
        "note 明说顺序要自己按数字比 | 顺序不写在数组位置上，要它自己算 |",
        "| `order_none` | 没有 `trace_ms`，note 明说这里没有绘画顺序 | 什么痕迹都不给 |",
        "| `order_scrambled` | 数组顺序与时间戳都是**假的**但自洽，note 一样叫它信 | "
        "假证据（false-evidence 控制组） |",
        "",
        "三幅画各带一个难点，正是要求的「非闭合装饰线」和打乱顺序：",
        "",
        "| 画 | 笔画数 | 挑战 |",
        "|---|---|---|",
    ]
    for f in FIXTURES:
        md.append(f"| `{f}` | {strokes[f]} | {CHALLENGE[f]} |")
    md += ["",
           "区域真值不是标出来的，是代码按**每幅画自己的分块**算的：把每条线沿弧长每 1 点"
           "采一次样，看哪一块拿走了一半以上的长度，拿不走就是 `spans-several`。"
           "分块的矩形连同名字一起写进 state（`state.tiles`），"
           "所以它做的是一个有定义的空间划分，不是猜九宫格。",
           "",
           "两个代码基线跟着每一格一起算，命中率要对着它们读：",
           "",
           "- `geom`：闭合轮廓包含 + 6 点邻近兜底 + 一张手写的「轮廓→部件」表；",
           "- `pen_run`：连贯性赌注——笔落点走超过 25 点就断成新一段，段内继承第一个能放下的部件名。",
           "",
           "---",
           "",
           "## 1. 一眼总览",
           ""]
    md += table(rows, CHOICE, "acc", "逐元素命中率", "三幅平均；单幅见 §2")
    md += table(rows, CHOICE, "baseline", "多数类基线（恒定答最常见的那一类）")
    md += table(rows, CHOICE, "macro_f1", "宏 F1")
    md += table(rows, CHOICE, "f1_baseline", "恒定回答的宏 F1 基线")
    md += table(rows, CHOICE, "mean_confidence", "平均置信度")
    md += table(rows, CHOICE, "act_coverage", "高置信（≥0.85）覆盖率")
    md += table(rows, PAIR, "acc", "成对题命中率")
    md += [
        "读法：`region` 一行几乎不动，因为它只吃坐标，与痕迹无关——这一行是这次实验的"
        "内对照，说明五个条件真的只动了痕迹这一件事。"
        "`part` 一行在 `order_named` 上三幅全对，是这次最强的一格；"
        "但同一行在 `order_list` 上就掉，说明那一格是**名字与痕迹同时给**才拿到的。",
        "",
        "---",
        "",
        "## 2. 部件归属：名字才是主因，痕迹只补一小块",
        "",
        "先把 1.000 那一格拆开。每幅画部件类数不同，所以逐幅看命中率：",
        "",
        *fixture_table(rows, "part", "acc", "`part` 命中率"),
        *fixture_table(rows, "part", "baseline", "`part` 多数类基线"),
        "",
        f"- **名字值多少**（`order_named` 对 `order_list`，两者都有真笔迹，只差 id 是不是笔画名）："
        f"三幅各 {d(rows, 'trace_stick', 'part', 'acc', NAMES)}、"
        f"{d(rows, 'trace_house_interleaved', 'part', 'acc', NAMES)}、"
        f"{d(rows, 'trace_cat_decor', 'part', 'acc', NAMES)}。"
        f"平均从 {s(rows, 'part', 'acc', 'order_named')} 掉到 {s(rows, 'part', 'acc', 'order_list')}。",
        f"- 名字+顺序同时给时三幅全对（宏 F1 {s(rows, 'part', 'macro_f1', 'order_named')}）。"
        f"部件是 {span('part', 'n_parts_truth')} 类的问题，"
        f"多数类基线只有 {q(rows, 'trace_stick', 'order_named', 'part', 'baseline')}/"
        f"{q(rows, 'trace_house_interleaved', 'order_named', 'part', 'baseline')}/"
        f"{q(rows, 'trace_cat_decor', 'order_named', 'part', 'baseline')}，不是撞对的。",
        f"- **痕迹值多少**（`order_list` 对 `order_none`，两者都没名字，只差有没有笔迹）："
        f"火柴人 {d(rows, 'trace_stick', 'part', 'acc', TRACE)}、"
        f"房子 {d(rows, 'trace_house_interleaved', 'part', 'acc', TRACE)}、"
        f"猫 {d(rows, 'trace_cat_decor', 'part', 'acc', TRACE)}，"
        f"三幅平均 {mean_dev(rows, 'part', 'acc', TRACE)}"
        f"（{s(rows, 'part', 'acc', 'order_list')} 对 {s(rows, 'part', 'acc', 'order_none')}）。"
        "**顺序写在数组位置上、时间戳是真的，这些加起来值不到一笔。**",
        f"- 顺序不写在数组位置上、只留一串真时间戳（`times_only`）平均 "
        f"{s(rows, 'part', 'acc', 'times_only')}，与 `order_none` 的 "
        f"{s(rows, 'part', 'acc', 'order_none')} 同样几乎无差："
        f"逐幅 {d(rows, 'trace_stick', 'part', 'acc', TIMES)}、"
        f"{d(rows, 'trace_house_interleaved', 'part', 'acc', TIMES)}、"
        f"{d(rows, 'trace_cat_decor', 'part', 'acc', TIMES)}。"
        "要它自己从数字里把顺序算出来，算得出来（§7 的 p_after），"
        "但算出来的顺序并没有换成更好的部件划分。",
        f"- **假痕迹是负资产**（`order_scrambled` 对 `order_none`）："
        f"火柴人 {d(rows, 'trace_stick', 'part', 'acc', FAKE)}，是正的——"
        f"那幅画本来就是一个部位连着画完，"
        f"任意一套自洽的假顺序里同一部位的笔画多半仍然挨在一起；"
        f"猫 {d(rows, 'trace_cat_decor', 'part', 'acc', FAKE)}（打平）；"
        f"而打乱那幅房子 {d(rows, 'trace_house_interleaved', 'part', 'acc', FAKE)}，"
        f"从 {q(rows, 'trace_house_interleaved', 'order_none', 'part', 'acc')} 掉到 "
        f"{q(rows, 'trace_house_interleaved', 'order_scrambled', 'part', 'acc')}。"
        f"而假痕迹那格的置信度并没有一起掉：整体平均 "
        f"{s(rows, 'part', 'mean_confidence', 'order_scrambled')}，"
        f"**答错时平均仍有 {s(rows, 'part', 'conf_on_wrong', 'order_scrambled')}**，"
        f"比什么都没给时答错的 {s(rows, 'part', 'conf_on_wrong', 'order_none')} 还高一点。",
        "",
        "### 2.1 划分质量：ARI 会骗人，NMI 不会",
        "",
        "把每个部件的软分布折成 P(同部件)=Σ p_a·p_b，再单链接聚到 0.5，与真值划分比：",
        "",
        *fixture_table(rows, "part", "ari", "`part` 软划分的 ARI"),
        *fixture_table(rows, "part", "nmi", "`part` 软划分的 NMI"),
        *fixture_table(rows, "part", "n_clusters_pred", "聚出的簇数", CNT),
        *fixture_table(rows, "part", "n_parts_truth", "真值部件数", CNT),
        "",
        f"`order_named` 三幅 ARI 全 "
        f"{q(rows, 'trace_stick', 'order_named', 'part', 'ari')}/"
        f"{q(rows, 'trace_house_interleaved', 'order_named', 'part', 'ari')}/"
        f"{q(rows, 'trace_cat_decor', 'order_named', 'part', 'ari')}，"
        f"簇数 "
        f"{q(rows, 'trace_stick', 'order_named', 'part', 'n_clusters_pred', fmt=CNT)}/"
        f"{q(rows, 'trace_house_interleaved', 'order_named', 'part', 'n_clusters_pred', fmt=CNT)}/"
        f"{q(rows, 'trace_cat_decor', 'order_named', 'part', 'n_clusters_pred', fmt=CNT)} 与真值一致，"
        f"混簇数 "
        f"{q(rows, 'trace_stick', 'order_named', 'part', 'n_mixed', fmt=CNT)}/"
        f"{q(rows, 'trace_house_interleaved', 'order_named', 'part', 'n_mixed', fmt=CNT)}/"
        f"{q(rows, 'trace_cat_decor', 'order_named', 'part', 'n_mixed', fmt=CNT)} —— "
        "这就是「把名字和笔迹一起给它，划分可以直接落库」的意思。",
        "",
        "但另几列要小读：`order_list` 在房子那幅 ARI 只有 "
        f"{q(rows, 'trace_house_interleaved', 'order_list', 'part', 'ari')}，"
        f"NMI 还有 {q(rows, 'trace_house_interleaved', 'order_list', 'part', 'nmi')}，"
        f"簇数却是 {q(rows, 'trace_house_interleaved', 'order_list', 'part', 'n_clusters_pred', fmt=CNT)}"
        f"（{strokes['trace_house_interleaved']} 笔里几乎一笔一簇）。"
        "**这不是聚错了，是不敢聚**：top-1 已经有 "
        f"{q(rows, 'trace_house_interleaved', 'order_list', 'part', 'acc')} 对，"
        "但质量摊得开，Σ p_a·p_b 过不了 0.5 的合并门槛。所以 ARI 在这里同时度量了「对不对」和"
        "「分布尖不尖」，读它必须连着簇数一起读。",
        "",
        "### 2.2 对着代码基线读",
        "",
        "两条规则只吃几何和自己的分段逻辑，与痕迹条件无关，所以按画列一次就够：",
        "",
        "| 画 | Jev `part`（名字+顺序） | Jev `part`（只有顺序） | 包含规则 `geom` | 连贯规则 `pen_run` | 多数类 |",
        "|---|---|---|---|---|---|",
    ]
    for f in FIXTURES:
        md.append(f"| `{f}` | {q(rows, f, 'order_named', 'part', 'acc')} | "
                  f"{q(rows, f, 'order_list', 'part', 'acc')} | "
                  f"{q(rows, f, 'order_named', '', 'acc', 'geom_part')} | "
                  f"{q(rows, f, 'order_named', '', 'acc', 'pen_run_part')} | "
                  f"{q(rows, f, 'order_named', 'part', 'baseline')} |")
    geom_mean = avg(rows, "", "acc", comp="geom_part")
    pen_mean = avg(rows, "", "acc", comp="pen_run_part")
    part_bl = avg(rows, "part", "baseline")
    md += ["",
           f"三幅平均：包含规则 {geom_mean:.3f}，连贯规则 {pen_mean:.3f}，"
           f"比多数类基线 {part_bl:.3f} 只高出 "
           f"{geom_mean - part_bl:.3f} 和 {pen_mean - part_bl:.3f}。"
           "也就是说这次不是「模型比规则强一点点」，而是规则根本没有把开口装饰线放对的能力："
           "火柴人那幅包含规则 "
           f"{q(rows, 'trace_stick', 'order_named', '', 'acc', 'geom_part')}，因为 "
           f"{q(rows, 'trace_stick', 'order_named', '', 'n_none', 'geom_part', '{:.0f}')}/"
           f"{strokes['trace_stick']} 笔它答不出来（没有轮廓可依托）；"
           "打乱那幅房子反而有 "
           f"{q(rows, 'trace_house_interleaved', 'order_named', '', 'acc', 'geom_part')}，"
           "因为它的部件本来就靠「在不在屋顶里、在不在门里」区分。",
           "",
           f"顺带一个反直觉的数字：笔迹走位距离当「同部件」判据其实相当好——三幅的 AUC "
           f"{min(r['pen_travel']['auc'] for r in rows):.3f}–"
           f"{max(r['pen_travel']['auc'] for r in rows):.3f}"
           f"（同段中位 {statistics.median([r['pen_travel']['median_same'] for r in rows]):.1f} 点，"
           f"跨段中位 {statistics.median([r['pen_travel']['median_diff'] for r in rows]):.1f} 点）。"
           "可 `pen_run` 就是拿不准：一个部件只有一笔时**也需要名字**，"
           "而连贯规则只会把没有轮廓可依托的线并进上一笔的名字里；"
           "同时没有任何单一阈值能把同段/跨段分开（中位 "
           f"{statistics.median([r['pen_travel']['median_same'] for r in rows]):.0f} 对 "
           f"{statistics.median([r['pen_travel']['median_diff'] for r in rows]):.0f}，"
           "但分布重叠，25 这个数是这组数据上的折中）。",
           "",
           "---",
           "",
           "## 3. 区域划分：与痕迹无关，而且给矩形就能算",
           "",
           *fixture_table(rows, "region", "acc", "`region` 命中率"),
           *fixture_table(rows, "region", "macro_f1", "`region` 宏 F1"),
           "",
           f"区域块是每幅画自己切的（"
           f"{TILES['trace_stick']} 块 / {TILES['trace_house_interleaved']} 块 / "
           f"{TILES['trace_cat_decor']} 块，都是长条+主体密区），"
           f"真值由代码按弧长采样算。五个条件的差别在噪声内："
           f"`order_named` {s(rows, 'region', 'acc', 'order_named')} 对 "
           f"`order_none` {s(rows, 'region', 'acc', 'order_none')} 对 "
           f"`order_scrambled` {s(rows, 'region', 'acc', 'order_scrambled')}，"
           f"多数类基线 {s(rows, 'region', 'baseline')}。"
           "这说明它做的是**「沿弧长比多少」这类空间判断**，不需要语义也能做，"
           "顺序被造假也不影响它。"
           "反过来，第一轮里 `scrambled` 把区域打到 0.00–0.22，这一轮假的是**顺序**不是坐标，"
           "区域一行自然不动——这正好是这次消融设计的自检。",
           "",
           "---",
           "",
           "## 4. 层级角色：最弱的一维，而且最吃名字",
           "",
           *fixture_table(rows, "layer", "acc", "`layer` 命中率"),
           *fixture_table(rows, "layer", "baseline", "`layer` 多数类基线"),
           *fixture_table(rows, "layer", "act_coverage", "`layer` 高置信覆盖率"),
           "",
           f"五档角色（backdrop/body/detail/decor/guide）平均命中从 "
           f"{s(rows, 'layer', 'acc', 'order_named')}（`order_named`）到 "
           f"{s(rows, 'layer', 'acc', 'order_list')}（`order_list`），"
           f"是四个 Choice 维度里最低的一族，基线 {s(rows, 'layer', 'baseline')}——"
           f"最好那格也只比基线高 {between(rows, 'layer', 'acc', 'baseline', 'order_named')}。"
           "它也是最吃名字的一维："
           f"猫那幅从 {q(rows, 'trace_cat_decor', 'order_named', 'layer', 'acc')} 掉到 "
           f"{q(rows, 'trace_cat_decor', 'order_list', 'layer', 'acc')}，"
           f"高置信覆盖率同时从 {q(rows, 'trace_cat_decor', 'order_named', 'layer', 'act_coverage')} "
           f"塌到 {q(rows, 'trace_cat_decor', 'order_list', 'layer', 'act_coverage')}；"
           "全三幅的覆盖率则从 "
           f"{s(rows, 'layer', 'act_coverage', 'order_named')} 到 "
           f"{s(rows, 'layer', 'act_coverage', 'order_list')}。"
           "**覆盖率跟着掉是好消息**：这一维它知道自己没依据。",
           "",
           "失误集中在 `decor` 与 `detail` 之间：瓦片、裂纹、衣褶、胡须都算"
           "「开口的小线」，作者一边归为装饰、一边归为细节。"
           "这两档在真实管线里本来就是同一个动作（要不要单独一层），"
           "所以工程上更稳的做法是**只问「这条线能不能单独一层」，别问它属于五档里的哪一档**——"
           "也就是下面第 5 节那条 Noul。",
           "",
           "---",
           "",
           "## 5. 装饰性非闭合线：一条能用的分流",
           "",
           "用户点名的挑战就是这种线：五根一样的毛、瓦片、烟、草。"
           "问法是给出一句断言让它估概率（Noul）：「这是一根为了好看而画的开口线，"
           "单独重画成一个小浮动层不会伤到主体结构」。",
           "",
           "| 条件 | 命中率 | 常数答基线 | recall | precision | AUC | 真为正的均值 | 真为负的均值 |",
           "|---|---|---|---|---|---|---|---|",
    ]
    for c in CONDS:
        md.append(f"| {CON_SHORT[c]} | {cell(rows, 'loose_decor', c, 'acc')} | "
                  f"{cell(rows, 'loose_decor', c, 'baseline')} | "
                  f"{cell(rows, 'loose_decor', c, 'recall')} | "
                  f"{cell(rows, 'loose_decor', c, 'precision')} | "
                  f"{cell(rows, 'loose_decor', c, 'auc')} | "
                  f"{cell(rows, 'loose_decor', c, 'mean_noul_pos')} | "
                  f"{cell(rows, 'loose_decor', c, 'mean_noul_neg')} |")
    n_decor = sum(single(rows, f, "order_named", "loose_decor", "positives") or 0
                  for f in FIXTURES)
    md += ["",
           f"三幅一共 {n_decor:.0f} 根开口装饰线（真值），共 "
           f"{sum(strokes.values()):.0f} 笔，`order_named` 条件下"
           f"recall {s(rows, 'loose_decor', 'recall', 'order_named')}、"
           f"AUC {s(rows, 'loose_decor', 'auc', 'order_named')}，"
           f"真为正的均值 {s(rows, 'loose_decor', 'mean_noul_pos', 'order_named')} 对"
           f"真为负的均值 {s(rows, 'loose_decor', 'mean_noul_neg', 'order_named')} —— 分隔很开。"
           f"逐幅 recall {q(rows, 'trace_stick', 'order_named', 'loose_decor', 'recall')}/"
           f"{q(rows, 'trace_house_interleaved', 'order_named', 'loose_decor', 'recall')}/"
           f"{q(rows, 'trace_cat_decor', 'order_named', 'loose_decor', 'recall')}，"
           f"precision {q(rows, 'trace_stick', 'order_named', 'loose_decor', 'precision')}/"
           f"{q(rows, 'trace_house_interleaved', 'order_named', 'loose_decor', 'precision')}/"
           f"{q(rows, 'trace_cat_decor', 'order_named', 'loose_decor', 'precision')}。",
           "",
           f"命中率之所以看着只比常数答（{s(rows, 'loose_decor', 'baseline', 'order_named')}）高 "
           f"{between(rows, 'loose_decor', 'acc', 'baseline', 'order_named')}，"
           "是因为真值本身就偏（多数线确实不是装饰），"
           "**这条题该看 recall 和 AUC，不该看命中率**。",
           "",
           "把 `order_named` 下 noul≥0.5 而真值为负的笔画列出来，误报长这样：",
           "",
           "| 画 | 误报（noul） | 真漏报 |",
           "|---|---|---|",
    ]
    for f in FIXTURES:
        raw = json.loads((RESULTS / "raw" / f"{f}__order_named.json").read_text(encoding="utf-8"))
        fp, fn = [], []
        for k, v in raw["answers"].items():
            if not k.startswith("loose_decor::"):
                continue
            eid = k.split("::", 1)[1]
            noul, t = v["noul"], bool(raw["truth"][eid]["loose_decor"])
            hit = f"`{eid}` {noul:.2f}"
            if t and noul < 0.5:
                fn.append(hit)
            elif not t and noul >= 0.5:
                fp.append(hit)
        md.append(f"| `{f}` | {'、'.join(fp) or '无'} | {'、'.join(fn) or '无'} |")
    md += ["",
           "误报分两种，工程后果不一样。`shirt-fold`、`wall-crack`、`fly-body` 这种"
           "「本来就是一根开口的小线」被说成可单独一层，按 live2d 的做法反而对——"
           "衣褶和墙裂本来就该跟自己的部件走一个浮动层。"
           "但 `fence-post-1..3` 加 `fence-rail` 四笔全被点名，就是真错了："
           "栅栏是承重的结构件，拔掉它画面就少一个东西。"
           "`ear-l` 0.54 这种更值得警惕：分数刚过线、东西却是主体的耳朵。"
           "`guide-axis`（辅助线）和 `ground-line`（地平线）被判成正例，是它比作者更对——"
           "辅助线本来就不该进重绘结果，地面线本来就该单独一层。"
           "所以结论是：**这条 Noul 能当筛选器（分数排序 + 卡阈值）用，"
           "阈值以下一定能安全删，阈值附近必须再过一遍部件归属——"
           "一根线「开口」不等于它「不重要」。**",
           "",
           "---",
           "",
           "## 6. 运动归属（rigging）",
           "",
           *fixture_table(rows, "motion", "acc", "`motion` 命中率"),
           *fixture_table(rows, "motion", "baseline", "`motion` 多数类基线"),
           *fixture_table(rows, "motion", "ari", "`motion` 软划分 ARI"),
           "",
           f"平均 {s(rows, 'motion', 'acc', 'order_named')}（`order_named`）对 "
           f"{s(rows, 'motion', 'acc', 'order_none')}（`order_none`），基线 "
           f"{s(rows, 'motion', 'baseline')}。"
           f"运动件比部件少（部件 {span('part', 'n_parts_truth')} 类，"
           f"运动 {span('motion', 'n_parts_truth')} 件），"
           "所以这一维更像一个粗一格的划分，"
           f"高置信覆盖率在 `order_named` 下有 {s(rows, 'motion', 'act_coverage', 'order_named')}，"
           f"`order_list` 下塌到 {s(rows, 'motion', 'act_coverage', 'order_list')}。",
           "",
           "这一维是三幅里最不稳的，两个方向都要报："
           "房子那幅没有名字时（`order_list` "
           f"{q(rows, 'trace_house_interleaved', 'order_list', 'motion', 'acc')}）"
           f"**正好落在自己的多数类基线上（{q(rows, 'trace_house_interleaved', 'order_list', 'motion', 'baseline')}）**"
           "——不比「恒定答最常见的那个运动件」多知道任何事；同一幅给名字有 "
           f"{q(rows, 'trace_house_interleaved', 'order_named', 'motion', 'acc')}，"
           f"给假顺序只有 {q(rows, 'trace_house_interleaved', 'order_scrambled', 'motion', 'acc')}，"
           f"连 {q(rows, 'trace_house_interleaved', 'order_none', 'motion', 'acc')}（什么都不给）都不如。"
           "但反过来，火柴人那幅 `order_named` 只有 "
           f"{q(rows, 'trace_stick', 'order_named', 'motion', 'acc')}，"
           f"低于它自己 `order_none` 的 {q(rows, 'trace_stick', 'order_none', 'motion', 'acc')}——"
           f"{strokes['trace_stick']} 笔里两笔的差别。"
           "**所以运动归属只读方向（有名字 > 没名字，假顺序 < 没顺序），不读幅度。**",
           "",
           "---",
           "",
           "## 7. 成对题：读得出顺序，和会用顺序，还是两件事",
           "",
           "每一对都问四个 Noul，方向题按镜像配平（同一对正反各问一次），"
           "所以命中率高于 0.5 才不是猜方向：",
           "",
           "| 题 | " + " | ".join(CON_SHORT[c] for c in CONDS) + " | 基线 | 正例数（三幅平均） |",
           "|---" * (len(CONDS) + 3) + "|",
    ]
    for fam in PAIR:
        md.append(f"| `{fam}` | " + " | ".join(cell(rows, fam, c, "acc") for c in CONDS)
                  + f" | {cell(rows, fam, 'order_named', 'baseline')} | "
                    f"{cell(rows, fam, 'order_named', 'positives', '{:.0f}')} |")
    md += ["",
           f"- **谁先谁后**：数组顺序真是笔迹时 "
           f"{s(rows, 'p_after', 'acc', 'order_named')}；"
           f"换成只有时间戳（note 已明说顺序要自己比数字）仍有 "
           f"{s(rows, 'p_after', 'acc', 'times_only')}，"
           f"三幅分别 {q(rows, 'trace_stick', 'times_only', 'p_after', 'acc')}/"
           f"{q(rows, 'trace_house_interleaved', 'times_only', 'p_after', 'acc')}/"
           f"{q(rows, 'trace_cat_decor', 'times_only', 'p_after', 'acc')} —— 会读时间。"
           f"但平均绝对信心一起掉：偏离 0.5 的程度从 "
           f"{s(rows, 'p_after', 'mean_dev_from_half', 'order_named')} 降到 "
           f"{s(rows, 'p_after', 'mean_dev_from_half', 'times_only')}。",
           f"- **是不是连笔**：同一个时间戳条件下只有 "
           f"{s(rows, 'p_adjacent', 'acc', 'times_only')}，"
           f"三幅 {q(rows, 'trace_stick', 'times_only', 'p_adjacent', 'acc')}/"
           f"{q(rows, 'trace_house_interleaved', 'times_only', 'p_adjacent', 'acc')}/"
           f"{q(rows, 'trace_cat_decor', 'times_only', 'p_adjacent', 'acc')}，"
           f"**低于自己的常数答基线 {s(rows, 'p_adjacent', 'baseline', 'times_only')}**。"
           "也就是说它能把两笔排前后，却不能从一串时间里认出"
           "「这一笔之后紧接着那一笔、中间没有别的」——那需要对所有其它数字做一次最近邻比较。",
           f"- **什么都没给**时两条方向题的均值都掉到 "
           f"{s(rows, 'p_after', 'mean_noul', 'order_none')} / "
           f"{s(rows, 'p_adjacent', 'mean_noul', 'order_none')}，"
           "即它按 criteria 里写的「state 没说就答 false」干脆否认。"
           "这是设计里的正确行为，不是失败：所以那两格的命中率（"
           f"{s(rows, 'p_after', 'acc', 'order_none')}、"
           f"{s(rows, 'p_adjacent', 'acc', 'order_none')}）"
           "度量的是**问题本身能不能答**，不是它推理得好不好。",
           f"- **假痕迹**：`order_scrambled` 的 p_after 平均 noul 抬到 "
           f"{s(rows, 'p_after', 'mean_noul', 'order_scrambled')}（真痕迹下 "
           f"{s(rows, 'p_after', 'mean_noul', 'order_named')}），"
           f"方向真值也跟着翻，而命中率只有 "
           f"{s(rows, 'p_after', 'acc', 'order_scrambled')} —— "
           "它照读了那条假时间线，读得很有信心，读到的是错的。",
           f"- **同部件的成对题比逐元素题差**：`p_same_part` 在 `order_named` 下平均 "
           f"{s(rows, 'p_same_part', 'acc', 'order_named')}，而同一批笔画的 `part` 是 "
           f"{s(rows, 'part', 'acc', 'order_named')}。"
           f"逐元素答案与成对答案一致率：三幅 "
           f"{q(rows, 'trace_stick', 'order_named', 'part_vs_pairwise', 'agreement')}/"
           f"{q(rows, 'trace_house_interleaved', 'order_named', 'part_vs_pairwise', 'agreement')}/"
           f"{q(rows, 'trace_cat_decor', 'order_named', 'part_vs_pairwise', 'agreement')}，"
           f"整套条件平均最低到 {min(values(rows, 'part_vs_pairwise', 'agreement')):.3f}：",
           "",
           "两条路问的是同一件事，但只有一条带着词表。猫的 `fur` vs `whiskers`、"
           "`ear-left` vs `head` 这类区分在没有词表时就退化成"
           "「两根线挨在同一团东西上，算不算一个部件」。"
           "工程含义：**要做部件划分就问带名字的 Choice；"
           "成对 Noul 适合当复核，不适合当主判据。**",
           "",
           "---",
           "",
           "## 8. 整图判断",
           "",
           "三条整图题各问一次（每幅画一行）。档位题的「预测」按 火柴人/房子/猫 顺序列三个档号，"
           "「真值」同理：",
           "",
           "| 条件 | 顺序可读（noul） | 运动件数 预测 | 真值 | 对 | 装饰占比 预测 | 真值 | 对 |",
           "|---|---|---|---|---|---|---|---|",
    ]
    def levels(items: list[dict[str, Any]], key: str) -> str:
        return "/".join("%.0f" % i[key] for i in items)

    def n_ok(items: list[dict[str, Any]]) -> str:
        return "%d/%d" % (sum(1 for i in items if i["ok"]), len(items))

    for c in CONDS:
        o = gestalt_items(rows, c, "g_order_readable")
        m = gestalt_items(rows, c, "g_moving_parts")
        ds = gestalt_items(rows, c, "decor_share")
        md.append("| %s | %.2f | %s | %s | %s | %s | %s | %s |" % (
            CON_SHORT[c], statistics.fmean(i["noul"] for i in o),
            levels(m, "pred"), levels(m, "truth"), n_ok(m),
            levels(ds, "pred"), levels(ds, "truth"), n_ok(ds)))
    ok_or = sum(1 for r in rows for i in r["gestalt"]["items"]
                if i["q"] == "g_order_readable" and i["ok"])
    orow = {c: gestalt_items(rows, c, "g_order_readable") for c in CONDS}

    def score_items(key: str) -> list[dict[str, Any]]:
        return [i for r in rows for i in r["gestalt"]["items"] if i["q"] == key]

    def band_stats(key: str) -> tuple[int, list[float], int, int]:
        items = score_items(key)
        ok = sum(1 for i in items if i["ok"])
        truth = sorted({i["truth"] for i in items})
        low = sum(1 for i in items if not i["ok"] and i["pred"] < i["truth"])
        high = sum(1 for i in items if not i["ok"] and i["pred"] > i["truth"])
        return ok, truth, low, high

    ok_mp, mp_truth, mp_low, mp_high = band_stats("g_moving_parts")
    ok_ds, ds_truth, ds_low, ds_high = band_stats("decor_share")
    md += ["",
           f"`g_order_readable` 是唯一完全对的一列（{ok_or}/{len(rows)}）。给顺序时 noul "
           f"{statistics.fmean(i['noul'] for i in orow['order_named']):.2f}，"
           f"假顺序时 {statistics.fmean(i['noul'] for i in orow['order_scrambled']):.2f}"
           "（它分不清真假，但它确实读到了「顺序是写得明的」，这句不算错），"
           f"什么都不给时 {statistics.fmean(i['noul'] for i in orow['order_none']):.2f}，"
           f"只有时间戳时 {statistics.fmean(i['noul'] for i in orow['times_only']):.2f}"
           " —— 它不认为一串数字等于「读得出顺序」，"
           "这与 §7 里连笔那一格互证。",
           "",
           "两条计数题继续犯第一轮的老毛病：**分档边界**。"
           f"运动件真值三幅都是 {','.join('%.0f' % t for t in mp_truth)} 档（4–6 件），"
           f"{len(rows)} 格里答对 {ok_mp}；"
           f"装饰占比真值也都是 {','.join('%.0f' % t for t in ds_truth)} 档"
           f"（「几笔装饰压在结构上」），答对 {ok_ds}。"
           f"错的 {(len(rows) - ok_mp) + (len(rows) - ok_ds)} 格里，"
           f"{mp_high + ds_high} 格往**高一档**偏，{mp_low + ds_low} 格往低档偏——"
           "它系统性把「有若干装饰线」读成「大半张画是装饰」。"
           "要能用的还是**连续分排序**，不是落库的档位。",
           "",
           "---",
           "",
           "## 9. 这份上限对机器重绘 / live2d 意味着什么",
           "",
           f"1. **给名字，给笔迹顺序，部件划分就能直接落库**：三幅 "
           f"{s(rows, 'part', 'acc', 'order_named')} 命中、宏 F1 "
           f"{s(rows, 'part', 'macro_f1', 'order_named')}、ARI "
           f"{s(rows, 'part', 'ari', 'order_named')}、混簇 "
           f"{s(rows, 'part', 'n_mixed', 'order_named', fmt=CNT)} 个，"
           f"对着的是 {s(rows, 'part', 'baseline', 'order_named')} 的多数类基线。"
           "这是这次实验里唯一一条「可以照抄进管线」的结论。",
           f"2. **笔迹顺序单独值不了多少**：把名字拿掉（`order_list`），"
           f"平均从 {s(rows, 'part', 'acc', 'order_named')} 掉到 "
           f"{s(rows, 'part', 'acc', 'order_list')}；"
           f"而 `order_list` 对 `order_none` 只差 {mean_dev(rows, 'part', 'acc', TRACE)}。"
           "**部件的身份主要来自这条线自己画的是什么、在哪里，不来自它是第几笔。**",
           f"3. **假痕迹是负资产**：房子那幅 "
           f"{q(rows, 'trace_house_interleaved', 'order_scrambled', 'part', 'acc')} 对无痕迹的 "
           f"{q(rows, 'trace_house_interleaved', 'order_none', 'part', 'acc')}，"
           "置信度还不掉。**上游录不到真实笔迹时，宁可不给，也别给一个看起来自洽的顺序。**",
           f"4. **区域划分是免费的**：{s(rows, 'region', 'acc')} 上下，"
           f"五个条件都不动（基线 {s(rows, 'region', 'baseline')}），"
           "把矩形定义写进 state 就够了，不需要名字也不需要顺序。",
           f"5. **层级角色（五档）是这次最弱的一维**："
           f"{s(rows, 'layer', 'acc')} 的平均命中，"
           f"且 decor/detail 本来就互相混淆。工程上用那条 Noul（能不能单独一层）替代，"
           f"它的 AUC 有 {s(rows, 'loose_decor', 'auc', 'order_named')}。",
           f"6. **顺序能排前后，不能认连笔**，所以「按笔画段自动分组」这种省事做法不要指望它"
           f"（§7：p_after {s(rows, 'p_after', 'acc', 'times_only')} 对 "
           f"p_adjacent {s(rows, 'p_adjacent', 'acc', 'times_only')}）。"
           "要分段就用代码算走位距离——"
           f"顺带说，走位距离本身在这三幅上是不错的判据（AUC "
           f"{min(r['pen_travel']['auc'] for r in rows):.3f}–"
           f"{max(r['pen_travel']['auc'] for r in rows):.3f}），"
           "但那是可精确计算的事实，留在代码里。",
           f"7. **成对题与逐元素题会互相打脸**（`order_named` 下一致率 "
           f"{s(rows, 'part_vs_pairwise', 'agreement', 'order_named')}，"
           f"最差一格 {min(values(rows, 'part_vs_pairwise', 'agreement')):.3f}）："
           "词表在手上时它分得开毛和胡须，只问「这两根算不算一个部件」时就算不开了。",
           "",
           "落到 live2d 式的最小管线，这次支持的分工是：",
           "",
           "```text",
           "SVG/笔迹解析（代码）：点列、长度、闭合、包含、走位距离、时间戳排序、区域矩形",
           "        ↓ 一个扁平 state，元素带 id（id 用有意义的部件名，别用 s01）",
           "Jev（一次请求，全部并行）：part / region / motion 带词表的 Choice",
           "                            + 非闭合装饰线 Noul（当筛选器，卡阈值）",
           "        ↓",
           "代码：Choice 分布 → 软划分（ARI/NMI 连着簇数一起看）→ 浮动层清单；p_* 只当复核信号",
           "```",
           "",
           "## 10. 这一轮的失效模式与设计缺陷",
           "",
           "- **它不为痕迹的真伪负责**（§2、§7）：假时间线被照读，置信度不掉。",
           "- **数组位置是它读顺序的首选通道**：顺序只在数组位置上时读得最好；"
           "只给时间戳时，前后关系还能推（p_after "
           f"{s(rows, 'p_after', 'acc', 'times_only')}），连笔关系就废了"
           f"（{s(rows, 'p_adjacent', 'acc', 'times_only')}，基线 "
           f"{s(rows, 'p_adjacent', 'baseline', 'times_only')}）。",
           "- **ARI 混着度量了「分布尖不尖」**（§2.1），必须连簇数与 NMI 一起读。",
           "- **命中率对偏斜真值没意义**：`loose_decor` 的常数答基线 "
           f"{s(rows, 'loose_decor', 'baseline')}，`p_adjacent` 的基线 "
           f"{s(rows, 'p_adjacent', 'baseline')}，所以这两族要看 recall/precision/AUC。",
           "- **`order_none` 的两条方向题是「不可答题」**：criteria 明确写了"
           "「state 没说就答 false」，那两格的命中率是问题的性质，不是它的能力。",
           f"- **样本还很小**：三幅共 {sum(strokes.values())} 笔、"
           f"每幅 {single(rows, 'trace_stick', 'order_named', 'p_after', 'n'):.0f} 对成对题，"
           "单幅的 0.05 级差别就是一两笔的差别；跨条件的对比只读同幅内部差。",
           "- **区域真值依赖我给的切法**：切法本身是代理定义，"
           "换一种切法要重测（第一轮已见过同一条规则在九宫格上成立、在自定切法上重排）。",
           "- **词表是我提供的**：这既是结论也是局限——"
           "这次测的是「给定词表后能否归类」，不是「能否发明部件名」。",
           "",
           "---",
           "",
           "复现：`python -m src.selftest` → `python -m src.run_traces --check` → "
           "`python -m src.run_traces` → `python -m src.traces_report`。",
           "第一轮的报告在 `results/report.md`，序列化条件对照见其 §0。",
           "",
    ]

    (RESULTS / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {RESULTS / 'report.md'} ({len(md)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
