"""Migrate temples.json → schema v3.

Two structural changes approved by the product owner (2026-11-06):

1. **依据分两层**
   * ``place_facts``: what the place *is* — verifiable (官方/文献 + URL).
   * ``wish_themes[].claim``: what people *pray for* there — a folk usage, never
     upgraded to "documented fact" just because the hall is documented.
2. **公众号只当渠道名**
   WeChat official accounts cannot be verified programmatically (login, unstable
   URL). They go to ``finder_hint`` ("去哪问"), never to ``sources``.

Also fills the five P0 文博点 sources found via 北京市文物局:
* 孔庙: 文物局专页 + 官网 (地址 国子监街13号)
* 五塔寺 / 万寿寺 / 大觉寺: 文物局「备案且正常开放博物馆」名单
* 智化寺: 文物局核心区（东城区）名单
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()
P = Path("app/agent/domain/temples.json")

WWJ = "https://wwj.beijing.gov.cn"
MUSEUM_LIST = f"{WWJ}/bjww/362771/362772/index.html"          # 备案且正常开放博物馆
DONGC = f"{WWJ}/bjww/362771/hxqbaqzckfbwg/dcq/index.html"      # 核心区（东城区）博物馆
KONGMIAO_GOV = f"{WWJ}/bjww/362771/362779/dspqgzdwwbhdw/523286/index.html"
KONGMIAO_SITE = "http://kmgzj.com/"

WWJ_FACTS = {
    "kongmiao": [
        {"text": "北京市文物局「北京孔庙」页面记录：东城区国子监街13号，孔庙和国子监博物馆。",
         "source": KONGMIAO_GOV, "evidence_type": "official"},
        {"text": "孔庙和国子监博物馆官网提供「预约购票」入口与闭馆时间公告。",
         "source": KONGMIAO_SITE, "evidence_type": "official"},
    ],
    "wutasi": [
        {"text": "列入北京市文物局「北京地区备案且正常开放博物馆」名单，名称：北京石刻艺术博物馆。",
         "source": MUSEUM_LIST, "evidence_type": "official"},
    ],
    "wanshousi": [
        {"text": "列入北京市文物局「北京地区备案且正常开放博物馆」名单，名称：万寿寺博物馆。",
         "source": MUSEUM_LIST, "evidence_type": "official"},
    ],
    "dajuesi": [
        {"text": "列入北京市文物局「北京地区备案且正常开放博物馆」名单，名称：北京大觉寺与团城管理处。",
         "source": MUSEUM_LIST, "evidence_type": "official"},
    ],
    "zhihuasi": [
        {"text": "列入北京市文物局核心区（东城区）备案且正常开放博物馆名单，名称：北京文博交流馆（北京市智化寺管理处）。",
         "source": DONGC, "evidence_type": "official"},
    ],
}

# 公众号等不可程序核验的渠道：只作 finder_hint
FINDER = {
    "yonghegong": ["雍和宫游客信众服务 公众号", "北京市佛教协会 官网"],
    "hongluosi": ["红螺寺景区 公众号", "hongluosi.com"],
    "fayuansi": ["法源寺 / 中国佛学院 公众号"],
    "guangjisi": ["中国佛教协会 官网"],
    "zhihuasi": ["北京文博交流馆（智化寺）公众号"],
    "dajuesi": ["北京大觉寺 公众号"],
    "lingguangsi": ["八大处公园 公众号"],
    "baoguosi": ["报国寺文化市场 公众号"],
    "fahaisi": ["法海寺壁画艺术馆 公众号"],
    "biyunsi": ["香山公园 公众号"],
    "wutasi": ["北京石刻艺术博物馆 公众号"],
    "wanshousi": ["北京艺术博物馆 公众号"],
    "huodeshenmiao": ["北京火神庙 公众号"],
    "kongmiao": ["孔庙和国子监博物馆 官网", "孔庙和国子监博物馆 公众号"],
    "lidaidiwangmiao": ["北京历代帝王庙博物馆 公众号"],
    "baiyunguan": ["北京白云观 公众号"],
    "miaofengshan": ["妙峰山 公众号"],
    "tongjiaosi": ["北京市佛教协会 官网（寺院介绍）"],
    "wofosi": ["国家植物园 公众号"],
    "cishousi": ["玲珑公园 管理方公告"],
    "dahuisi": ["北京市文物局 公告"],
    "dongyuemiao": ["北京民俗博物馆 公众号"],
    "miaoyingsi": ["白塔寺（妙应寺）公众号"],
    "dazhongsi": ["大钟寺古钟博物馆 公众号"],
    "tanzhesi": ["潭柘寺 公众号"],
    "jietaisi": ["戒台寺 公众号"],
    "guanghuasi": ["广化寺 公众号"],
    "tianningsi": ["北京市佛教协会 官网（寺院介绍）"],
    "yunjusi": ["云居寺 公众号"],
    "hepingsi": ["北京市佛教协会 官网（寺院介绍）"],
}

# 许愿说法（claim）与场所事实（basis）分开表述
CLAIM_TEXT = {
    ("hongluosi", "姻缘"): "民间流传在千手观音殿求姻缘，网络攻略里出现最多。",
    ("hongluosi", "求子"): "民间也有到此求子的说法。",
    ("guangjisi", "姻缘"): "网络攻略称圆通殿（观音殿）求姻缘灵验。",
    ("lingguangsi", "姻缘"): "「求姻缘去八大处」是流传较广的说法。",
    ("wofosi", "学业"): "因「卧佛」谐音 offer，近年学生来求学业与求职。",
    ("kongmiao", "学业"): "民众到孔庙祈求考试顺利是长期民俗。",
    ("baiyunguan", "求子"): "民间到元君殿向送子娘娘、催生娘娘求子。",
    ("baiyunguan", "学业"): "民间到文昌殿求学业、考试顺利。",
    ("baiyunguan", "健康"): "民间到药王殿求祛病健康。",
    ("baiyunguan", "财运"): "民间到财神殿求财。",
    ("miaofengshan", "求子"): "庙会期间向碧霞元君与子孙娘娘、送生娘娘求子。",
    ("miaofengshan", "姻缘"): "民间到月老殿求姻缘。",
    ("miaofengshan", "财运"): "民间向三霄娘娘求财。",
    ("miaofengshan", "健康"): "民间到药王殿求健康。",
    ("miaofengshan", "学业"): "民间到文昌殿求学业。",
    ("dongyuemiao", "姻缘"): "民间到月老殿求姻缘。",
    ("dongyuemiao", "健康"): "民间到药王殿求健康。",
    ("dongyuemiao", "学业"): "民间到文昌殿求学业。",
    ("huodeshenmiao", "财运"): "民间到火神庙求财。",
    ("yonghegong", "事业"): "民间常说雍和宫求事业、仕途。",
    ("tanzhesi", "事业"): "皇家寺院背景，民间有求仕途的说法。",
}

# 场所事实（可核）——殿宇/主供
BASIS = {
    ("hongluosi", "姻缘"): "中院千手观音殿（千手观音）",
    ("guangjisi", "姻缘"): "圆通殿（观音菩萨）",
    ("wofosi", "学业"): "卧佛殿（释迦牟尼卧像）",
    ("kongmiao", "学业"): "大成殿（孔子）",
    ("baiyunguan", "求子"): "元君殿（送子娘娘、催生娘娘、眼光娘娘、天花娘娘）",
    ("baiyunguan", "学业"): "文昌殿（文昌帝君）",
    ("baiyunguan", "健康"): "药王殿（药王）",
    ("baiyunguan", "财运"): "财神殿（财神）",
    ("miaofengshan", "求子"): "灵感宫（碧霞元君、子孙娘娘、送生娘娘）",
    ("miaofengshan", "姻缘"): "月老殿（月老）",
    ("miaofengshan", "财运"): "财神殿（三霄娘娘）",
    ("miaofengshan", "健康"): "药王殿（药王）",
    ("miaofengshan", "学业"): "文昌殿（文昌帝君）",
    ("dongyuemiao", "姻缘"): "西路月老殿（月老）",
    ("dongyuemiao", "健康"): "药王殿（药王）",
    ("dongyuemiao", "学业"): "后罩楼文昌殿（文昌帝君）",
    ("huodeshenmiao", "财运"): "财神殿",
}


# 用户嘴里的叫法（常见简称/别名），否则问「孔庙」会查不到
ALIASES = {
    "kongmiao": ["孔庙", "国子监", "北京孔庙", "孔庙国子监"],
    "wutasi": ["石刻博物馆", "北京石刻艺术博物馆", "真觉寺金刚宝座塔"],
    "wanshousi": ["北京艺术博物馆", "万寿寺博物馆"],
    "huodeshenmiao": ["火神庙", "什刹海火神庙", "火德庙"],
    "cishousi": ["玲珑塔", "玲珑公园"],
    "dajuesi": ["大觉寺与团城"],
    "dongyuemiao": ["北京民俗博物馆", "民俗博物馆"],
    "zhihuasi": ["文博交流馆"],
    "dazhongsi": ["古钟博物馆", "觉生寺"],
    "miaoyingsi": ["白塔", "白塔寺"],
    "yunjusi": ["石经山"],
    "baiyunguan": ["白云观"],
    "tianningsi": ["天宁寺塔"],
    "lidaidiwangmiao": ["帝王庙"],
    "fahaisi": ["法海寺壁画"],
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
    verified_urls: dict[str, bool] = {}
    added = 0

    for t in data["temples"]:
        tid = t["id"]

        # 1) place_facts
        facts = t.get("place_facts") or []
        for fact in WWJ_FACTS.get(tid, []):
            url = fact["source"]
            if url not in verified_urls:
                verified_urls[url] = check(url)
            if not verified_urls[url]:
                continue
            facts.append({**fact, "checked_at": TODAY})
            added += 1
        t["place_facts"] = facts

        # 2) 新来源并入 sources（只收可核 URL）
        known = {s["url"] for s in t.get("sources", [])}
        for fact in facts:
            url = fact.get("source")
            if url and url not in known and verified_urls.get(url, False):
                t["sources"].append({
                    "url": url,
                    "publisher": "北京市文物局" if "wwj.beijing.gov.cn" in url else "孔庙和国子监博物馆官网",
                    "kind": "official",
                    "checked_at": TODAY,
                })
                known.add(url)
        if t["sources"]:
            t["sources_status"] = "verified"

        # 3) 心愿：拆成 claim（民俗说法）+ basis（场所事实）
        for w in t.get("wish_themes", []):
            key = (tid, w["theme"])
            w["claim"] = CLAIM_TEXT.get(key) or w.get("note", "")
            w["claim_evidence"] = "reference" if w.get("evidence_type") == "reference" else "folk"
            w["basis"] = BASIS.get(key, "")
            # 场所事实的出处：优先用这条心愿自己的链接，否则用该寺庙已核实的来源
            w["basis_source"] = w.get("source_url", "") if w["basis"] else ""
            if w["basis"] and not w["basis_source"] and t["sources"]:
                w["basis_source"] = t["sources"][0]["url"]
            w.pop("evidence_type", None)
            w.pop("note", None)

        # 4) 常见叫法（用户不会说全称）
        aliases = list(dict.fromkeys((t.get("aliases") or []) + ALIASES.get(tid, [])))
        t["aliases"] = aliases

        # 5) 公众号只作渠道
        t["finder_hint"] = FINDER.get(tid, [])
        t["checked_at"] = TODAY

    data["meta"]["schema_version"] = "v3"
    data["meta"]["checked_at"] = TODAY
    data["meta"]["updated_at"] = TODAY
    data["meta"]["source_policy"] = (
        "sources 只放可程序核验的网页（政府/官网/协会），带核对日期；"
        "微信公众号等无法核验的渠道放进 finder_hint（去哪问），不作为引用。"
    )
    data["meta"]["evidence_policy"] = (
        "依据分两层：place_facts 是可核的场所事实；wish_themes[].claim 是「人们来求什么」的民俗用法，"
        "不因为殿宇有文献记载就把民俗升格为事实。"
    )
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = data["temples"]
    print("place_facts added:", added)
    print("verified:", sum(1 for r in rows if r["sources_status"] == "verified"),
          "| unverified:", sum(1 for r in rows if r["sources_status"] != "verified"))
    print("unverified:", "、".join(r["name"] for r in rows if r["sources_status"] != "verified"))
    from collections import Counter
    print("claim_evidence:", dict(Counter(w["claim_evidence"] for r in rows for w in r["wish_themes"])))
    print("wishes with basis:", sum(1 for r in rows for w in r["wish_themes"] if w["basis"]),
          "/", sum(len(r["wish_themes"]) for r in rows))


if __name__ == "__main__":
    main()
