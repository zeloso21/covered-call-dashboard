#!/usr/bin/env python3
"""커버드콜 ETF 월배당 비교 대시보드 데이터 수집 (단순 정보제공판).

종목별로 "최종배당시 주가 / 최종배당월 / 주가대비 연배당율 / 최근 6개월 배당액"만
보여준다. 1억 투자 시뮬레이션·KODEX200 비교는 없음(2026-09-13 전면 개편).

연배당율 = (최종배당월부터 6개월간 배당 합 × 2) ÷ 최종배당시 주가

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
LOOKBACK_MONTHS = 24
YIELD_WINDOW = 6  # 최종배당월부터 이만큼(포함) 역산해 연배당율/배당내역 산출

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


def shift_ym(ym, delta):
    """'YYYY-MM'에서 delta개월 이동(음수=과거)한 'YYYY-MM'."""
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12}-{idx % 12 + 1:02d}"


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


def build_summary(code, name, divs_by_month, closes):
    """최종배당월/그 시점 주가/연배당율/최근 6개월 배당내역."""
    paid = [ym for ym, amt in divs_by_month.items() if amt > 0]
    if not paid:
        return None
    last_div_month = max(paid)
    price = closes.get(last_div_month)
    if price is None:
        return None
    window_months = [shift_ym(last_div_month, -i) for i in range(YIELD_WINDOW - 1, -1, -1)]
    monthly_divs = [{"month": ym, "amount": round(divs_by_month.get(ym, 0.0), 1)} for ym in window_months]
    window_sum = sum(x["amount"] for x in monthly_divs)
    ann_yield_pct = round(window_sum * 2 / price * 100, 2)
    return {
        "code": code,
        "name": name,
        "last_div_month": last_div_month,
        "price_at_last_div": round(price, 1),
        "ann_yield_pct": ann_yield_pct,
        "monthly_divs": monthly_divs,
    }


def main():
    months = month_ends(LOOKBACK_MONTHS)
    print(f"기간 {months[0][2]} ~ {months[-1][2]}", flush=True)

    universe = discover_covered_call_etfs()
    print(f"KRX 커버드콜 ETF {len(universe)}종 발견", flush=True)

    n_month = 0
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
        summary = build_summary(code, name, divs, closes)
        if not summary:
            print(f"  [skip] {name} 요약 실패", flush=True)
            continue
        etfs.append(summary)
        print(f"  ✓ {name[:36]:36} 최종배당 {summary['last_div_month']}  "
              f"주가 {summary['price_at_last_div']:,}  연배당율 {summary['ann_yield_pct']:+.1f}%", flush=True)

    print(f"\n커버드콜 {len(universe)}종 → 월배당 {n_month}종 → 요약 완료 {len(etfs)}종", flush=True)

    out = {
        "generated": datetime.date.today().isoformat(),
        "assumptions": f"연배당율 = (최종배당월부터 {YIELD_WINDOW}개월 배당 합 × 2) ÷ 최종배당시 주가",
        "etfs": etfs,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"data.json 저장 ({len(etfs)}종)", flush=True)


if __name__ == "__main__":
    main()
