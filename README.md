# 금리 자동수집 대시보드

매일 한국시간(KST) 오전 6시에 9개 금리를 자동으로 수집해서, GitHub Pages 웹사이트에서 확인할 수 있게 해주는 완전 무료 자동화입니다.

- 자동 실행: GitHub Actions (무료)
- 웹사이트 호스팅: GitHub Pages (무료)
- 별도 서버/결제 없음

## 수집 항목 (9개)

1. 한국은행 기준금리
2. CD(3개월)
3. A1CP(1개월)
4. A1CP(3개월)
5. 회사채(AA-, 1년)
6. 회사채(AA-, 2년)
7. 회사채(AA-, 3년)
8. 국고채권(3년)
9. SOFR

## 폴더 구조

```
scripts/                 수집 스크립트 (Python)
  date_utils.py           영업일/전영업일 계산
  storage.py              이력(JSON) 저장 로직
  export_xlsx.py          이력을 엑셀로 변환
  fetch_rates.py          메인 실행 스크립트
  sources/                사이트별 수집 모듈 (bok, kofia, sofr)
  tests/                  네트워크 없이 돌아가는 단위 테스트
docs/                    GitHub Pages로 배포되는 웹사이트
  index.html              대시보드 페이지
  data/history.json       누적 수집 이력 (자동 갱신)
  data/history.xlsx       누적 이력 엑셀 (자동 갱신)
.github/workflows/
  fetch-rates.yml         매일 자동 실행 워크플로우
```

## 배포 방법 (터미널/관리자 권한 전혀 필요 없음, 웹브라우저만 사용)

이 프로젝트는 컴퓨터에 아무것도 설치하지 않고, 웹브라우저에서 GitHub 사이트만 클릭해서 100% 배포할 수 있습니다.

### 0. 압축 풀기 + 숨김 파일 보이게 설정
1. 받은 `rates-tracker.zip`을 더블클릭(또는 우클릭 → 압축 풀기)해서 압축을 풉니다. (관리자 권한 불필요, 운영체제 기본 기능)
2. 이 프로젝트에는 `.github`, `.gitignore` 처럼 **점(.)으로 시작하는 폴더/파일**이 있는데, 기본 설정에서는 파일탐색기에 안 보일 수 있습니다. 업로드 전에 숨김 파일이 보이도록 설정해주세요.
   - **Mac**: 압축 푼 폴더를 Finder에서 연 상태에서 `Cmd + Shift + .` (마침표) 를 누르면 숨김 파일이 나타납니다.
   - **Windows**: 탐색기 상단 **보기(View)** 탭 → **숨긴 항목(Hidden items)** 체크박스 선택.
   - `.github` 폴더와 `.gitignore` 파일이 회색으로 흐릿하게 보이면 정상입니다 (선택은 정상적으로 가능).

### 1. GitHub 저장소 만들기
1. 브라우저에서 https://github.com/new 접속 (로그인 필요)
2. Repository name에 원하는 이름 입력 (예: `rates-tracker`)
3. Public/Private 아무거나 선택 (Public이 Actions 무료 사용량이 더 넉넉합니다)
4. 다른 옵션은 그대로 두고 **Create repository** 클릭

### 2. 파일 업로드
1. 방금 만든 저장소 페이지에서 **Add file → Upload files** 클릭
2. 압축 푼 `rates-tracker` 폴더를 **열고**, 그 안의 내용물 전체(`.github`, `docs`, `scripts`, `README.md`, `requirements.txt`, `.gitignore`)를 **모두 선택(Ctrl+A / Cmd+A)** 한 뒤, 브라우저의 업로드 영역으로 통째로 드래그합니다.
   - 주의: `rates-tracker` 폴더 자체를 드래그하지 말고, 그 **안의 내용물**을 드래그해야 합니다. (폴더째 올리면 `rates-tracker/scripts/...` 처럼 한 단계 더 들어간 구조가 되어버립니다)
3. 파일 목록이 다 올라온 게 보이면 하단의 **Commit changes** 클릭
4. 업로드 후 저장소 파일 목록에 `.github` 폴더가 보이는지 꼭 확인하세요. 안 보이면 0번의 숨김 파일 설정이 안 된 것이니 `.github/workflows/fetch-rates.yml` 파일 하나만 아래 방법으로 별도 생성하면 됩니다:
   - 저장소 페이지 **Add file → Create new file** 클릭
   - 파일명 입력칸에 `.github/workflows/fetch-rates.yml` 이라고 입력 (슬래시를 입력하면 자동으로 폴더가 만들어집니다)
   - 압축 푼 폴더 안의 `.github/workflows/fetch-rates.yml` 파일을 메모장/텍스트에디터로 열어서 내용을 복사한 뒤, GitHub 편집창에 붙여넣기
   - **Commit changes** 클릭

### 3. GitHub Pages 활성화
1. 저장소의 **Settings → Pages** 로 이동
2. "Build and deployment" → Source를 **Deploy from a branch** 로 설정
3. Branch는 **main**, 폴더는 **/docs** 선택 후 저장
4. 몇 분 후 `https://<내계정>.github.io/<저장소이름>/` 주소로 사이트가 열립니다.

### 4. Actions 쓰기 권한 설정 (자동 커밋을 위해 필요)
1. 저장소의 **Settings → Actions → General** 로 이동
2. 맨 아래 "Workflow permissions" 에서 **Read and write permissions** 선택 후 저장

### 5. 첫 실행 테스트 (수동 실행)
1. 저장소의 **Actions** 탭 → 왼쪽에서 "Fetch daily rates" 선택
2. 오른쪽 "Run workflow" 버튼 클릭 → 실행
3. 실행이 끝나면 초록색 체크가 뜨는지 확인합니다. 만약 실패(빨간 X)하면 로그를 열어서 어떤 항목이 실패했는지 확인하세요.
4. 성공하면 `docs/data/history.json`, `docs/data/history.xlsx` 가 자동으로 커밋됩니다.
5. Pages 사이트를 새로고침하면 오늘자 금리가 표시됩니다.

이후로는 매일 KST 오전 6시에 자동으로 실행됩니다 (GitHub Actions의 예약 실행이 가끔 지연/스킵될 수 있어, 7시에 한 번 더 재시도합니다 - 이미 성공했으면 조용히 끝납니다). 스케줄 시각을 바꾸고 싶으면 `.github/workflows/fetch-rates.yml`의 `cron` 값을 수정하세요. UTC 기준이라 KST보다 9시간 빠릅니다.

혹시 예약 실행이 둘 다 놓쳐서 오늘자가 안 들어왔다면, 사이트 상단의 **"지금 값 갱신하기"** 링크로 바로 이동해서 **Run workflow**를 눌러 즉시 채울 수 있습니다 (GitHub 로그인 필요).

## 꼭 확인해야 할 점 (중요)

- **KOFIA(CD/CP/회사채/국고채권) API**: 브라우저에서 실제 요청을 캡처해서 만들었지만, GitHub Actions 서버(쿠키 없는 첫 요청)에서도 동일하게 동작하는지는 실제로 한 번 돌려봐야 확실합니다. 1회차 수동 실행 결과를 꼭 확인해주세요.
- **날짜 로직**: 매일 실행 시점 기준 "전영업일(국내)/그 전영업일(해외)" 값을 조회하며, 공휴일 등으로 데이터가 없으면 자동으로 하루씩 더 앞으로 이동해서 찾습니다. `history.json`의 각 날짜는 **실행한 날짜가 아니라 그 값이 실제로 유효한 기준일**로 저장됩니다 (예: 9/7(월)에 실행하면 그 결과는 실제 조회 대상이었던 9/4(금) 밑에 저장되고, 9/7 자신의 값은 그 다음 영업일 실행에서 채워집니다). 금요일 값은 그 다음 토/일에도 자동으로 채워 넣습니다 (주말엔 새 시세가 없으므로 금요일 값이 곧 주말 값).

## 과거 데이터 한 번에 채우기 (백필)

처음 시작할 때처럼 이력이 하루치밖에 없다면, 아래 방법으로 과거 영업일치를 한 번에 채울 수 있습니다 (터미널 필요 없음, GitHub Actions에서 실행).

1. 저장소의 **Actions** 탭 → 왼쪽에서 **"Backfill rates"** 선택
2. 오른쪽 **Run workflow** 클릭 → `days`에 채우고 싶은 영업일 수 입력 (기본값 22 = 약 한 달) → **Run workflow**
3. 완료되면 `docs/data/history.json`, `docs/data/history.xlsx`에 과거 영업일치가 추가로 커밋됩니다.

오늘자(가장 최근 영업일)는 매일 자동 실행되는 "Fetch daily rates" 쪽 몫이라 백필 대상에서 제외됩니다. 여러 번 실행해도 같은 날짜는 최신 결과로 덮어써질 뿐이라 안전합니다.

이 워크플로우는 매주 일요일(KST 오전 8시)에도 자동으로 한 번 더 실행되어, "Fetch daily rates"가 어느 날 예약 실행을 놓쳐 빠진 날짜가 생겼더라도 최근 22영업일 범위 안이면 자동으로 복구됩니다.

## 로컬에서 테스트하기

```bash
pip install -r requirements.txt
python scripts/fetch_rates.py          # 실제로 사이트에 접속해서 오늘자 데이터 수집
python -m unittest discover -s scripts/tests -v   # 네트워크 없이 로직만 검증
```

## 웹사이트 기능

- 오늘 기준 9개 금리 표시
- 날짜를 입력해서 해당일의 9개 금리 조회
- 금리 종류 + 기간을 선택해서 해당 기간의 값 목록/최소/최대/평균 확인
- 누적 이력 엑셀(history.xlsx) 다운로드
