#!/usr/bin/env node
/**
 * 콜시작금리 수집 - 한국자금중개(KMB) 일일 시황 PDF("콜 레포 시장 동향")
 *
 * 콜시작금리 = MAX(기준금리 + 3bp, REPO 시작금리 + 2bp)  (사내 산정 기준)
 *   - REPO 시작금리: PDF 상단 "1. 지준시장 주요 지표"의 "레포(일반채)" 칸. 한 값(3.09%)이거나
 *     범위(3.04~3.14%, 2.45%~2.73%)로 나오며, 범위일 때는 하한이 시작금리다.
 *   - 기준금리: 같은 표의 "기준금리" 칸.
 *   (2026-04-07~11-23의 시트 콜금리(P열) 155일과 대조해 전부 일치함을 확인했다.)
 *
 * 결과는 docs/data/call_start.json 에 {날짜: {value, repo_low, repo_high, base, seq}}로 저장한다.
 * 날짜는 PDF 안의 날짜가 아니라 게시 목록의 날짜를 쓴다 (PDF 본문 날짜에 오타가 있는 파일이 있다).
 * 이미 저장된 날짜는 다시 받지 않으므로 하루에 여러 번 실행돼도 무해하고, 변화가 없으면 파일을 쓰지 않는다.
 * 휴일(PDF가 없는 평일)과 주말은 이 파일에 없는 날짜이며, 화면에서 국내 금리의 기준일(CD 기준일)로
 * 조회하므로 직전 영업일 값이 그대로 쓰인다.
 *
 * 사용법 (저장소 루트에서):  npm install --no-save pdf-parse@1.1.1  &&  node scripts/fetch_call_start.js
 */
"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT_PATH = process.env.CALL_START_OUT || path.join(ROOT, "docs", "data", "call_start.json");
const LIST_URL = "https://www.kmbco.com/kor/trendi/money_trend.do";
const DOWNLOAD_URL = "https://www.kmbco.com/common/downloadFile.do";
const MAX_PAGES = 30;
const HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
};

// ---------------------------------------------------------------------------
// 순수 함수 (네트워크/PDF 라이브러리 없이 테스트 가능)
// ---------------------------------------------------------------------------

/** 게시 목록 HTML에서 [{date, seq}]를 뽑는다. "콜 레포 시장 동향(YYYY-MM-DD)" 행의 첨부파일 번호. */
function parseListHtml(html) {
  const out = [];
  for (const m of html.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)) {
    const title = m[1].match(/콜 레포 시장 동향\((\d{4}-\d{2}-\d{2})\)/);
    const file = m[1].match(/fnFileDown\('(\d+)','4'\)/);
    if (title && file) out.push({ date: title[1], seq: Number(file[1]) });
  }
  return out;
}

/** 소수 둘째 자리(bp) 정수로 계산해서 부동소수점 오차를 피한다. */
function computeCallStart(base, repoLow) {
  return Math.max(Math.round(base * 100) + 3, Math.round(repoLow * 100) + 2) / 100;
}

/**
 * PDF 텍스트 조각들([{s, x, y}])에서 레포(일반채) 시작금리와 기준금리를 위치로 읽는다.
 * 라벨("레포(일반채)", "기준금리") 바로 아래 칸의 값을 쓴다. 못 읽으면 null.
 */
function parseCallStart(items) {
  const its = items.map((i) => ({ s: String(i.s).trim(), x: i.x, y: i.y })).filter((i) => i.s);
  const topmost = (re) => its.filter((i) => re.test(i.s)).sort((a, b) => b.y - a.y)[0];
  const below = (label, maxDx) =>
    its
      .filter((i) => Math.abs(i.x - label.x) < maxDx && i.y < label.y && i.y > label.y - 25)
      .sort((a, b) => b.y - a.y);

  const repoLabel = topmost(/^레포\(일반채\)$/);
  const baseLabel = topmost(/^기준금리$/);
  if (!repoLabel || !baseLabel) return null;

  const repoCell = below(repoLabel, 40).find((i) => /^\d\.\d{2}%?(~\d\.\d{2}%?)?$/.test(i.s));
  const baseCell = below(baseLabel, 30).find((i) => /^\d\.\d{2}%$/.test(i.s));
  if (!repoCell || !baseCell) return null;

  const m = repoCell.s.match(/^(\d\.\d{2})%?(?:~(\d\.\d{2})%?)?$/);
  const repoLow = Number(m[1]);
  const repoHigh = m[2] ? Number(m[2]) : repoLow;
  const base = parseFloat(baseCell.s);
  if (!(repoLow > 0 && repoLow < 20 && base > 0 && base < 20 && repoLow <= repoHigh)) return null;
  return { repo_low: repoLow, repo_high: repoHigh, base, value: computeCallStart(base, repoLow) };
}

// ---------------------------------------------------------------------------
// 네트워크 / PDF
// ---------------------------------------------------------------------------

async function fetchListPage(page) {
  const res = await fetch(`${LIST_URL}?cPage=${page}`, { headers: HEADERS });
  if (!res.ok) throw new Error(`목록 ${page}페이지 HTTP ${res.status}`);
  return parseListHtml(await res.text());
}

async function downloadPdf(seq) {
  const res = await fetch(DOWNLOAD_URL, {
    method: "POST",
    headers: { ...HEADERS, "Content-Type": "application/x-www-form-urlencoded" },
    body: `seq=${seq}&t_type=4`,
  });
  if (!res.ok) throw new Error(`PDF ${seq} HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.subarray(0, 4).toString() !== "%PDF") throw new Error(`PDF ${seq}가 PDF 형식이 아닙니다`);
  return buf;
}

async function extractItems(buf) {
  const pdfParse = require("pdf-parse");
  const items = [];
  const warn = console.warn;
  console.warn = () => {}; // pdf.js의 "Ignoring invalid character" 경고는 결과에 영향이 없다
  try {
    await pdfParse(buf, {
      pagerender: async (page) => {
        const tc = await page.getTextContent();
        tc.items.forEach((i) => items.push({ s: i.str, x: i.transform[4], y: i.transform[5] }));
        return "";
      },
    });
  } finally {
    console.warn = warn;
  }
  return items;
}

function loadExisting() {
  try {
    const j = JSON.parse(fs.readFileSync(OUT_PATH, "utf8"));
    return j && j.days ? j : { days: {} };
  } catch (e) {
    return { days: {} };
  }
}

async function main() {
  const existing = loadExisting();
  const days = { ...existing.days };
  let added = 0;
  let failed = 0;
  let listOk = false;

  for (let page = 1; page <= MAX_PAGES; page++) {
    let entries;
    try {
      entries = await fetchListPage(page);
      listOk = true;
    } catch (e) {
      console.log(`::warning::KMB 목록 조회 실패: ${e.message}`);
      break;
    }
    if (entries.length === 0) break;

    let anyNew = false;
    for (const { date, seq } of entries) {
      if (days[date]) continue;
      anyNew = true;
      try {
        const parsed = parseCallStart(await extractItems(await downloadPdf(seq)));
        if (!parsed) throw new Error("표에서 레포(일반채)/기준금리 값을 읽지 못했습니다");
        days[date] = { value: parsed.value, repo_low: parsed.repo_low, repo_high: parsed.repo_high, base: parsed.base, seq };
        added++;
        console.log(`${date} 콜시작금리 ${parsed.value.toFixed(2)} (레포 ${parsed.repo_low}~${parsed.repo_high}, 기준금리 ${parsed.base})`);
      } catch (e) {
        failed++;
        console.log(`::warning::${date} (seq ${seq}) 수집 실패, 다음 실행에서 다시 시도합니다: ${e.message}`);
      }
    }
    // 이번 페이지가 전부 이미 저장된 날짜면 더 오래된 페이지는 볼 필요가 없다
    if (!anyNew) break;
  }

  if (!listOk) {
    console.log("::error::KMB 게시 목록에 접속하지 못했습니다 (콜시작금리를 갱신하지 못함)");
    process.exitCode = 1;
    return;
  }

  const sorted = Object.fromEntries(Object.keys(days).sort().map((d) => [d, days[d]]));
  const text = JSON.stringify({ source: "한국자금중개(KMB) 일일 원화자금 현황 PDF", days: sorted }, null, 2) + "\n";
  let before = "";
  try {
    before = fs.readFileSync(OUT_PATH, "utf8");
  } catch (e) {}
  if (text !== before) {
    fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
    fs.writeFileSync(OUT_PATH, text);
  }
  console.log(`완료: 신규 ${added}건, 실패 ${failed}건, 총 ${Object.keys(sorted).length}일`);
}

if (require.main === module) {
  main().catch((e) => {
    console.log(`::error::${e.stack || e.message}`);
    process.exitCode = 1;
  });
}

module.exports = { parseListHtml, parseCallStart, computeCallStart };
