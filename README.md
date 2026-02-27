# 텔레그램 Claude 봇

텔레그램을 통해 Claude AI와 대화하는 개인 비서 봇입니다.

## 기능

- **텍스트 메세지** → Claude가 답변 (대화 히스토리 유지)
- **이미지 전송** → Claude가 이미지 분석 및 설명
- **문서 전송** → Claude가 내용 요약 및 정리
- **명령어 지원**: `/start`, `/clear`, `/help`

---

## 빠른 시작

### 1단계: 텔레그램 봇 토큰 발급

1. 텔레그램에서 **@BotFather** 검색
2. `/newbot` 명령어 입력
3. 봇 이름과 username 설정
4. 발급된 **API Token** 복사

### 2단계: 내 텔레그램 ID 확인

1. 텔레그램에서 **@userinfobot** 검색
2. Start 클릭
3. 표시된 **Id** 숫자 복사

### 3단계: Anthropic API Key 발급

1. [console.anthropic.com](https://console.anthropic.com) 접속
2. API Keys 메뉴에서 새 키 발급

### 4단계: 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 값 입력
```

`.env` 파일 내용:
```
TELEGRAM_BOT_TOKEN=여기에_봇_토큰
ANTHROPIC_API_KEY=여기에_API_키
ALLOWED_USER_IDS=여기에_내_텔레그램_ID
```

---

## 실행 방법

### 방법 1: Docker (권장)

```bash
docker compose up -d
```

로그 확인:
```bash
docker compose logs -f
```

중지:
```bash
docker compose down
```

### 방법 2: 직접 실행

```bash
pip install -r requirements.txt
python bot.py
```

---

## 사용법

| 입력 | 결과 |
|------|------|
| 텍스트 메세지 | Claude가 답변 |
| 사진 전송 | 이미지 분석/설명 |
| 사진 + 캡션 | 캡션 질문에 맞게 분석 |
| 파일 전송 | 문서 요약 |
| 파일 + 캡션 | 캡션 지시에 따라 처리 |

### 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 봇 시작 및 대화 초기화 |
| `/clear` | 대화 히스토리 삭제 |
| `/help` | 도움말 보기 |

### 사용 예시

```
나: 오늘 할 일 목록 정리해줘
Claude: 물론입니다! 어떤 할 일들이 있으신가요? ...

나: [계약서 파일 첨부] 핵심 조항만 요약해줘
Claude: 계약서의 핵심 조항을 요약해드리겠습니다...

나: [사진 첨부] 이 음식 칼로리 추정해줘
Claude: 이미지에서 보이는 음식을 분석하면...
```

---

## 보안

- `ALLOWED_USER_IDS`에 본인 ID만 등록하면 다른 사람은 봇 사용 불가
- `.env` 파일은 절대 공유하거나 git에 올리지 마세요
- 봇은 private 채팅만 사용하는 것을 권장합니다
