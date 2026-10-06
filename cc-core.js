/* 커버드콜 대시보드 공통 계산·포맷 모듈
 * simulator.html / overview.html / index.html 이 같은 함수를 써서 숫자가 항상 일치하도록 한다.
 * 규칙: 매수 = 시작월 말 종가, 분배금 = 그 달 말 지급(시작월 분배금은 받지 않음),
 *       재투자·적립·매도 = 그 달 종가, 소수 주 허용. 보수는 종가에 반영된 것으로 간주. 세전.
 */
(function(global){
'use strict';

/* ---------- 포맷 ---------- */
function fmtKRW(n){
  if(!isFinite(n)) return '-';
  const neg = n < 0; let v = Math.abs(n);
  let s;
  if(v >= 1e8){
    const eok = Math.floor(v / 1e8), man = Math.round((v - eok*1e8) / 1e4);
    s = man >= 10000 ? (eok+1)+'억원' : eok+'억' + (man ? ' '+man.toLocaleString('ko-KR')+'만' : '') + '원';
  } else if(v >= 1e4){
    s = Math.round(v/1e4).toLocaleString('ko-KR') + '만원';
  } else {
    s = Math.round(v).toLocaleString('ko-KR') + '원';
  }
  return (neg ? '−' : '') + s;
}
function fmtAxis(v){
  const a = Math.abs(v);
  if(a >= 1e8) return (v/1e8).toFixed(a >= 1e9 ? 0 : 1).replace(/\.0$/,'') + '억';
  if(a >= 1e4) return Math.round(v/1e4).toLocaleString('ko-KR') + '만';
  return Math.round(v).toLocaleString('ko-KR');
}
function pct(x, d=1){ if(!isFinite(x)) return '-'; const v=(x*100); return (v>0?'+':v<0?'−':'')+Math.abs(v).toFixed(d)+'%'; }
function pctp(x){ return Math.abs(x*100).toFixed(1)+'%p'; }
// 화면에 보이는 소수 1자리 % 끼리의 차이 (보이는 숫자로 뺄셈해도 맞도록)
function dpp(a, b){ return (Math.round(a*1000) - Math.round(b*1000)) / 1000; }
// 부호 붙은 %p (예: +1.4%p, −3.9%p)
function spp(x){ if(!isFinite(x)) return '-'; return (x>0?'+':x<0?'−':'') + pctp(x); }
function cls(x){ return x>0 ? 'pos' : x<0 ? 'neg' : ''; }
function esc(s){ return String(s).replace(/[&<>"]/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch])); }

/* ---------- 데이터 정렬 ---------- */
// 커버드콜·짝꿍이 모두 있는 달 목록
function commonMonths(H, cc, pr){
  const a = H.series[cc];
  if(!pr) return a.m.slice();
  const b = H.series[pr], set = new Set(b.m);
  return a.m.filter(m => set.has(m));
}
function sliceFrom(H, code, months){
  const x = H.series[code], idx = new Map(x.m.map((m,i)=>[m,i]));
  return {m:months, c:months.map(m=>x.c[idx.get(m)]), d:months.map(m=>x.d[idx.get(m)]), name:x.name, code};
}

/* ---------- 계산 엔진 (단위: 원, 소수 주 허용) ---------- */
// 거치식. reinvest: 분배금 재투자 여부, tax: 분배금 원천징수율
function simLump(x, amt, opt={}){
  const tax = opt.tax || 0, re = !!opt.reinvest;
  const c = x.c, d = x.d, n = c.length;
  let sh = amt / c[0], cash = 0, cum = 0;
  const value=[amt], cumDiv=[0], total=[amt], yearDiv={};
  for(let t=1;t<n;t++){
    const div = sh * d[t] * (1 - tax);
    cum += div;
    const y = x.m[t].slice(0,4); yearDiv[y] = (yearDiv[y]||0) + sh * d[t];
    if(re) sh += div / c[t]; else cash += div;
    value.push(sh * c[t]); cumDiv.push(cum); total.push(sh * c[t] + cash);
  }
  const end = n-1;
  return {value, cumDiv, total, yearDiv, invested:amt,
    priceRet: c[end]/c[0]-1,
    distRatio: d.slice(1).reduce((s,v)=>s+v,0)/c[0],
    endValue: value[end], divSum: cum, totalRet: total[end]/amt-1};
}
// 적립식: t=0..n-2 매달 말 매수, 분배금은 매수 전 보유분 기준
function simDCA(x, monthly){
  const c=x.c, d=x.d, n=c.length;
  let sh=0, cash=0, inv=0;
  const value=[], invested=[], total=[];
  for(let t=0;t<n;t++){
    const div = sh * d[t]; cash += div;
    if(t < n-1){ sh += monthly / c[t]; inv += monthly; }
    value.push(sh*c[t]); invested.push(inv); total.push(sh*c[t]+cash);
  }
  return {value, invested, total, divSum:cash, endValue:value[n-1], inv, totalRet: inv? total[n-1]/inv-1 : 0};
}
// 생활비 인출: 분배금 먼저, 부족분 매도, 남으면 재투자
function simWithdraw(x, amt, y){
  const c=x.c, d=x.d, n=c.length;
  let sh = amt / c[0], depleted = null, sold = 0;
  const value=[amt];
  for(let t=1;t<n;t++){
    if(sh <= 0){ value.push(0); continue; }
    const net = sh * d[t] - y;
    if(net < 0) sold += -net;
    sh += net / c[t];
    if(sh <= 0){ sh = 0; if(!depleted) depleted = x.m[t]; }
    value.push(sh * c[t]);
  }
  return {value, endValue:value[n-1], depleted, sold};
}
function simDeposit(n, amt, ratePct){
  const r = ratePct/100/12; const v=[];
  for(let t=0;t<n;t++) v.push(amt*Math.pow(1+r,t));
  return v;
}
function simDepositDCA(n, monthly, ratePct){
  const r = ratePct/100/12; let bal=0; const v=[];
  for(let t=0;t<n;t++){ bal *= (1+r); if(t<n-1) bal += monthly; v.push(bal); }
  return v;
}
// 최근 12개월(진행 중인 마지막 달 제외) 주당 분배금 → 현재가 대비 연 분배율
function trailingYield(H, code){
  const x = H.series[code], L = x.m.length-1;
  const from = Math.max(0, L-12);
  const months = L - from;               // 완결된 달 수
  const sum = x.d.slice(from, L).reduce((s,v)=>s+v,0);
  const annual = months > 0 ? sum * 12 / months : 0;
  return {months, sum, annual, price:x.c[L], yld: annual / x.c[L], from:x.m[from], to:x.m[L-1]};
}
// 장세 분류 (진행 중인 마지막 달 제외). 짝꿍 월 총수익률 기준 ±3%
function regimes(cc, pr){
  const out = {up:{n:0,cc:0,pr:0}, flat:{n:0,cc:0,pr:0}, down:{n:0,cc:0,pr:0}};
  for(let t=1;t<cc.c.length-1;t++){
    const rp = (pr.c[t]+pr.d[t])/pr.c[t-1]-1, rc = (cc.c[t]+cc.d[t])/cc.c[t-1]-1;
    const k = rp > 0.03 ? 'up' : rp < -0.03 ? 'down' : 'flat';
    out[k].n++; out[k].cc += rc; out[k].pr += rp;
  }
  for(const k in out){ const o=out[k]; o.ccAvg = o.n? o.cc/o.n : NaN; o.prAvg = o.n? o.pr/o.n : NaN; }
  return out;
}

/* ---------- 분류 (종목명 기준) ---------- */
// 기초자산 그룹: 종목명 키워드로 분류. 위에서부터 먼저 맞는 규칙 적용.
const GROUPS = ['코스피200','나스닥100','S&P500','미국배당','반도체','채권','기타','혼합형'];
function groupOf(name){
  const n = name.replace(/\s+/g,'');
  if(/혼합|밸런스/.test(n)) return '혼합형';
  if(/국채|채권/.test(n)) return '채권';
  if(/반도체/.test(n)) return '반도체';
  if(/나스닥/.test(n)) return '나스닥100';
  if(/S&P500|미국500/.test(n)) return 'S&P500';
  if(/미국배당/.test(n)) return '미국배당';
  if(/^(KODEX|TIGER|PLUS|RISE|SOL|ACE|KIWOOM|FOCUS)200/.test(n)) return '코스피200';
  return '기타';
}
// 운용사(브랜드) = 종목명 첫 단어
function amcOf(name){ return name.trim().split(/\s+/)[0]; }

/* ---------- 전 종목 요약 지표 (overview) ---------- */
// full: 두 ETF 데이터가 모두 있는 가장 이른 달 ~ 마지막 달 (= simulator.html 기본 화면과 같은 기간)
// w12 : 진행 중인 마지막 달을 뺀 최근 12개월. 시작 = 12개월 전 월말(매수), 끝 = 직전 완결 달.
//       데이터가 짧으면 있는 기간 전체(short=true), 분배율은 12/k 로 연환산.
function windowMonths(all){
  const endIdx = all.length - 2;                 // 직전 완결 달
  if(endIdx < 1) return null;
  const startIdx = Math.max(0, endIdx - 12);
  return all.slice(startIdx, endIdx + 1);
}
function computeRow(H, p){
  const name = H.series[p.code].name;
  const prCode = p.grade === 'C' ? null : p.pair;
  const all = commonMonths(H, p.code, prCode);
  const row = {code:p.code, name, grade:p.grade, memo:p.memo||'', group:groupOf(name), amc:amcOf(name),
    pair:prCode, pairName: prCode ? H.series[prCode].name : null};
  // full
  const cc = sliceFrom(H, p.code, all), L = simLump(cc, 1);
  row.start = all[0]; row.end = all[all.length-1]; row.N = all.length - 1;
  row.ccTot = L.totalRet; row.ccDist = L.distRatio;
  if(prCode){
    const pr = sliceFrom(H, prCode, all), Lp = simLump(pr, 1);
    row.prTot = Lp.totalRet; row.prDist = Lp.distRatio;
    row.diff = dpp(L.totalRet, Lp.totalRet);
    row.reg = regimes(cc, pr);
    row.downDiff = row.reg.down.n ? row.reg.down.ccAvg - row.reg.down.prAvg : NaN;
  }
  // w12
  const wm = windowMonths(all);
  if(wm){
    const k = wm.length - 1, wc = simLump(sliceFrom(H, p.code, wm), 1);
    row.w = {start:wm[0], end:wm[k], k, short:k < 12, yld: wc.distRatio * 12 / k, ccTot: wc.totalRet, ccDist: wc.distRatio};
    if(prCode){
      const wp = simLump(sliceFrom(H, prCode, wm), 1);
      row.w.prTot = wp.totalRet; row.w.diff = dpp(wc.totalRet, wp.totalRet);
      row.w.ccPath = wc.total.map(v=>v-1); row.w.prPath = wp.total.map(v=>v-1); row.w.months = wm;
    }
  }
  return row;
}
function computeAll(H){ return H.pairs.map(p => computeRow(H, p)); }
function pearson(xs, ys){
  const n = xs.length; if(n < 3) return NaN;
  const mx = xs.reduce((a,b)=>a+b,0)/n, my = ys.reduce((a,b)=>a+b,0)/n;
  let sxy=0, sxx=0, syy=0;
  for(let i=0;i<n;i++){ const dx=xs[i]-mx, dy=ys[i]-my; sxy+=dx*dy; sxx+=dx*dx; syy+=dy*dy; }
  return sxy / Math.sqrt(sxx*syy);
}

global.CC = {fmtKRW, fmtAxis, pct, pctp, dpp, spp, cls, esc,
  commonMonths, sliceFrom, simLump, simDCA, simWithdraw, simDeposit, simDepositDCA, trailingYield, regimes,
  GROUPS, groupOf, amcOf, windowMonths, computeRow, computeAll, pearson};
})(window);
