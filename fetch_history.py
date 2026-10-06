#!/usr/bin/env python3
"""커버드콜 vs 짝꿍 일반 ETF 시뮬레이터용 장기 이력 수집 → history.json.

2026-10-06 추가. data.json(배당 정보표)과 별개로, 시뮬레이터 페이지가 쓰는 월별 종가·분배금
전체 이력을 만든다. fetch_data.py의 KIS 호출 함수를 그대로 재사용하고 data.json은 건드리지 않음.

- 대상: data.json의 월배당 커버드콜 전 종목 + cc_pairs.json에 지정된 짝꿍 일반 ETF.
- 짝꿍 매칭(cc_pairs.json)은 KRX 기초지수명을 보고 사람이 정한 것:
    A = 같은 기초자산 일반 ETF, B = 비슷한 기초자산(근사 비교), C = 주식+채권 혼합형 등 공정한 짝 없음.
  짝꿍은 같은 운용사가 아니라 그 기초자산의 대표 ETF(순자산 최대)로 통일(사용자 결정).
  cc_pairs.json에 없는 신규 커버드콜은 grade=null로 넣고 로그에 경고 → 사람이 매칭 추가.
- 종가는 원주가(수정주가 아님), 분배금은 기준일(record_date) 월 기준.
"""
import json
import time

from fetch_data import fetch_dividends, fetch_monthly_closes, month_ends

LOOKBACK_MONTHS = 96  # 월봉 한 번 조회 최대 100행 이내


def main():
    months = month_ends(LOOKBACK_MONTHS)
    with open("data.json", encoding="utf-8") as f:
        cc = {e["code"]: e["name"] for e in json.load(f)["etfs"]}
    with open("cc_pairs.json", encoding="utf-8") as f:
        pairs_cfg = json.load(f)

    pairs, names = [], dict(cc)
    for code, name in cc.items():
        p = pairs_cfg["pairs"].get(code)
        if not p:
            print(f"  [경고] 짝꿍 미지정: {name} ({code}) — cc_pairs.json에 추가 필요", flush=True)
            p = {"pair": None, "grade": None, "memo": "짝꿍 미지정"}
        pairs.append({"code": code, "pair": p["pair"], "grade": p["grade"], "memo": p.get("memo", "")})
        if p["pair"]:
            names[p["pair"]] = pairs_cfg["pair_names"][p["pair"]]

    series = {}
    for code, name in names.items():
        closes = fetch_monthly_closes(code, months)
        time.sleep(0.25)
        divs = fetch_dividends(code, months)
        time.sleep(0.25)
        if not closes:
            print(f"  [skip] {name} ({code}) 주가 없음", flush=True)
            continue
        m = sorted(closes)
        series[code] = {"name": name, "m": m, "c": [closes[x] for x in m],
                        "d": [round(divs.get(x, 0.0), 1) for x in m]}
        print(f"  ✓ {name[:34]:34} {m[0]}~{m[-1]} {len(m)}개월 분배 {sum(1 for x in m if divs.get(x))}회", flush=True)

    out = {
        "generated": months[-1][2],
        "notes": {
            "c": "월말 종가(원주가, 진행 중인 달은 최근 종가)",
            "d": "그 달 기준일(record_date) 주당 분배금 합(세전, 원)",
            "grade": "A 같은 기초자산 / B 근사 비교 / C 공정한 짝 없음(혼합형 등)",
        },
        "pairs": pairs,
        "series": series,
    }
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"history.json 저장: 커버드콜 {len(cc)}종, 시계열 {len(series)}종", flush=True)


if __name__ == "__main__":
    main()
