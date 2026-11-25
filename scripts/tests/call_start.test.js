// 실행: (저장소 루트에서) node --test scripts/tests/call_start.test.js
// 네트워크/PDF 라이브러리 없이, 실제 PDF에서 읽은 텍스트 조각 위치를 그대로 옮긴 데이터로 검증한다.
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { parseListHtml, parseCallStart, computeCallStart } = require("../fetch_call_start.js");

// 2026-11-23 PDF: 레포(일반채) 3.09% (한 값), 기준금리 3.00%
const SINGLE = [
  { s: "일일 원화자금 현황", x: 252, y: 753 },
  { s: "레포(일반채)", x: 90, y: 715 },
  { s: "콜(O/N)", x: 42, y: 714 },
  { s: "기준금리", x: 146, y: 714 },
  { s: "3.09%", x: 98, y: 704 },
  { s: "3.00%", x: 151, y: 704 },
  { s: "3.110%", x: 44, y: 700 },
  { s: "레포(회사채)", x: 90, y: 695 },
  { s: "3.14%", x: 98, y: 684 },
  { s: "6. 기준금리 변동상황", x: 27, y: 400 },
];

// 2026-09-18 PDF: 레포(일반채) 3.04~3.14% (범위), 기준금리 3.00%
const RANGE = SINGLE.map((i) => (i.s === "3.09%" ? { ...i, s: "3.04~3.14%" } : i));

// 2026-07-21 PDF: 범위 표기가 2.45%~2.73% 이고 기준금리 2.75%
const RANGE_PCT = [
  { s: "레포(일반채)", x: 90, y: 715 },
  { s: "기준금리", x: 146, y: 714 },
  { s: "2.45%~2.73%", x: 90, y: 704 },
  { s: "2.75%", x: 151, y: 704 },
];

test("단일 값: 레포 3.09 -> max(3.03, 3.11) = 3.11", () => {
  const r = parseCallStart(SINGLE);
  assert.deepStrictEqual(r, { repo_low: 3.09, repo_high: 3.09, base: 3.0, value: 3.11 });
});

test("범위 표기는 하한을 쓴다: 3.04~3.14 -> max(3.03, 3.06) = 3.06 (상한을 쓰면 3.16이라 틀림)", () => {
  const r = parseCallStart(RANGE);
  assert.strictEqual(r.repo_low, 3.04);
  assert.strictEqual(r.repo_high, 3.14);
  assert.strictEqual(r.value, 3.06);
});

test("두 값에 모두 % 가 붙은 범위 표기도 읽는다: 2.45%~2.73%, 기준금리 2.75 -> 기준금리+3bp 하한 2.78", () => {
  const r = parseCallStart(RANGE_PCT);
  assert.strictEqual(r.repo_low, 2.45);
  assert.strictEqual(r.value, 2.78);
});

test("기준금리 하한: 레포 시작이 기준금리보다 한참 낮으면 기준금리+3bp", () => {
  assert.strictEqual(computeCallStart(3.0, 2.98), 3.03);
  assert.strictEqual(computeCallStart(2.75, 2.73), 2.78);
});

test("레포 시작+2bp가 더 크면 그 값", () => {
  assert.strictEqual(computeCallStart(3.0, 3.07), 3.09);
  assert.strictEqual(computeCallStart(2.5, 2.52), 2.54);
});

test("부동소수점 오차 없이 계산한다", () => {
  assert.strictEqual(computeCallStart(2.75, 2.85), 2.87);
  assert.strictEqual(computeCallStart(3.0, 3.15), 3.17);
});

test("표를 못 읽으면 null (라벨 없음 / 값 칸 없음)", () => {
  assert.strictEqual(parseCallStart([{ s: "아무 글자", x: 1, y: 1 }]), null);
  assert.strictEqual(parseCallStart(SINGLE.filter((i) => i.s !== "3.09%")), null);
});

test("목록 HTML에서 날짜와 첨부파일 번호를 뽑는다", () => {
  const html = `
    <tr><td>3383</td><td>콜 레포 시장 동향(2026-11-24)</td><td><a href="javascript:fnFileDown('3428','4')">첨부파일</a></td><td>2026.11.24</td></tr>
    <tr><td>3382</td><td>콜 레포 시장 동향(2026-11-23)</td><td><a href="javascript:fnFileDown('3427','4')">첨부파일</a></td><td>2026.11.23</td></tr>
    <tr><td>1</td><td>다른 게시물</td><td></td><td></td></tr>`;
  assert.deepStrictEqual(parseListHtml(html), [
    { date: "2026-11-24", seq: 3428 },
    { date: "2026-11-23", seq: 3427 },
  ]);
});
