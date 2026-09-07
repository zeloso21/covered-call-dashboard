# 커버드콜 ETF 월배당 비교 대시보드

국내 상장 **월배당 커버드콜 ETF**에 2년 전(또는 상장 직후) 월말에 **1억원을 일시금 매수**해
**분배금을 매달 현금으로 인출**(재투자 없음, 세전)했을 때의 결과를 매월말 기준으로 시뮬레이션합니다.

- **평가액(원금)** 과 **누적 수령배당** 을 분리해서 표시
- 같은 기간 **KODEX 200** 총자산과 비교
- 은퇴자가 "월 현금흐름 / 원금 보존 / 총수익"을 한눈에 비교

**대시보드**: https://zeloso21.github.io/covered-call-dashboard/

## 데이터

- 한국투자증권 Open API (모의투자 도메인)
  - 분배금: 예탁원정보(배당일정) `/uapi/domestic-stock/v1/ksdinfo/dividend`
  - 월말 종가: 국내주식기간별시세 `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice` (월봉)
- `fetch_data.py` 가 `data.json` 생성. GCP VM cron으로 매월 2일 자동 갱신 후 커밋.

## 주의

커버드콜 ETF는 기초자산이 크게 오를 때 상승분을 반납하며, 분배금 일부가 사실상 자본(원금)에서
나올 수 있습니다. 투자 권유가 아니며 투자 판단과 책임은 본인에게 있습니다.
