#!/usr/bin/env python3
"""커버드콜 ETF 월배당 비교 대시보드 데이터 수집.

2년 전 월말(또는 상장 직후)에 각 ETF에 1억원을 일시금 매수(buy & hold),
분배금은 현금 수령(재투자 X, 세전). 매월말 기준: 평가액(자본) / 누적 수령배당(소득)
분리, KODEX 200(069500)과 비교.

데이터 소스
  - 커버드콜 ETF 목록: KRX data-dbg  /svc/apis/etp/etf_bydd_trd  (AUTH_KEY 헤더)
      → 이름에 "커버드콜"이 들어간 전 종목을 여기서 발견한다. (예탁원 배당피드의
        무필터 조회는 페이지네이션이 사실상 안 돼서 첫 100건만 읽혔고, 종목코드
        정렬상 커버드콜 ETF가 뒤라 매달 상당수가 누락됐었음 — 2026-09 수정.)
  - 분배금: KIS  /uapi/domestic-stock/v1/ksdinfo/dividend  (tr_id HHKDB669102C0)
      → 종목코드(SHT_CD)를 지정하면 24개월 범위를 한 번에 완전하게 돌려준다.
  - 월말주가: KIS  /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
      (tr_id FHKST03010100, 기간=M, 원주가)

환경변수: KIS_APP_KEY, KIS_APP_SECRET, KRX_AUTH_KEY
"""
import os
import json
import time
import datetime
import requests

KIS_URL = "https://openapivts.koreainvestment.com:29443"
KRX_URL = "https://data-dbg.krx.co.kr/svc/apis"
APP = os.environ["KIS_APP_KEY"]
SEC = os.environ["KIS_APP_SECRET"]
KRX_KEY = os.environ["KRX_AUTH_KEY"]
PRINCIPAL = 100_000_000
LOOKBACK_MONTHS = 24
BENCH_CODE = "069500"
BENCH_NAME = "KODEX 200"

NAME_KEYS = ("커버드콜",)
# 월배당 판정: 분배를 시작한 뒤의 "완결된 달"(진행 중인 이번 달 제외) 중 이 비율 이상에서
# 분배 실적이 있어야 한다. 분기배당(≈0.33)·격월(≈0.5)은 자연히 걸러지고, 매달 주는데
# 한두 달 건너뛴 종목(예: TIGER 200커버드콜 14개월 중 11회)은 통과한다.
MONTHLY_HIT_RATIO = 0.70
MIN_DIST = 2  # 최소 분배 횟수 (신규 상장 종목도 몇 달치만 있으면 포함)


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


def _kis_get(path, tr_id, params, tr_cont=""):
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


def _krx_get(path, params):
    for attempt in range(4):
        try:
            r = requests.get(f"{KRX_URL}/{path}", headers={"AUTH_KEY": KRX_KEY}, params=params, timeout=25)
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"  KRX 재시도({e})", flush=True); time.sleep(3)
    raise RuntimeError(f"KRX {path} 요청 실패")


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


def discover_covered_call_etfs():
    """KRX ETP 일별시세에서 이름에 '커버드콜'이 든 전 종목을 찾는다. {code: name}"""
    d = datetime.date.today()
    for _ in range(7):
        d -= datetime.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        j = _krx_get("etp/etf_bydd_trd", {"basDd": d.strftime("%Y%m%d")})
        rows = j.get("OutBlock_1") or []
        if rows:
            break
    else:
        raise RuntimeError("KRX ETF 목록을 못 받음")
    out = {}
    for x in rows:
        nm = (x.get("ISU_NM") or "").strip()
        cd = (x.get("ISU_CD") or "").strip()
        if cd and any(k in nm for k in NAME_KEYS):
            out[cd] = nm
    return out


def fetch_dividends(code, months):
    """종목코드 지정 분배 이력을 24개월 범위 한 번에 조회. {'YYYY-MM': 주당분배금_합} (record_date 기준)."""
    f_dt, t_dt = months[0][0], datetime.date.today().strftime("%Y%m%d")

    def _one(f, t):
        r = _kis_get("/uapi/domestic-stock/v1/ksdinfo/dividend", "HHKDB669102C0",
                     {"CTS": "", "GB1": "0", "F_DT": f, "T_DT": t, "SHT_CD": code, "HIGH_GB": ""})
        rows = r.json().get("output1") or []
        rows = rows if isinstance(rows, list) else [rows]
        return rows, r.headers.get("tr_cont", "")

    rows, tc = _one(f_dt, t_dt)
    # 방어: 혹시 한 번에 안 담기면(주당분배 100건↑ = 사실상 없음) 월별로 쪼개 다시.
    if tc == "F" or len(rows) >= 100:
        rows = []
        for f, t, _ in months:
            r2, _ = _one(f, t)
            rows.extend(r2)
            time.sleep(0.15)

    by_month = {}
    for row in rows:
        amt = row.get("per_sto_divi_amt")
        rd = row.get("record_date") or ""
        if len(rd) < 6 or amt is None or not str(amt).replace(".", "").isdigit():
            continue
        ym = f"{rd[:4]}-{rd[4:6]}"
        by_month[ym] = by_month.get(ym, 0.0) + float(amt)
    return by_month


def fetch_monthly_closes(code, months):
    """월봉 종가. {'YYYY-MM': close_price}  (없으면 빈 dict)"""
    f_dt = months[0][0]
    t_dt = datetime.date.today().strftime("%Y%m%d")
    r = _kis_get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100",
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


def is_monthly_payer(by_month, months):
    """분배 시작 이후의 '완결된 달'(이번 달 제외) 기준으로 월배당 여부를 본다."""
    if len(by_month) < MIN_DIST:
        return False
    cur_ym = datetime.date.today().strftime("%Y-%m")
    complete = [ym for _, _, ym in months if ym != cur_ym]
    first_div = min(by_month)
    active = [ym for ym in complete if ym >= first_div]
    if len(active) < 2:
        # 분배가 2건 이상인데 완결월이 1개 이하 = 이번 달에 몰림 → 다음 달 갱신 때 판정
        return len(by_month) >= MIN_DIST and len(active) >= 1
    hit = sum(1 for ym in active if ym in by_month)
    recent2 = active[-2:]
    still_active = any(ym in by_month for ym in recent2)
    return still_active and hit / len(active) >= MONTHLY_HIT_RATIO


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
        month_div = shares * divs_by_month.get(ym, 0.0)
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

    cur_ym = datetime.date.today().strftime("%Y-%m")
    complete = [s for s in series if s["month"] != cur_ym]
    last = series[-1]
    yrs = max(len(series) - 1, 1) / 12.0

    # 월배당(세전·1억당): "분배를 시작한 달"부터의 완결월(이번 달 제외) 중 최근 12개의
    # 실제 분배 총액 ÷ 그 개월수 (중간에 분배 0인 달은 포함, 시작 전 0인 달은 제외).
    pay_ms = [s["month"] for s in series if s["month_div"] > 0]
    first_pay = pay_ms[0] if pay_ms else (complete[0]["month"] if complete else series[0]["month"])
    win = [s for s in complete if s["month"] >= first_pay][-12:]
    if not win:
        win = complete[-12:] if complete else series[-12:]
    avg_monthly_div = round(sum(s["month_div"] for s in win) / len(win)) if win else 0
    pay_months = sum(1 for s in win if s["month_div"] > 0)

    # "지금 매수 시" 추정용: 최근 12완결월 주가 평균, 가장 최근 실제 분배월의 주당 분배금.
    price_win = [s["price"] for s in complete][-12:] or [s["price"] for s in series][-12:]
    price_avg_12m = round(sum(price_win) / len(price_win), 1) if price_win else None
    last_div_row = next((s for s in reversed(complete) if s["month_div"] > 0),
                        next((s for s in reversed(series) if s["month_div"] > 0), None))
    div_ps_last = round(last_div_row["month_div"] / shares, 1) if (last_div_row and shares) else None

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
            "entry_price": round(closes[start_ym], 1),
            "cur_price": last["price"],
            "price_avg_12m": price_avg_12m,
            "div_ps_last": div_ps_last,
            "div_per_share_month_12m": round(avg_monthly_div / shares, 1) if shares else 0,
            # 매입가 대비 연 배당률 = 최근 12완결월 월평균 분배(0인 달 포함) × 12 ÷ 매입원금.
            # = (주당 월평균 분배 ÷ 매입단가) × 12 와 동일. 상담에서 "그때 사셨으면 매입가 대비 연 N%".
            "yoc_ann_pct": round(avg_monthly_div * 12 / PRINCIPAL * 100, 2),
            # 현재가 대비 연 배당률 = 같은 월평균 분배 × 12 ÷ 현재 평가액.
            # = (주당 월평균 분배 ÷ 현재 주당가) × 12. "지금 사시면 현재가 대비 연 N%".
            "fwd_yield_ann_pct": round(avg_monthly_div * 12 / last["nav"] * 100, 2) if last["nav"] else 0,
            "avg_monthly_div_12m": avg_monthly_div,
            "pay_months_12m": pay_months,
            "win_months": len(win),
            "months_held": len(series),
        },
    }


def main():
    months = month_ends(LOOKBACK_MONTHS)
    common_start = months[0][2]
    print(f"기간 {months[0][2]} ~ {months[-1][2]}  (일시금 기준월 {common_start})", flush=True)

    universe = discover_covered_call_etfs()
    print(f"KRX 커버드콜 ETF {len(universe)}종 발견", flush=True)

    bench_div = fetch_dividends(BENCH_CODE, months)
    time.sleep(0.3)
    bench_closes = fetch_monthly_closes(BENCH_CODE, months)
    time.sleep(0.3)
    bench_sim = simulate(bench_closes, bench_div, months, common_start)

    n_month, n_price = 0, 0
    etfs = []
    for code, name in sorted(universe.items(), key=lambda kv: kv[1]):
        divs = fetch_dividends(code, months)
        time.sleep(0.25)
        if not is_monthly_payer(divs, months):
            continue
        n_month += 1
        closes = fetch_monthly_closes(code, months)
        time.sleep(0.25)
        if not closes:
            print(f"  [skip] {name} ({code}) 주가 없음", flush=True)
            continue
        avail = [ym for _, _, ym in months if ym in closes]
        start_ym = common_start if common_start in closes else (avail[0] if avail else None)
        if not start_ym:
            continue
        sim = simulate(closes, divs, months, start_ym)
        if not sim:
            print(f"  [skip] {name} 시뮬 실패", flush=True)
            continue
        n_price += 1
        bench_same = simulate(bench_closes, bench_div, months, start_ym)
        sim["bench_total_ret_pct"] = bench_same["summary"]["total_ret_pct"] if bench_same else None
        sim["bench_total_ret_ann_pct"] = bench_same["summary"]["total_ret_ann_pct"] if bench_same else None
        sim["summary"]["vs_bench_pct"] = (
            round(sim["summary"]["total_ret_pct"] - bench_same["summary"]["total_ret_pct"], 2)
            if bench_same else None
        )
        etfs.append({
            "code": code,
            "name": name,
            "start_month": start_ym,
            "full_2y": start_ym == common_start,
            **sim,
        })
        s = sim["summary"]
        print(f"  ✓ {name[:36]:36} 시작 {start_ym}  총수익 {s['total_ret_pct']:+.1f}%  "
              f"월배당 {s['avg_monthly_div_12m']:,} ({s['pay_months_12m']}/{s['win_months']})", flush=True)

    print(f"\n커버드콜 {len(universe)}종 → 월배당 {n_month}종 → 시뮬 완료 {len(etfs)}종", flush=True)

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
    print(f"data.json 저장 ({len(etfs)}종 + 벤치마크)", flush=True)


if __name__ == "__main__":
    main()
