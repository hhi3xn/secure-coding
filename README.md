# Tiny Second-hand Shopping Platform

시큐어 코딩 과제용 중고거래 플랫폼입니다.

사용자는 회원가입 후 상품을 등록하고, 다른 사용자와 메시지를 주고받고, 상품 또는 사용자를 신고할 수 있습니다. 관리자는 사용자, 상품, 신고 내역을 관리할 수 있습니다.

## 개발 환경

- Python 3.10 이상
- Flask
- Flask-SocketIO
- SQLite

## 설치 방법

```bash
git clone https://github.com/hhi3xn/secure-coding.git
cd secure-coding
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell에서는 가상환경 활성화 명령어가 다릅니다.

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 때문에 `Activate.ps1` 실행이 막히는 경우에는 현재 터미널에서만 실행 정책을 임시로 우회한 뒤 활성화합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

또는 가상환경을 활성화하지 않고 아래처럼 직접 실행할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## 실행 방법

```bash
python app.py
```

실행 후 브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:5000
```

최초 실행 시 `market.db` SQLite 데이터베이스가 자동으로 생성됩니다.

## 관리자 계정

처음으로 `admin` 사용자명으로 회원가입하면 관리자 권한이 부여됩니다.

예시:

```text
username: admin
password: Adminpass1
```

비밀번호는 8자 이상이며 영문과 숫자를 모두 포함해야 합니다.

## 주요 기능

- 회원가입, 로그인, 로그아웃
- 비밀번호 해시 저장
- 프로필 소개글 수정
- 비밀번호 변경
- 사용자 조회
- 상품 등록
- 내가 등록한 상품 조회
- 상품 수정 및 삭제
- 상품 상세 조회
- 상품 검색
- 실시간 전체 채팅
- 1대1 메시지
- 상품 신고
- 사용자 신고
- 신고 3회 이상 누적 시 상품 숨김 또는 사용자 휴면 처리
- 가상 포인트 송금
- 관리자 페이지
- 관리자에 의한 사용자 휴면/복구
- 관리자에 의한 상품 숨김/복구/삭제
- 신고 내역 조회

## 보안 적용 내용

- 비밀번호 평문 저장 제거
- Werkzeug `generate_password_hash()`, `check_password_hash()` 사용
- 사용자명, 비밀번호, 상품, 메시지, 신고 사유, 송금 금액 입력값 검증
- SQL 파라미터 바인딩 사용
- 로그인 여부 확인
- 상품 소유자 권한 확인
- 관리자 권한 확인
- CSRF 토큰 검증
- 세션 쿠키 `HttpOnly`, `SameSite=Lax` 설정
- 보안 헤더 설정
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Content-Security-Policy`
- 로그인 실패 횟수 제한
- 채팅 메시지 전송 제한
- 중복 신고 방지

## 테스트

다음 항목을 중심으로 테스트했습니다.

- 회원가입, 로그인, 비밀번호 변경
- 상품 등록, 수정, 삭제, 검색
- 사용자 조회
- 전체 채팅 및 1대1 메시지
- 신고 누적에 따른 상품 숨김 및 사용자 휴면
- 송금 및 잔액 검증
- 관리자 접근 제어
- CSRF 토큰 검증
- 세션 쿠키 및 보안 헤더 확인
- SQL Injection 형태의 검색어 처리

문법 검사는 아래 명령어로 수행할 수 있습니다.

```bash
python -m py_compile app.py
```

## 데이터베이스

프로젝트는 SQLite를 사용합니다. 실행 시 `market.db` 파일이 자동으로 생성됩니다.

주요 테이블은 다음과 같습니다.

- `user`: 사용자 정보
- `product`: 상품 정보
- `report`: 신고 정보
- `message`: 1대1 메시지
- `transfer`: 송금 내역

`market.db`는 로컬 실행 데이터이므로 Git에 포함하지 않습니다.
