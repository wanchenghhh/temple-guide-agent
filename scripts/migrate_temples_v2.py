"""One-off: migrate app/agent/domain/temples.json to schema v2.

v2 changes (driven by the 2026-11-06 manual review):
* 现状 status: active_temple | heritage | relic | closed | market (+ recommendable)
* 心愿: role(primary/secondary) + evidence_type(official/reference/folk) + source
* 殿 halls: 殿名 + 神像 + 管什么心愿 + 依据
* 来源 sources: verified (HTTP 200) URLs only, with checked_at; else [] + unverified
* 「平安」不再是标签: 由检索层的默认项处理（用户决定）
* 去掉所有"约9:00–17:00、约25元"式易变数字，改为指向官方渠道
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()
BFJ = "https://www.beijingfojiao.com/index.php?c=show&id={}"
WIKI = "https://zh.wikipedia.org/wiki/{}"
P = Path("app/agent/domain/temples.json")

BFJ_IDS = {
    "yonghegong": 5, "tongjiaosi": 10, "guanghuasi": 14, "tianningsi": 16,
    "yunjusi": 27, "tanzhesi": 36, "jietaisi": 37, "hepingsi": 41,
}
WIKI_TITLES = {
    "hongluosi": "红螺寺", "guangjisi": "广济寺 (北京市)",
    "miaoyingsi": "妙应寺", "dazhongsi": "大钟寺", "wofosi": "卧佛寺",
    "dahuisi": "大慧寺", "baiyunguan": "白云观", "dongyuemiao": "北京东岳庙",
    "miaofengshan": "妙峰山", "cishousi": "慈寿寺塔",
}

# 复核结论（2026-11-06 人工核验 / 用户复核）
FIX = {
    # 硬错与地址交通
    "tianningsi": {
        "sect": "汉传佛教（尼众）", "category": "汉传佛教（尼众）",
        "address_hint": "西城区天宁寺前街甲3号",
        "transport": "地铁7号线广安门内站，公交可达。",
        "overview": "北京城内的尼众寺院，建筑坐北朝南，殿宇为清代重修，自南向北依次为山门殿、弥陀殿及东西配殿；寺内天宁寺塔为辽代古塔，是北京现存最古老的建筑之一。",
    },
    "fahaisi": {"transport": "地铁11号线模式口站附近（6号线金安桥站换乘11号线），公交可达。"},
    "kongmiao": {
        "address_hint": "东城区国子监街：孔庙13号、国子监15号（两处相邻）",
        "category": "儒家/文庙",
    },
    "dazhongsi": {"category": "汉传佛教（现为古钟博物馆）"},
    # 心愿硬错：大钟寺没有任何"学业"依据
    "_remove_themes": {"dazhongsi": ["学业"]},
}

# 现状：活跃寺院(可许愿) / 文博点(可参观、顺带祈福) / 遗址 / 不开放 / 文化市场
STATUS = {
    # —— 佛协登记的活动场所（有官方来源）——
    "yonghegong": ("active_temple", True, "normal", []),
    "tongjiaosi": ("active_temple", False, "unverified", []),   # 尼众道场，开放信息四处不一
    "guanghuasi": ("active_temple", True, "normal", []),
    "tianningsi": ("active_temple", True, "normal", []),
    "yunjusi": ("active_temple", True, "normal", []),
    "tanzhesi": ("active_temple", True, "normal", []),
    "jietaisi": ("active_temple", True, "normal", []),
    "hepingsi": ("active_temple", True, "normal", []),
    # —— 活跃但由景区/协会管理，开放与票价需单独核实 ——
    "hongluosi": ("active_temple", True, "unverified", []),
    "guangjisi": ("active_temple", True, "unverified", []),
    "fayuansi": ("active_temple", True, "unverified", []),
    "lingguangsi": ("active_temple", True, "unverified", []),
    "wofosi": ("active_temple", True, "unverified", []),
    "baiyunguan": ("active_temple", True, "unverified", []),
    "huodeshenmiao": ("active_temple", True, "unverified", []),
    "miaofengshan": ("active_temple", True, "unverified", []),
    # —— 文博点：可参观，不是上香许愿的场所 ——
    "zhihuasi": ("heritage", True, "reservation", ["周一闭馆"]),
    "miaoyingsi": ("heritage", True, "unverified", ["周一闭馆"]),
    "dazhongsi": ("heritage", True, "unverified", ["周一闭馆"]),
    "dajuesi": ("heritage", True, "unverified", []),
    "baoguosi": ("market", False, "unverified", []),
    "fahaisi": ("heritage", True, "reservation", []),
    "biyunsi": ("heritage", True, "unverified", []),
    "wutasi": ("heritage", True, "unverified", ["周一闭馆"]),
    "wanshousi": ("heritage", True, "unverified", ["周一闭馆"]),
    "dongyuemiao": ("heritage", True, "unverified", ["周一闭馆"]),
    "kongmiao": ("heritage", True, "unverified", ["周一闭馆"]),
    "lidaidiwangmiao": ("heritage", True, "unverified", ["周一闭馆"]),
    # —— 遗址 / 不开放 ——
    "cishousi": ("relic", False, "unverified", []),
    "dahuisi": ("closed", False, "closed", []),
}

HERITAGE_NOTE = "此处现为文博/参观场所，不是上香许愿的寺院；可以去看建筑与氛围，但别当成拜佛求愿的地方。"
RELICS_NOTE = {
    "cishousi": "寺院建筑已在清代焚毁，现仅存慈寿寺塔（玲珑塔），位于玲珑公园内，不是可参访的寺院。",
    "dahuisi": "现仅存大悲宝殿，长期未对公众开放，不建议列入寻访推荐。",
}

# 已非活跃寺院的条目，不能再拿“以官方为准”含糊带过
RELICS_TEXT = {
    "cishousi": {
        "atmosphere": "仅存的玲珑塔位于玲珑公园内，公园环境清静，适合散步看塔。",
        "accessibility": "公园地面平缓，塔周边可行走；不是寺院参访。",
    },
    "dahuisi": {
        "atmosphere": "仅存一座大悲宝殿，被居民区包围，不对公众开放。",
        "accessibility": "不对外开放，无参访条件。",
    },
}

# 具体、可核对的开放提示（人工复核结论，非官方公告原文）
VISIT = {
    "yonghegong": "香火最旺，节假日常需排队；现多需线上预约，具体开放时段与购票方式请以官方公众号最新公告为准。",
    "zhihuasi": "现为文博开放场所，需通过官方公众号提前预约购票（至多提前3个开放日），现场不再售票；京音乐演出时间固定，出行前请核实场次。",
    "wutasi": "同一地点有两个运营主体：石刻艺术博物馆（售票、周一闭馆）与五塔寺公园（免费开放），两者开放时间不同，去之前先确认你要进哪一个。",
    "tongjiaosi": "尼众道场，以清修为主；开放时间在不同渠道说法不一（有说仅上午、有说只在初一十五、结夏安居期间不开放），出发前务必电话核实。",
}

DEFAULT_VISIT_ACTIVE = "开放时间、门票与预约方式以官方渠道最新公告为准，出发前再确认一次。"
DEFAULT_VISIT_HERITAGE = "为文博开放场所，多数周一闭馆、可能需要预约或购票，请以官方公告为准。"

# 心愿：role=primary/secondary，evidence_type=official/reference/folk
WISH = {
    "yonghegong": [("事业", "primary", "folk", "民间常说雍和宫求事业、仕途，无权威依据，只作口碑参考。")],
    "tanzhesi": [("事业", "secondary", "folk", "皇家寺院背景，民间有求仕途的说法，属口碑。")],
    "hongluosi": [
        ("姻缘", "primary", "folk", "中院设千手观音殿，民间以观音殿求姻缘的说法流传最广，属网络口碑。"),
        ("求子", "secondary", "folk", "民间也有求子说法，无权威依据。"),
    ],
    "guangjisi": [("姻缘", "primary", "folk", "寺内圆通殿（观音殿）求姻缘的说法见于网络攻略，无权威依据。")],
    "lingguangsi": [("姻缘", "primary", "folk", "「求姻缘去八大处」是流传较广的民间说法，无权威依据。")],
    "wofosi": [("学业", "primary", "folk", "「卧佛」谐音 offer，近年学生求学业、求职的口碑，属网络流行说法。")],
    "kongmiao": [("学业", "primary", "folk", "孔庙祭孔，民间以求学业、考试顺利为主，属传统民俗。")],
    "baiyunguan": [
        ("求子", "primary", "reference", "元君殿内祀催生娘娘、送子娘娘、眼光娘娘、天花娘娘。"),
        ("学业", "secondary", "reference", "文昌殿供奉文昌帝君。"),
        ("健康", "secondary", "reference", "药王殿供奉药王。"),
        ("财运", "secondary", "reference", "财神殿（原儒仙殿）祀财神。"),
    ],
    "miaofengshan": [
        ("求子", "primary", "reference", "灵感宫供奉碧霞元君，两侧为眼光娘娘、子孙娘娘、斑疹娘娘、送生娘娘。"),
        ("姻缘", "secondary", "reference", "灵感宫西路殿堂设月老殿。"),
        ("财运", "secondary", "reference", "殿内供奉三霄娘娘，民间视为财神。"),
        ("健康", "secondary", "reference", "娘娘庙设药王殿。"),
        ("学业", "secondary", "reference", "东厢殿为文昌殿，供奉文昌帝君。"),
    ],
    "dongyuemiao": [
        ("姻缘", "primary", "reference", "庙内西路已修复月老殿。"),
        ("健康", "secondary", "reference", "庙内设药王殿。"),
        ("学业", "secondary", "reference", "后罩楼设文昌殿，供奉文昌帝君。"),
    ],
    "huodeshenmiao": [("财运", "primary", "folk", "民间以火神庙求财为主，属口碑说法。")],
}

HALLS = {
    "hongluosi": [("千手观音殿", "千手观音", ["姻缘"], "reference")],
    "guangjisi": [("圆通殿（观音殿）", "观音菩萨", ["姻缘"], "reference")],
    "baiyunguan": [
        ("元君殿", "催生娘娘、送子娘娘、眼光娘娘、天花娘娘", ["求子"], "reference"),
        ("文昌殿", "文昌帝君", ["学业"], "reference"),
        ("药王殿", "药王", ["健康"], "reference"),
        ("财神殿", "财神", ["财运"], "reference"),
    ],
    "miaofengshan": [
        ("灵感宫", "碧霞元君、子孙娘娘、送生娘娘", ["求子"], "reference"),
        ("月老殿", "月老", ["姻缘"], "reference"),
        ("文昌殿", "文昌帝君", ["学业"], "reference"),
        ("药王殿", "药王", ["健康"], "reference"),
        ("财神殿", "三霄娘娘", ["财运"], "reference"),
    ],
    "dongyuemiao": [
        ("月老殿", "月老", ["姻缘"], "reference"),
        ("文昌殿", "文昌帝君", ["学业"], "reference"),
        ("药王殿", "药王", ["健康"], "reference"),
    ],
    "tianningsi": [("山门殿、弥陀殿", "弥陀", [], "reference")],
}


def check(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (link-check)"}, method="HEAD")
        return urllib.request.urlopen(req, timeout=15).status == 200
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (link-check)"})
            return urllib.request.urlopen(req, timeout=15).status == 200
        except Exception:
            return False


def source_for(tid: str) -> tuple[list[dict], str]:
    if tid in BFJ_IDS:
        url = BFJ.format(BFJ_IDS[tid])
        if check(url):
            return ([{"url": url, "publisher": "北京市佛教协会", "kind": "official",
                      "checked_at": TODAY}], "verified")
    if tid in WIKI_TITLES:
        from urllib.parse import quote
        url = WIKI.format(quote(WIKI_TITLES[tid]))
        if check(url):
            return ([{"url": url, "publisher": "维基百科", "kind": "reference",
                      "checked_at": TODAY}], "verified")
    return ([], "unverified")


def main() -> None:
    data = json.loads(P.read_text(encoding="utf-8"))
    out = []
    for t in data["temples"]:
        tid = t["id"]
        t.pop("category", None)
        t.update({k: v for k, v in FIX.get(tid, {}).items() if not k.startswith("_")})

        status, recommendable, open_status, closure = STATUS[tid]
        t["status"] = status
        t["status_label"] = {
            "active_temple": "活跃寺院", "heritage": "文博点",
            "relic": "遗址", "closed": "不开放", "market": "文化市场",
        }[status]
        t["recommendable"] = recommendable
        t["open_status"] = open_status
        t["closure_rule"] = closure
        if status == "heritage":
            t["recommend_note"] = HERITAGE_NOTE
        elif not recommendable:
            t["recommend_note"] = RELICS_NOTE.get(tid, "第一版不纳入寻愿推荐。")
        else:
            t["recommend_note"] = ""

        # 宗派与场所类型分开
        t["sect"] = t.pop("sect", None) or {
            "yonghegong": "藏传佛教", "miaoyingsi": "藏传佛教", "wutasi": "藏传佛教",
            "baiyunguan": "道教", "dongyuemiao": "道教", "huodeshenmiao": "道教",
            "miaofengshan": "民间信仰", "kongmiao": "儒家", "lidaidiwangmiao": "无",
            "guanghuasi": "汉传佛教", "tongjiaosi": "汉传佛教（尼众）",
        }.get(tid, "汉传佛教")

        # 心愿
        removed = FIX["_remove_themes"].get(tid, [])
        themes = []
        for theme, role, ev, note in WISH.get(tid, []):
            themes.append({"theme": theme, "role": role, "evidence_type": ev,
                           "note": note, "source_url": ""})
        t["wish_themes"] = [w for w in themes if w["theme"] not in removed]
        t["generic_wish_ok"] = status == "active_temple"   # 平安等泛化诉求走默认项

        # 殿
        srcs, src_status = source_for(tid)
        url = srcs[0]["url"] if srcs else ""
        halls = []
        for name, deity, hthemes, ev in HALLS.get(tid, []):
            halls.append({"name": name, "deity": deity, "themes": hthemes,
                          "evidence_type": ev, "source_url": url,
                          "checked_at": TODAY if url else ""})
        t["halls"] = halls
        for w in t["wish_themes"]:
            if any(w["theme"] in h["themes"] for h in halls):
                w["source_url"] = url
            w["source_url"] = w["source_url"] or ""

        # 来源
        t["sources"] = srcs
        t["sources_status"] = src_status
        t["checked_at"] = TODAY

        # 去掉易变数字，指向官方渠道
        if tid in VISIT:
            t["visit_note"] = VISIT[tid]
        elif status in ("relic", "closed"):
            t["visit_note"] = "不具备常规参访条件，请勿作为出行目的地。"
        elif status == "heritage":
            t["visit_note"] = DEFAULT_VISIT_HERITAGE
        elif status == "market":
            t["visit_note"] = "现为文化市场/书市，营业时间以场地公告为准。"
        else:
            t["visit_note"] = DEFAULT_VISIT_ACTIVE

        for k, v in RELICS_TEXT.get(tid, {}).items():
            t[k] = v

        out.append(t)

    data["temples"] = out
    data["meta"] = {
        "schema_version": "v2",
        "city": "北京",
        "scope": "城近郊",
        "updated_at": TODAY,
        "checked_at": TODAY,
        "count": len(out),
        "recommendable_count": sum(1 for t in out if t["recommendable"]),
        "note": (
            "资料整理自公开信息，逐条标注来源与核对日期；未核实字段一律标 unverified，不写成事实。"
            "开放时间、门票、预约方式随时可能变化，一律以官方渠道最新公告为准。"
            "民间说法只作口碑参考，不代表灵验承诺。"
        ),
        "wish_policy": (
            "「平安」不作为寺庙标签：用户只说平安时，按「可推荐 + 距离 + 氛围」给默认候选。"
            "其余心愿必须有依据（殿宇/神像或文献），依据分 official / reference / folk 三级，"
            "folk 级必须在回答里说明是民间口碑。"
        ),
    }
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("temples:", len(out),
          "| recommendable:", data["meta"]["recommendable_count"])
    from collections import Counter
    print("status:", dict(Counter(t["status"] for t in out)))
    print("sources verified:", sum(1 for t in out if t["sources_status"] == "verified"),
          "| unverified:", sum(1 for t in out if t["sources_status"] == "unverified"))
    th = Counter()
    for t in out:
        for w in t["wish_themes"]:
            th[w["theme"]] += 1
    print("themes:", dict(th))


if __name__ == "__main__":
    main()
