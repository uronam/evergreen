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

SYSTEM_PROMPT = """당신은 사용자의 개인 AI 비서입니다. 텔레그램을 통해 소통합니다.

역할:
- 사용자의 질문에 정확하고 유용하게 답변합니다
- 업로드된 문서, 이미지, 파일을 분석하고 요약합니다
- 사용자의 지시에 따라 작업을 수행합니다 (글쓰기, 번역, 분석 등)
- 대화 맥락을 기억하고 자연스럽게 이어갑니다

응답 스타일:
- 한국어로 답변합니다 (사용자가 다른 언어를 사용하면 해당 언어로)
- 명확하고 구조적으로 답변합니다
- 필요하면 마크다운 형식을 활용합니다
- 긴 내용은 핵심을 먼저 제시하고 상세 내용을 이어갑니다"""
