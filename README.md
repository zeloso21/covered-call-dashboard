# 커버드콜 ETF 월배당 정보

국내 상장 **월배당 커버드콜 ETF**의 실제 배당 내역만 단순하게 보여주는 정보 페이지입니다.
(2026-09-13 전면 개편 — 1억 투자 시뮬레이션/KODEX200 비교는 제거)

- 종목명 / 최종배당시 주가 / 최종배당월 / 연배당율 / 최근 6개월 배당액
- **연배당율** = (최종배당월부터 6개월간 배당 합 × 2) ÷ 최종배당시 주가

**대시보드**: https://zeloso21.github.io/covered-call-dashboard/

## 데이터

- 한국투자증권 Open API (모의투자 도메인)
  - 분배금: 예탁원정보(배당일정) `/uapi/domestic-stock/v1/ksdinfo/dividend`
  - 월말 종가: 국내주식기간별시세 `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice` (월봉)
- `fetch_data.py` 가 `data.json` 생성. GCP VM cron으로 매월 2일 자동 갱신 후 커밋.

## 주의

커버드콜 ETF는 기초자산이 크게 오를 때 상승분을 반납하며, 분배금 일부가 사실상 자본(원금)에서
나올 수 있습니다. 투자 권유가 아니며 투자 판단과 책임은 본인에게 있습니다.
