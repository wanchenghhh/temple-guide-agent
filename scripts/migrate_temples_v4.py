"""Migrate temples.json → schema v4 (2026-11-06 第二轮人工复核后).

采纳的修正（有来源支撑）：
* 妙峰山：并非宗教活动场所（wiki 明确「一直没有僧人或道士进驻…只是旅游景区」）；
  财神殿供赵公明，三霄娘娘在三仙姑殿（涧沟村重建，独立于景区）；
  文昌殿在**回香阁东厢殿**，不在娘娘庙内 —— 说法保留，依据改正。
* 东岳庙：2008 年恢复道教活动场所并颁发登记证、2015 年悬挂宗教活动场所标识牌 → 双属性。
* 红螺寺：官网自称「景区官网」、谢绝带香入园、景区门票需预约 → 现状=景区。
* 广化寺：把「正常开放」降回未核实（多个来源称平时不对游客开放）。
* 雍和宫：open_status = reservation（限流 + 线上售票）。
* 灵光寺：删掉「姻缘」（主流说法指向八大处大悲寺），并补入大悲寺（佛协登记）。
* 灵光寺→大悲寺 为置换：移除报国寺（文化市场、无心愿、无来源，纯挂名）。
* 结构：status 增加 scenic；新增 religious_registered / visitable / open_note；
  `recommendable` 拆成 `wish_recommendable`（可许愿）+ `visitable`（可参观）。
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()
P = Path("app/agent/domain/temples.json")

WIKI_MS = "https://zh.wikipedia.org/wiki/%E5%A6%99%E5%B3%B0%E5%B1%B1"
WIKI_DYM = "https://zh.wikipedia.org/wiki/%E5%8C%97%E4%BA%AC%E4%B8%9C%E5%B2%B3%E5%BA%99"
WIKI_GZJ = "https://zh.wikipedia.org/wiki/%E5%8C%97%E4%BA%AC%E5%9B%BD%E5%AD%90%E7%9B%91"
HONGLUO = "http://hongluosi.com/"
BFJ_DABEI = "https://www.beijingfojiao.com/index.php?c=show&id=19"

LABELS = {
    "religious_site": "宗教活动场所",
    "heritage": "文博点",
    "scenic": "景区/民间信仰",
    "relic": "遗址",
    "closed": "不开放",
    "market": "文化市场",
}

# 佛协「寺院介绍」名单内的 8 座：登记在册的佛教活动场所
BFJ_REGISTERED = {
    "yonghegong", "tongjiaosi", "guanghuasi", "tianningsi",
    "yunjusi", "tanzhesi", "jietaisi", "hepingsi",
}

STATUS_V4 = {
    # id: (status, registered, visitable, wish_recommendable, open_status)
    "yonghegong": ("religious_site", True, True, True, "reservation"),
    "tongjiaosi": ("religious_site", True, True, False, "unverified"),
    "guanghuasi": ("religious_site", True, True, True, "unverified"),
    "tianningsi": ("religious_site", True, True, True, "unverified"),
    "yunjusi": ("religious_site", True, True, True, "unverified"),
    "tanzhesi": ("religious_site", True, True, True, "unverified"),
    "jietaisi": ("religious_site", True, True, True, "unverified"),
    "hepingsi": ("religious_site", True, True, True, "unverified"),
    "hongluosi": ("scenic", None, True, True, "reservation"),
    "guangjisi": ("religious_site", None, True, True, "unverified"),
    "fayuansi": ("religious_site", None, True, True, "unverified"),
    "lingguangsi": ("religious_site", None, True, True, "unverified"),
    "wofosi": ("scenic", None, True, True, "unverified"),
    "baiyunguan": ("religious_site", None, True, True, "unverified"),
    "huodeshenmiao": ("religious_site", None, True, True, "unverified"),
    "miaofengshan": ("scenic", False, True, True, "unverified"),
    "dongyuemiao": ("heritage", True, True, True, "unverified"),
    "zhihuasi": ("heritage", False, True, True, "reservation"),
    "miaoyingsi": ("heritage", None, True, True, "unverified"),
    "dazhongsi": ("heritage", None, True, True, "unverified"),
    "dajuesi": ("heritage", False, True, True, "unverified"),
    "fahaisi": ("heritage", None, True, True, "reservation"),
    "biyunsi": ("heritage", None, True, True, "unverified"),
    "wutasi": ("heritage", False, True, True, "unverified"),
    "wanshousi": ("heritage", False, True, True, "unverified"),
    "kongmiao": ("heritage", False, True, True, "unverified"),
    "lidaidiwangmiao": ("heritage", None, True, True, "unverified"),
    "cishousi": ("relic", False, False, False, "unverified"),
    "dahuisi": ("closed", False, False, False, "closed"),
    "dabeisi": ("religious_site", True, True, True, "unverified"),
}

OPEN_NOTE = {
    "yonghegong": "香火最旺，节假日限流；现需线上预约购票，开放时段与止票时间以官方公众号公告为准。",
    "guanghuasi": "有多个来源称平时不对游客开放，仅在农历初一、十五及佛菩萨圣诞开放；具体以寺院或佛协公告为准。",
    "tongjiaosi": "尼众道场，以清修为主；开放时间不同渠道说法不一（有说仅上午、有说只在初一十五、结夏安居期间不开放），出发前务必电话核实。",
    "hongluosi": "景区官网标注「谢绝带香入园」（庙区提供免费香），门票需预约；开放时段以景区公告为准。",
    "wofosi": "位于国家植物园内，进入需植物园门票；是否为宗教活动场所待核，按参观场所看待更稳。",
    "dongyuemiao": "现为北京民俗博物馆，同时自 2008 年起恢复为道教活动场所；两套管理班子并存，中路神像区由道教界管理。",
    "miaofengshan": "是景区与民间信仰庙宇，并非宗教活动场所（无僧道进驻）；庙会期间香火最盛。",
    "zhihuasi": "文博开放场所，需公众号提前预约购票（至多提前 3 个开放日），现场不售票。",
    "wutasi": "同一地点两个运营主体：石刻艺术博物馆（售票、周一闭馆）与五塔寺公园（免费），开放时间不同。",
    "dabeisi": "位于八大处公园内，需公园门票；开放时间以官方公告为准。",
    "lingguangsi": "位于八大处公园内，需公园门票；佛牙舍利塔开放时间另行公告。",
    "fayuansi": "中国佛学院所在地，是否对普通游客开放待核（有说法称平时不对外开放）。",
    "baiyunguan": "道教宫观，春节庙会期间人流量大；开放时间与门票以官方公告为准。",
    "huodeshenmiao": "什刹海畔道观，开放时间与是否收费待核。",
    "guangjisi": "中国佛教协会所在地，是否对普通游客开放待核。",
    "dajuesi": "文博开放场所（北京大觉寺与团城管理处），开放时间以官方公告为准。",
    "miaoyingsi": "白塔寺，现为博物馆性质开放，周一闭馆，需购票。",
    "dazhongsi": "古钟博物馆，周一闭馆，需购票。",
    "wanshousi": "北京艺术博物馆，周一闭馆，需购票。",
    "kongmiao": "文博开放场所，周一闭馆，需预约购票。",
    "lidaidiwangmiao": "博物馆性质，周一闭馆，需购票。",
    "fahaisi": "看壁画需预约，名额有限，务必提前约。",
    "biyunsi": "位于香山公园内，需公园门票。",
    "tianningsi": "尼众寺院，是否对普通游客开放待核。",
    "yunjusi": "开放时间与门票以官方公告为准。",
    "tanzhesi": "开放时间与门票以官方公告为准。",
    "jietaisi": "开放时间与门票以官方公告为准。",
    "hepingsi": "开放时间与门票以官方公告为准。",
    "cishousi": "仅存慈寿寺塔（玲珑塔），位于玲珑公园内。",
    "dahuisi": "长期未对公众开放。",
}

# 场所事实补充/更正
FACTS = {
    "miaofengshan": [
        ("妙峰山自重新对外开放之后，一直没有僧人或道士进驻，并非宗教活动场所，只是旅游景区。", WIKI_MS, "reference"),
        ("娘娘庙主要建筑：山门殿、正殿（灵感宫）、地藏殿、药王殿、观音殿、月老殿、财神殿、王三奶奶殿；庙外另有回香阁。", WIKI_MS, "reference"),
        ("回香阁东厢殿为文昌殿，供奉文昌帝君；回香阁在灵感宫以北约 100 米。", WIKI_MS, "reference"),
        ("财神殿位于灵感宫东路殿堂，供奉赵公明像。", WIKI_MS, "reference"),
    ],
    "dongyuemiao": [
        ("2008 年 5 月 3 日恢复道教活动场所并颁发宗教活动场所登记证；2015 年 5 月 16 日正式悬挂宗教活动场所标识牌。", WIKI_DYM, "reference"),
        ("庙内同时设有北京民俗博物馆，形成两套管理班子并存。", WIKI_DYM, "reference"),
    ],
    "hongluosi": [
        ("红螺寺官网自我标识为「景区官网」，并注明「谢绝带香入园」，景区门票需预约。", HONGLUO, "official"),
    ],
    "kongmiao": [
        ("国子监是元明清三代国家最高学府所在地，与孔庙一墙之隔（「左庙右学」）。", WIKI_GZJ, "reference"),
    ],
}

# 心愿依据更正：(tid, theme) -> (basis, claim_evidence, claim)
WISH_FIX = {
    ("miaofengshan", "学业"): ("回香阁东厢殿（文昌帝君）", "reference", "民间到回香阁文昌殿求学业。"),
    ("miaofengshan", "财运"): ("财神殿（赵公明）", "reference", "民间到财神殿向赵公明求财。"),
    ("miaofengshan", "健康"): ("药王殿（药王扁鹊）", "reference", "民间到药王殿求健康。"),
    ("miaofengshan", "姻缘"): ("月老殿（月下老人）", "reference", "过去青年男女到月老殿求婚姻。"),
    ("miaofengshan", "求子"): ("灵感宫（碧霞元君、眼光/子孙/斑疹/送生娘娘）", "reference", "庙会期间向碧霞元君与子孙娘娘、送生娘娘求子。"),
    ("kongmiao", "学业"): ("大成殿（孔子）＋国子监（元明清最高学府）", "folk", "民众到孔庙祈求考试顺利是长期民俗。"),
    ("guangjisi", "姻缘"): ("圆通殿（即观音殿，供观音菩萨）", "folk", "网络攻略称圆通殿求姻缘灵验。"),
}

DABEISI = {
    "id": "dabeisi",
    "name": "大悲寺",
    "aliases": ["八大处大悲寺", "隐寂寺"],
    "district": "石景山区",
    "sect": "汉传佛教",
    "status": "religious_site",
    "status_label": LABELS["religious_site"],
    "religious_registered": True,
    "visitable": True,
    "wish_recommendable": True,
    "open_status": "unverified",
    "closure_rule": [],
    "address_hint": "石景山区八大处三山庵与龙泉庵之间的山腰",
    "overview": "八大处「三山八刹十二景」中的著名一刹，始建辽宋，原名隐寂寺，清康熙五十一年（1712）改名大悲寺；2011 年颁发宗教活动场所登记证，为北京市级文物保护单位。",
    "deities": [],
    "wish_themes": [
        {
            "theme": "姻缘",
            "role": "primary",
            "claim": "八大处一带流传的姻缘说法多指向大悲寺（同处八大处的灵光寺更偏平安、健康）。",
            "claim_evidence": "folk",
            "basis": "",
            "basis_source": "",
        }
    ],
    "generic_wish_ok": True,
    "halls": [],
    "place_facts": [],
    "sources": [
        {"url": BFJ_DABEI, "publisher": "北京市佛教协会", "kind": "official", "checked_at": TODAY}
    ],
    "sources_status": "verified",
    "finder_hint": ["八大处公园 公众号"],
    "atmosphere": "位于八大处山腰，环境清幽，是八大处诸寺之一。",
    "transport": "八大处公园内，市区乘车约 40–60 分钟可达公园，园内步行上山。",
    "accessibility": "公园内需爬山或乘缆车，体力要求中等。",
    "visit_note": "位于八大处公园内，需公园门票；开放时间以官方公告为准。",
    "recommend_note": "",
    "checked_at": TODAY,
}


def check(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (link-check)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    data = json.loads(P.read_text(encoding="utf-8"))
    rows = [r for r in data["temples"] if r["id"] != "baoguosi"]   # 置换：报国寺 → 大悲寺
    urls: dict[str, bool] = {}

    for t in rows:
        tid = t["id"]
        status, registered, visitable, wish_ok, open_status = STATUS_V4[tid]
        legacy_rec = t.pop("recommendable", True)
        t["status"] = status
        t["status_label"] = LABELS[status]
        t["religious_registered"] = registered
        t["visitable"] = visitable
        t["wish_recommendable"] = wish_ok if tid in STATUS_V4 else legacy_rec
        t["open_status"] = open_status
        t["open_note"] = OPEN_NOTE.get(tid, "")

        # 景区/文博点即使可许愿，也必须说明它不是上香许愿的宗教活动场所
        if status in ("heritage", "scenic") and wish_ok:
            base = t.get("recommend_note") or ""
            if "不是上香许愿" not in base:
                t["recommend_note"] = ("此处可参观，但不是上香许愿的宗教活动场所。" + base).strip()
        elif not wish_ok and not (t.get("recommend_note") or "").strip():
            t["recommend_note"] = "第一版不纳入许愿推荐。"

        for text, url, kind in FACTS.get(tid, []):
            if url not in urls:
                urls[url] = check(url)
            if not urls[url]:
                continue
            facts = t.setdefault("place_facts", [])
            if all(f["text"] != text for f in facts):
                facts.append({"text": text, "source": url, "evidence_type": kind, "checked_at": TODAY})
            known = {s["url"] for s in t.setdefault("sources", [])}
            if url not in known:
                t["sources"].append({
                    "url": url,
                    "publisher": ("红螺寺景区官网" if "hongluosi" in url else "维基百科"),
                    "kind": kind,
                    "checked_at": TODAY,
                })
        if t["sources"]:
            t["sources_status"] = "verified"

        if tid == "lingguangsi":
            t["wish_themes"] = [w for w in t["wish_themes"] if w["theme"] != "姻缘"]
            t["recommend_note"] = "八大处一带的姻缘说法多指向大悲寺（资料库已收录），灵光寺更偏平安与健康。"
        if tid == "tongjiaosi":
            t["recommend_note"] = "尼众道场、以清修为主，开放信息四处不一，用户很可能白跑，第一版暂不纳入许愿推荐。"

        for w in t["wish_themes"]:
            fix = WISH_FIX.get((tid, w["theme"]))
            if not fix:
                continue
            w["basis"], w["claim_evidence"], w["claim"] = fix
            if w["basis"] and not w.get("basis_source") and t["sources"]:
                w["basis_source"] = t["sources"][0]["url"]
            if w["basis"] and t["sources"]:
                w["basis_source"] = t["sources"][0]["url"]
        t["checked_at"] = TODAY

    rows.append(DABEISI)
    data["temples"] = rows
    data["meta"].update({
        "schema_version": "v4",
        "updated_at": TODAY,
        "checked_at": TODAY,
        "count": len(rows),
        "recommendable_count": sum(1 for r in rows if r["wish_recommendable"]),
        "visitable_count": sum(1 for r in rows if r["visitable"]),
        "status_policy": (
            "status 区分宗教活动场所 / 文博点 / 景区·民间信仰 / 遗址 / 不开放 / 文化市场；"
            "religious_registered 标明是否登记宗教活动场所（null=待核）。"
            "「景区」和「文博点」可以参观，但不当成上香许愿的地方。"
        ),
        "recommend_policy": (
            "wish_recommendable = 能否作为许愿推荐；visitable = 能否去参观。"
            "两列分开，避免「可推荐」含义不清。"
        ),
    })
    data["meta"]["wish_policy"] = (
        "「平安」不作为寺庙标签：用户只说平安时，按「可推荐 + 距离 + 氛围」给默认候选。"
        "其余心愿必须有说法与依据：claim 是民俗/文献说法，basis 是场所事实（殿宇/神像），"
        "两者分别标注，不把民俗升格为事实。"
    )
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    from collections import Counter
    print("temples:", len(rows),
          "| 可许愿:", data["meta"]["recommendable_count"],
          "| 可参观:", data["meta"]["visitable_count"])
    print("status:", dict(Counter(r["status"] for r in rows)))
    print("registered:", dict(Counter(str(r["religious_registered"]) for r in rows)))
    print("verified:", sum(1 for r in rows if r["sources_status"] == "verified"),
          "| unverified:", "、".join(r["name"] for r in rows if r["sources_status"] != "verified"))


if __name__ == "__main__":
    main()
