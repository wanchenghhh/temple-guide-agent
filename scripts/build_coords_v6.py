"""schema v6：给寺庙加坐标，并生成「常见出发地坐标表」。

坐标来源只有两个，都可复核：
* 维基百科坐标（API `prop=coordinates`）
* 维基数据 P625（对应条目无坐标时）

没有可靠坐标的（云居寺、和平寺）**留空**——检索层会诚实退回「按区县」，
绝不按印象补一个数字。大悲寺取八大处公园坐标（园内步行约数百米），单独标注。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()
P = Path("app/agent/domain/temples.json")
O = Path("app/agent/domain/origins.json")

W = "https://zh.wikipedia.org/wiki/"
WD = "https://www.wikidata.org/wiki/"

# id: (lat, lng, 说明, 来源)
TEMPLE_COORDS = {
    "yonghegong": (39.94694, 116.41111, "", W + "%E9%9B%8D%E5%92%8C%E5%AE%AB"),
    "guanghuasi": (39.94104, 116.3905, "", W + "%E5%B9%BF%E5%8C%96%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%E5%B8%82%29"),
    "zhihuasi": (39.91616, 116.42588, "", W + "%E6%99%BA%E5%8C%96%E5%AF%BA"),
    "miaoyingsi": (39.92389, 116.35694, "", W + "%E5%A6%99%E5%BA%94%E5%AF%BA"),
    "guangjisi": (39.92425, 116.37245, "", W + "%E5%B9%BF%E6%B5%8E%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%E5%B8%82%29"),
    "tianningsi": (39.89511, 116.34593, "取天宁寺塔坐标（塔在寺内）", W + "%E5%A4%A9%E5%AE%81%E5%AF%BA%E5%A1%94%20%28%E5%8C%97%E4%BA%AC%29"),
    "lidaidiwangmiao": (39.92361, 116.36125, "", W + "%E5%8E%86%E4%BB%A3%E5%B8%9D%E7%8E%8B%E5%BA%99"),
    "kongmiao": (39.94511, 116.40831, "", W + "%E5%8C%97%E4%BA%AC%E5%AD%94%E5%BA%99"),
    "dongyuemiao": (39.92361, 116.43778, "", W + "%E5%8C%97%E4%BA%AC%E4%B8%9C%E5%B2%B3%E5%BA%99"),
    "huodeshenmiao": (39.93546, 116.38936, "", W + "%E5%9C%B0%E5%AE%89%E9%97%A8%E7%81%AB%E7%A5%9E%E5%BA%99"),
    "baiyunguan": (39.8989, 116.338, "", W + "%E7%99%BD%E4%BA%91%E8%A7%82"),
    "fayuansi": (39.88484, 116.36963, "", W + "%E6%B3%95%E6%BA%90%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%29"),
    "wanshousi": (39.94528, 116.30523, "", W + "%E4%B8%87%E5%AF%BF%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%29"),
    "dazhongsi": (39.96876, 116.33794, "", W + "%E5%A4%A7%E9%92%9F%E5%AF%BA"),
    "wutasi": (39.94492, 116.33035, "", W + "%E7%9C%9F%E8%A7%89%E5%AF%BA"),
    "dahuisi": (39.9531, 116.3295, "", W + "%E5%A4%A7%E6%85%A7%E5%AF%BA"),
    "cishousi": (39.92662, 116.28933, "", W + "%E6%85%88%E5%AF%BF%E5%AF%BA%E5%A1%94"),
    "wofosi": (40.00727, 116.20683, "", W + "%E5%8D%81%E6%96%B9%E6%99%AE%E8%A7%89%E5%AF%BA"),
    "dajuesi": (40.05247, 116.10657, "", W + "%E5%A4%A7%E8%A7%89%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%29"),
    "fahaisi": (39.94255, 116.1599, "", W + "%E6%B3%95%E6%B5%B7%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%E5%B8%82%29"),
    "biyunsi": (39.99601, 116.18585, "", W + "%E7%A2%A7%E4%BA%91%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%E5%B8%82%29"),
    "lingguangsi": (39.95252, 116.18161, "", W + "%E7%81%B5%E5%85%89%E5%AF%BA%20%28%E5%8C%97%E4%BA%AC%29"),
    "miaofengshan": (39.9757, 116.05024, "", W + "%E5%A6%99%E5%B3%B0%E5%B1%B1"),
    "tongjiaosi": (39.94429, 116.42626, "", W + "%E9%80%9A%E6%95%99%E5%AF%BA"),
    "dabeisi": (39.9537, 116.18, "取八大处公园坐标，寺在园内需步行", W + "%E5%85%AB%E5%A4%A7%E5%A4%84"),
    "tanzhesi": (39.90417, 116.02417, "", WD + "Q1815062"),
    "jietaisi": (39.86888, 116.08025, "", WD + "Q1688939"),
    "hongluosi": (40.37259, 116.6203, "", WD + "Q2406089"),
    # 没有可靠坐标：留空，检索层诚实退回「按区县」
    "yunjusi": None,
    "hepingsi": None,
}

# 常见出发地：(名称, 别名, lat, lng, 来源)
ORIGINS = [
    ("国贸", ["国贸站", "CBD", "建外", "大望路"], 39.90769, 116.45438, W + "%E5%9B%BD%E8%B4%B8%E7%AB%99%20%28%E5%8C%97%E4%BA%AC%E5%B8%82%29"),
    ("五道口", ["五道口站", "清华东路"], 39.99287, 116.33757, W + "%E4%BA%94%E9%81%93%E5%8F%A3%E7%AB%99"),
    ("西二旗", ["西二旗站"], 40.05159, 116.30008, W + "%E8%A5%BF%E4%BA%8C%E6%97%97%E7%AB%99"),
    ("望京", ["望京站"], 39.99657, 116.46243, WD + "Q10875105"),
    ("中关村", ["中关村站", "海淀黄庄"], 39.98117, 116.30894, WD + "Q197774"),
    ("天通苑", ["天通苑站", "天通苑北"], 40.0689, 116.4178, WD + "Q16923114"),
    ("奥林匹克公园", ["奥森", "奥林匹克森林公园"], 40.00303, 116.38667, WD + "Q1338919"),
    ("三里屯", ["三里屯酒吧街", "工体北路"], 39.93472, 116.44986, W + "%E4%B8%89%E9%87%8C%E5%B1%AF%E9%85%92%E5%90%A7%E8%A1%97"),
    ("北京南站", ["南站"], 39.86361, 116.37278, W + "%E5%8C%97%E4%BA%AC%E5%8D%97%E7%AB%99"),
    ("北京西站", ["西站"], 39.89356, 116.3157, W + "%E5%8C%97%E4%BA%AC%E8%A5%BF%E7%AB%99"),
    ("首都机场", ["首都国际机场", "T3", "T2"], 40.08, 116.58444, W + "%E5%8C%97%E4%BA%AC%E9%A6%96%E9%83%BD%E5%9B%BD%E9%99%85%E6%9C%BA%E5%9C%BA"),
    ("通州北苑", ["通州"], 39.90274, 116.63134, W + "%E9%80%9A%E5%B7%9E%E5%8C%97%E8%8B%91%E7%AB%99"),
    ("苹果园", ["苹果园站", "苹果园地铁"], 39.92491, 116.17178, W + "%E8%8B%B9%E6%9E%9C%E5%9B%AD%E7%AB%99"),
    ("石景山游乐园", ["石景山游乐园站"], 39.913, 116.202, W + "%E7%9F%B3%E6%99%AF%E5%B1%B1%E6%B8%B8%E4%B9%90%E5%9B%AD"),
]


def main() -> None:
    data = json.loads(P.read_text(encoding="utf-8"))
    with_coord = 0
    for t in data["temples"]:
        c = TEMPLE_COORDS.get(t["id"])
        if c is None:
            t["lat"] = None
            t["lng"] = None
            t["coord_note"] = "暂未取到可靠坐标，距离按区县估算"
            t["coord_source"] = ""
            continue
        lat, lng, note, src = c
        t["lat"], t["lng"] = lat, lng
        t["coord_note"] = note
        t["coord_source"] = src
        with_coord += 1

    data["meta"]["schema_version"] = "v6"
    data["meta"]["updated_at"] = TODAY
    data["meta"]["coord_policy"] = (
        "坐标仅取自维基百科坐标接口或维基数据 P625；取不到就留空，"
        "距离计算退回区县并明确告知用户，绝不按印象补数字。"
    )
    P.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    origins = {
        "meta": {
            "city": "北京",
            "schema_version": "v1",
            "updated_at": TODAY,
            "note": "常见出发地坐标表：只收北京常用的出发地点。用户说的地点不在这张表里时，"
                    "系统按区县给候选并说明原因，不猜坐标。",
            "source_policy": "坐标取自维基百科坐标接口或维基数据 P625，可逐条复核。",
        },
        "origins": [
            {"name": n, "aliases": a, "lat": lat, "lng": lng, "source": s}
            for n, a, lat, lng, s in ORIGINS
        ],
    }
    O.write_text(json.dumps(origins, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"temples coords: {with_coord}/{len(data['temples'])}"
          f"（留空: {[t['name'] for t in data['temples'] if t['lat'] is None]}）")
    print(f"origins: {len(origins['origins'])}")


if __name__ == "__main__":
    main()
