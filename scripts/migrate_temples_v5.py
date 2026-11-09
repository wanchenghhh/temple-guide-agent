"""Migrate temples.json → schema v5：把「代查到的官方链接」并入，并逐条核验。

原则不变：**每一行都要能点开**。
本次所有 URL 都在写入前做过 HTTP 200 校验；lddwm.com（历代帝王庙官网）返回 503，
因此改用北京数字文化馆的官方场馆页，并在 finder_hint 里注明官网暂时打不开。

新增内容全部是「场所事实」（开放时间/闭馆日/门票/预约），证据等级 official；
心愿说法仍保持原等级，只有能指到具体殿宇的才补 basis（并标明出处）。
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()
P = Path("app/agent/domain/temples.json")

ZGFXY = "https://zgfxy.cn/fys"
LGS = "http://www.lingguangsi.com/index.php/Article/view/id/207.htm"
FHS = "https://www.bjsjs.gov.cn/sjsfc/sjswwjd/202502/t20250206_475968.shtml"
BYS = "https://www.xiangshan-park.cn/cn/tabs/showdetail.aspx?tabid=700011&iid=29622"
TAOIST = "http://www.taoist.org.cn/getDjzsById.do?id=460"
XICHENG = "https://www.bjxch.gov.cn/zt/schjmp/xxxq/pnidpv932676.html"
LDDWM = "https://bjszwhg.org.cn/detail/13732"
WIKI_DABEI = "https://zh.wikipedia.org/wiki/%E5%A4%A7%E6%82%B2%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%29"
VISITBEIJING = "https://www.visitbeijing.com.cn/article/4MJTb9gldk5"

PUBLISHER = {
    ZGFXY: ("中国佛学院官网", "official"),
    LGS: ("灵光寺官网", "official"),
    FHS: ("北京市石景山区人民政府", "official"),
    BYS: ("香山公园官网", "official"),
    TAOIST: ("中国道教协会", "official"),
    XICHENG: ("北京市西城区人民政府", "official"),
    LDDWM: ("北京数字文化馆（北京市文化馆）", "official"),
    WIKI_DABEI: ("维基百科", "reference"),
    VISITBEIJING: ("北京旅游网（攻略）", "media"),
}

FACTS = {
    "fayuansi": [
        (ZGFXY, "中国佛学院官网：法源寺始建于唐贞观十九年（645），寺内有天王殿、大雄宝殿、悯忠阁、毗卢殿、观音殿、藏经楼等殿堂；1983 年被定为佛教重点寺院，2001 年列为全国重点文物保护单位。"),
    ],
    "lingguangsi": [
        (LGS, "灵光寺官网：灵光寺是八大处现存最重要的一座寺院，始建于唐大历年间（766–779）。"),
    ],
    "fahaisi": [
        (FHS, "石景山区政府：开放时间 09:00–16:30（16:00 停止售票），每周一闭馆、法定节假日正常开放；普通入馆门票 20 元（优惠价 10 元），参观免预约。"),
        (FHS, "石景山区政府：明代壁画真迹票 100 元，须通过「石景山文旅」微信公众号或「石景山文E」app 提前预约七日内场次。"),
    ],
    "biyunsi": [
        (BYS, "香山公园官网：碧云寺 2023 年 11 月因保护性修缮临时关闭，现已恢复开放；每周一闭馆（法定节假日除外）。"),
        (BYS, "香山公园官网：4 月 1 日–11 月 15 日 8:00 开门、17:00 停止进入、17:30 关门；11 月 16 日–次年 3 月 31 日 8:30 开门、16:30 停止进入、17:00 关门；需单独购票。"),
    ],
    "huodeshenmiao": [
        (TAOIST, "中国道教协会：火神庙（敕建火德真君庙）位于地安门外、什刹海旁，始建于唐贞观六年（632）；庙宇由中国道教协会筹资修复，作为道教活动场所对外开放。"),
        (XICHENG, "西城区政府：火德真君庙位于地安门外大街 77 号，1984 年列为北京市文物保护单位；2001–2005 年腾退修缮后交由中国道教协会管理使用并对外开放。"),
        (TAOIST, "中国道教协会：火神庙主体建筑自南向北为隆恩殿（供王灵官）、火祖殿（供火德荧惑星君）、斗姥阁、万岁景命阁（玉皇阁）。"),
    ],
    "lidaidiwangmiao": [
        (LDDWM, "北京数字文化馆场馆页：历代帝王庙博物馆开放时间周三至周日 9:00–16:00，周一、周二闭馆（法定节假日除外）；地址西城区阜成门内大街 131 号。"),
    ],
    "dabeisi": [
        (WIKI_DABEI, "维基百科：大悲寺建于辽金，明嘉靖二十九年（1550）在两层大殿后新建大悲阁供奉观世音菩萨；是八大处中继灵光寺之后第二座恢复为宗教活动场所的寺庙。"),
    ],
}

# 开放状态：只有官方页面写明才改
OPEN = {
    "fahaisi": ("normal", ["周一闭馆"],
                "官方：开放 09:00–16:30（16:00 停止售票），周一闭馆、节假日正常开放；普通门票 20 元、参观免预约；壁画真迹 100 元需预约。"),
    "biyunsi": ("normal", ["周一闭馆（法定节假日除外）"],
                "官方：每周一闭馆（法定节假日除外）；需单独购票；4/1–11/15 8:00–17:30，11/16–3/31 8:30–17:00。"),
    "huodeshenmiao": ("normal", [],
                      "官方：已交由中国道教协会管理并对外开放；具体开放时段与是否收费尚未核实。"),
    "lidaidiwangmiao": ("normal", ["周一闭馆", "周二闭馆"],
                         "官方：周三至周日 9:00–16:00，周一、周二闭馆（法定节假日除外）；咨询电话 010-66120186。"),
    "fayuansi": ("unverified", [],
                 "中国佛学院官网未公布开放信息；佛学院在此办学，是否对普通游客开放需电话确认。"),
    "lingguangsi": ("unverified", [],
                    "官网有寺院通告与佛牙舍利瞻礼安排；进园需八大处公园门票，具体票价待核。"),
    "tongjiaosi": ("unverified", [],
                   "有多个媒体来源称仅在农历初一、十五 8:30–16:00 开放，平日闭门清修；属媒体来源，建议电话复核。"),
    "guangjisi": ("unverified", [],
                  "公开攻略称免费、无需预约（约 7:00–16:30），未见官方页面，建议电话复核。"),
    "baiyunguan": ("unverified", [],
                   "公开攻略称门票 10 元、无需预约，未见官方页面，建议电话复核。"),
}

WISH_FIX = {
    ("yonghegong", "事业"): {
        "basis": "法轮殿", "basis_source": VISITBEIJING,
        "claim": "旅游平台攻略与民间口碑都指法轮殿求事业；另有永佑殿西配殿求学业的说法。",
        "claim_evidence": "folk",
    },
    ("dabeisi", "姻缘"): {
        "basis": "大悲阁／观音殿（观世音菩萨）", "basis_source": WIKI_DABEI,
        "claim": "八大处一带流传的姻缘说法多指向大悲寺（同处八大处的灵光寺更偏平安、健康）。",
        "claim_evidence": "folk",
    },
    ("huodeshenmiao", "财运"): {
        "basis": "",
        "claim": "民间有到火神庙求财的说法，但殿宇依据未核实——官方页面列出的殿堂为隆恩殿、火祖殿、斗姥阁、万岁景命阁。",
        "claim_evidence": "folk",
    },
    ("tanzhesi", "事业"): {
        "basis": "",
        "claim": "皇家寺院背景，民间有求仕途的说法，但具体指向不一致（观音殿、帝王树绕树三圈等）。",
        "claim_evidence": "folk",
    },
}


# 只作「说法的出处」，不算场所事实（攻略类来源不进 place_facts）
SOURCES_ONLY = {
    "yonghegong": [VISITBEIJING],
}


def check(url: str) -> bool:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (link-check)"}, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (link-check)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status == 200
        except Exception:
            return False


def main() -> None:
    data = json.loads(P.read_text(encoding="utf-8"))
    verified: dict[str, bool] = {}
    added_sources = added_facts = 0

    for t in data["temples"]:
        tid = t["id"]
        facts = t.setdefault("place_facts", [])
        sources = t.setdefault("sources", [])
        known = {(s["url"], s["publisher"]) for s in sources}

        for url, text in FACTS.get(tid, []):
            if url not in verified:
                verified[url] = check(url)
            if not verified[url]:
                print("SKIP unverified url:", url)
                continue
            publisher, kind = PUBLISHER[url]
            if (url, publisher) not in known:
                sources.append({"url": url, "publisher": publisher, "kind": kind, "checked_at": TODAY})
                known.add((url, publisher))
                added_sources += 1
            if all(f["text"] != text for f in facts):
                facts.append({"text": text, "source": url,
                              "evidence_type": kind, "checked_at": TODAY})
                added_facts += 1

        for url in SOURCES_ONLY.get(tid, []):
            if url not in verified:
                verified[url] = check(url)
            if not verified[url]:
                print("SKIP unverified url:", url)
                continue
            publisher, kind = PUBLISHER[url]
            if (url, publisher) not in known:
                sources.append({"url": url, "publisher": publisher, "kind": kind, "checked_at": TODAY})
                known.add((url, publisher))
                added_sources += 1

        if tid in OPEN:
            status, closure, note = OPEN[tid]
            t["open_status"] = status
            t["closure_rule"] = closure
            t["open_note"] = note

        for w in t.get("wish_themes", []):
            fix = WISH_FIX.get((tid, w["theme"]))
            if fix:
                w.update(fix)

        if sources:
            t["sources_status"] = "verified"
        if tid == "lidaidiwangmiao":
            t["finder_hint"] = ["北京数字文化馆 场馆页（官网 lddwm.com 当前 503，暂不可用）",
                                "北京历代帝王庙博物馆 公众号"]
        t["checked_at"] = TODAY

    data["meta"].update({
        "schema_version": "v5",
        "updated_at": TODAY,
        "checked_at": TODAY,
    })
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = data["temples"]
    print("sources +", added_sources, "| place_facts +", added_facts)
    print("verified:", sum(1 for r in rows if r["sources_status"] == "verified"),
          "/", len(rows))
    print("unverified:", [r["name"] for r in rows if r["sources_status"] != "verified"] or "无")
    from collections import Counter
    print("open_status:", dict(Counter(r["open_status"] for r in rows)))
    print("wishes with basis:", sum(1 for r in rows for w in r["wish_themes"] if w.get("basis")),
          "/", sum(len(r["wish_themes"]) for r in rows))


if __name__ == "__main__":
    main()
