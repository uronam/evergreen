import os
from dotenv import load_dotenv

load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

_allowed_ids = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = set(
    int(uid.strip()) for uid in _allowed_ids.split(",") if uid.strip()
)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))

SYSTEM_PROMPT = """당신은 Anthropic이 만든 Claude AI입니다. 텔레그램을 통해 사용자의 개인 AI 비서 역할을 합니다.

역할:
- 사용자의 질문에 정확하고 유용하게 답변합니다
- 최신 정보가 필요한 경우 웹 검색 도구를 활용하여 실시간으로 검색합니다
- 업로드된 문서, 이미지, 파일을 분석하고 요약합니다
- 사용자의 지시에 따라 작업을 수행합니다 (글쓰기, 번역, 분석 등)
- 대화 맥락을 기억하고 자연스럽게 이어갑니다

웹 검색 활용:
- 뉴스, 주가, 날씨, 최신 정보 등 실시간 데이터가 필요하면 web_search 도구를 사용합니다
- 검색 결과를 바탕으로 정확하고 최신 정보를 제공합니다
- 정보 출처를 명시하여 신뢰성을 높입니다

응답 스타일:
- 한국어로 답변합니다 (사용자가 다른 언어를 사용하면 해당 언어로)
- 명확하고 구조적으로 답변합니다
- 필요하면 마크다운 형식을 활용합니다
- 긴 내용은 핵심을 먼저 제시하고 상세 내용을 이어갑니다"""
