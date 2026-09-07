#!/usr/bin/env python3
"""커버드콜 ETF 월배당 비교 대시보드 데이터 수집.

2년 전 월말에 각 ETF에 1억원을 일시금 매수(buy & hold), 분배금은 현금 수령(재투자 X, 세전).
매월말 기준: 평가액(자본) / 누적 수령배당(소득) 분리, KODEX 200(069500)과 비교.

데이터 소스: KIS Open API (모의투자 도메인, paper key)
  - 분배금: /uapi/domestic-stock/v1/ksdinfo/dividend  (tr_id HHKDB669102C0)
  - 월말주가: /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice (tr_id FHKST03010100, M)

환경변수: KIS_APP_KEY, KIS_APP_SECRET  (GitHub Actions secrets / 로컬 .env)
"""
import os
import sys
import json
import time
import datetime
import requests

KIS_URL = "https://openapivts.koreainvestment.com:29443"
APP = os.environ["KIS_APP_KEY"]
SEC = os.environ["KIS_APP_SECRET"]
PRINCIPAL = 100_000_000
LOOKBACK_MONTHS = 24
BENCH_CODE = "069500"
BENCH_NAME = "KODEX 200"

# "커버드콜" 이름 필터에 더해, 월배당(최근 6개월 중 5개월+ 분배 실적)인 종목만 남긴다.
NAME_KEYS = ("커버드콜",)


def _token():
    for attempt in range(4):
        r = requests.post(f"{KIS_URL}/oauth2/tokenP",
                          json={"grant_type": "client_credentials", "appkey": APP, "appsecret": SEC},
                          timeout=15)
        j = r.json()
        if j.get("access_token"):
            return j["access_token"]
        print(f"  토큰 재시도 {attempt+1}: {j.get('error_description')}", flush=True)
        time.sleep(62)
    raise RuntimeError("KIS 토큰 발급 실패")


TOKEN = _token()


def _get(path, tr_id, params, tr_cont=""):
    h = {"authorization": f"Bearer {TOKEN}", "appkey": APP, "appsecret": SEC,
         "tr_id": tr_id, "custtype": "P", "tr_cont": tr_cont}
    for attempt in range(5):
        try:
            r = requests.get(f"{KIS_URL}{path}", headers=h, params=params, timeout=20)
            if r.status_code == 500:
                time.sleep(3); continue
            return r
        except requests.exceptions.RequestException as e:
            print(f"  요청 재시도({e})", flush=True); time.sleep(3)
    raise RuntimeError(f"{path} 요청 실패")


def month_ends(n):
    """최근 n개월의 (YYYYMMDD_first, YYYYMMDD_last, 'YYYY-MM') 리스트 (과거→현재)."""
    today = datetime.date.today()
    d = today.replace(day=1)
    out = []
    for _ in range(n):
        nxt = (d + datetime.timedelta(days=32)).replace(day=1)
        last = nxt - datetime.timedelta(days=1)
        out.append((d.strftime("%Y%m%d"), last.strftime("%Y%m%d"), d.strftime("%Y-%m")))
        d = (d - datetime.timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def fetch_all_dividends(months):
    """기간 전체 분배(배당) 일정을 월별로 조회. {sht_cd: {'name':.., 'by_month': {'YYYY-MM': amount_won}}}"""
    acc = {}
    for f_dt, t_dt, ym in months:
        cts, tr_cont = "", ""
        for _ in range(20):
            r = _get("/uapi/domestic-stock/v1/ksdinfo/dividend", "HHKDB669102C0",
                     {"CTS": cts, "GB1": "0", "F_DT": f_dt, "T_DT": t_dt, "SHT_CD": "", "HIGH_GB": ""}, tr_cont)
            j = r.json()
            rows = j.get("output1") or []
            if not isinstance(rows, list):
                rows = [rows]
            for row in rows:
                name = (row.get("isin_name") or "").strip()
                code = (row.get("sht_cd") or "").strip()
                amt = row.get("per_sto_divi_amt")
                rd = row.get("record_date") or ""
                if not code or not amt or not str(amt).replace(".", "").isdigit():
                    continue
                rec_ym = f"{rd[:4]}-{rd[4:6]}" if len(rd) >= 6 else ym
                e = acc.setdefault(code, {"name": name, "by_month": {}})
                if name and not e["name"]:
                    e["name"] = name
                e["by_month"][rec_ym] = e["by_month"].get(rec_ym, 0.0) + float(amt)
            tc = r.headers.get("tr_cont", "")
            if tc in ("F", "M") and rows:
                nc = rows[-1].get("CTS") or rows[-1].get("cts") or ""
                if not nc or nc == cts:
                    break
                cts, tr_cont = nc, "N"
                time.sleep(0.35)
            else:
                break
        time.sleep(0.4)
    return acc


def fetch_monthly_closes(code, months):
    """월봉 종가. {'YYYY-MM': close_price}  (없으면 빈 dict)"""
    f_dt = months[0][0]
    t_dt = datetime.date.today().strftime("%Y%m%d")
    r = _get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100",
             {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
              "FID_INPUT_DATE_1": f_dt, "FID_INPUT_DATE_2": t_dt,
              "FID_PERIOD_DIV_CODE": "M", "FID_ORG_ADJ_PRC": "1"})
    j = r.json()
    out = {}
    for row in (j.get("output2") or []):
        dt = row.get("stck_bsop_date") or ""
        cl = row.get("stck_clpr")
        if len(dt) >= 6 and cl and str(cl).replace(".", "").isdigit():
            out[f"{dt[:4]}-{dt[4:6]}"] = float(cl)
    return out


def is_monthly_payer(by_month, months_present):
    """최근 6개월(또는 상장 후 개월수) 중 80% 이상 분배 실적이면 월배당으로 본다."""
    recent = [ym for _, _, ym in months_present][-6:]
    hit = sum(1 for ym in recent if ym in by_month)
    return len(recent) >= 2 and hit / len(recent) >= 0.8


def simulate(closes, divs_by_month, months, start_ym):
    """start_ym 월말에 PRINCIPAL 매수. 이후 매월말 시계열."""
    if start_ym not in closes:
        return None
    shares = PRINCIPAL / closes[start_ym]
    series = []
    cum_div = 0.0
    started = False
    for _, _, ym in months:
        if ym == start_ym:
            started = True
        if not started:
            continue
        px = closes.get(ym)
        if px is None:
            continue
        mdiv_ps = divs_by_month.get(ym, 0.0)
        month_div = shares * mdiv_ps
        cum_div += month_div
        nav = shares * px
        series.append({
            "month": ym,
            "price": round(px, 1),
            "nav": round(nav),
            "month_div": round(month_div),
            "cum_div": round(cum_div),
            "total": round(nav + cum_div),
        })
    if len(series) < 2:
        return None
    last = series[-1]
    yrs = max(len(series) - 1, 1) / 12.0
    div_events = [s["month_div"] for s in series if s["month_div"] > 0][-12:]
    total_ret = last["total"] / PRINCIPAL - 1
    nav_ret = last["nav"] / PRINCIPAL - 1
    return {
        "shares": round(shares, 2),
        "start_month": start_ym,
        "series": series,
        "summary": {
            "nav_now": last["nav"],
            "cum_div_now": last["cum_div"],
            "total_now": last["total"],
            "nav_ret_pct": round(nav_ret * 100, 2),
            "div_ret_pct": round(last["cum_div"] / PRINCIPAL * 100, 2),
            "total_ret_pct": round(total_ret * 100, 2),
            "nav_ret_ann_pct": round(((1 + nav_ret) ** (1 / yrs) - 1) * 100, 2),
            "total_ret_ann_pct": round(((1 + total_ret) ** (1 / yrs) - 1) * 100, 2),
            "income_yield_ann_pct": round(last["cum_div"] / PRINCIPAL / yrs * 100, 2),
            "preservation_pct": round(last["nav"] / PRINCIPAL * 100, 2),
            "avg_monthly_div_12m": round(sum(div_events) / len(div_events)) if div_events else 0,
            "months_held": len(series),
        },
    }


def main():
    months = month_ends(LOOKBACK_MONTHS)
    common_start = months[0][2]
    print(f"기간 {months[0][2]} ~ {months[-1][2]}  (일시금 기준월 {common_start})", flush=True)

    print("분배금 일정 수집...", flush=True)
    all_div = fetch_all_dividends(months)
    print(f"  전체 분배 종목 {len(all_div)}건", flush=True)

    # 커버드콜 + 월배당 필터
    cand = {c: v for c, v in all_div.items() if any(k in v["name"] for k in NAME_KEYS)}
    targets = {c: v for c, v in cand.items() if is_monthly_payer(v["by_month"], months)}
    print(f"  커버드콜 {len(cand)}종 → 월배당 {len(targets)}종", flush=True)

    # 벤치마크 분배금(KODEX 200)
    bench_div = all_div.get(BENCH_CODE, {"by_month": {}})["by_month"]

    print("월말주가 수집...", flush=True)
    bench_closes = fetch_monthly_closes(BENCH_CODE, months)
    time.sleep(0.4)
    bench_sim = simulate(bench_closes, bench_div, months, common_start)

    etfs = []
    for code, v in sorted(targets.items(), key=lambda kv: kv[1]["name"]):
        closes = fetch_monthly_closes(code, months)
        time.sleep(0.4)
        if not closes:
            print(f"  [skip] {v['name']} ({code}) 주가 없음", flush=True)
            continue
        # 상장 2년 미만이면 첫 완전월부터
        avail = [ym for _, _, ym in months if ym in closes]
        start_ym = common_start if common_start in closes else (avail[0] if avail else None)
        if not start_ym:
            continue
        sim = simulate(closes, v["by_month"], months, start_ym)
        if not sim:
            print(f"  [skip] {v['name']} 시뮬 실패", flush=True)
            continue
        # 같은 시작월 기준 KODEX 200 총자산(종목별 기간 맞춘 벤치마크 비교)
        bench_same = simulate(bench_closes, bench_div, months, start_ym)
        sim["bench_total_ret_pct"] = bench_same["summary"]["total_ret_pct"] if bench_same else None
        sim["bench_total_ret_ann_pct"] = bench_same["summary"]["total_ret_ann_pct"] if bench_same else None
        sim["summary"]["vs_bench_pct"] = (
            round(sim["summary"]["total_ret_pct"] - bench_same["summary"]["total_ret_pct"], 2)
            if bench_same else None
        )
        etfs.append({
            "code": code,
            "name": v["name"],
            "start_month": start_ym,
            "full_2y": start_ym == common_start,
            **sim,
        })
        print(f"  ✓ {v['name'][:40]:40} 시작 {start_ym}  총수익 {sim['summary']['total_ret_pct']:+.1f}%  월배당 {sim['summary']['avg_monthly_div_12m']:,}", flush=True)

    out = {
        "generated": datetime.date.today().isoformat(),
        "principal": PRINCIPAL,
        "common_start_month": common_start,
        "assumptions": "2년 전 일시금 1억 매수·보유, 분배금 현금 수령(재투자 없음), 세전",
        "benchmark": {"code": BENCH_CODE, "name": BENCH_NAME, **(bench_sim or {})},
        "etfs": etfs,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\ndata.json 저장 ({len(etfs)}종 + 벤치마크)", flush=True)


if __name__ == "__main__":
    main()
