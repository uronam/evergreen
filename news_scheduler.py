"""
뉴스 자동 알림 스케줄러
- 사용자별 기업 목록 저장
- 매일 오전 7시(KST)에 뉴스 검색 후 텔레그램 전송
"""
from __future__ import annotations

import json
import logging
import os
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import claude_client

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")

# 사용자별 뉴스 구독 정보 저장 경로
SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(__file__), "news_subscriptions.json")

# { chat_id (int): [기업명, ...] }
subscriptions: dict[int, list[str]] = {}


def _load_subscriptions() -> None:
    global subscriptions
    if os.path.exists(SUBSCRIPTIONS_FILE):
        try:
            with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            subscriptions = {int(k): v for k, v in raw.items()}
        except Exception as e:
            logger.warning(f"구독 정보 로드 실패: {e}")
            subscriptions = {}


def _save_subscriptions() -> None:
    try:
        with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in subscriptions.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"구독 정보 저장 실패: {e}")


def set_subscription(chat_id: int, companies: list[str]) -> None:
    subscriptions[chat_id] = companies
    _save_subscriptions()


def remove_subscription(chat_id: int) -> bool:
    if chat_id in subscriptions:
        del subscriptions[chat_id]
        _save_subscriptions()
        return True
    return False


def get_subscription(chat_id: int) -> list[str] | None:
    return subscriptions.get(chat_id)


def search_news_for_companies(companies: list[str]) -> str:
    """기업 목록에 대한 최근 24시간 뉴스를 검색하고 요약합니다."""
    from datetime import datetime
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    companies_str = ", ".join(companies)
    prompt = (
        f"오늘은 {today}입니다. "
        f"web_search 도구를 사용하여 다음 기업들의 {today} 기준 최근 24시간 주요 뉴스를 검색해줘:\n"
        f"{companies_str}\n\n"
        f"각 기업마다:\n"
        f"- 기업명을 제목으로\n"
        f"- 주요 뉴스 2~3개를 핵심만 간략히 (날짜 포함)\n"
        f"- 뉴스가 없으면 '특이사항 없음'으로\n\n"
        f"반드시 웹 검색으로 {today} 기준 실제 최신 뉴스를 가져와줘. 학습 데이터가 아닌 실시간 검색 결과를 사용해줘."
    )
    try:
        result = claude_client.ask_claude([], prompt)
        return result
    except Exception as e:
        logger.error(f"뉴스 검색 오류: {e}")
        return f"뉴스 검색 중 오류가 발생했습니다: {e}"


async def send_daily_news(bot) -> None:
    """모든 구독자에게 뉴스를 발송합니다."""
    if not subscriptions:
        return

    logger.info(f"일일 뉴스 발송 시작: {len(subscriptions)}명")

    for chat_id, companies in list(subscriptions.items()):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"📰 오늘의 기업 뉴스 브리핑\n\n검색 중... ⏳",
            )
            news_text = await asyncio.to_thread(search_news_for_companies, companies)
            header = "📰 **오늘의 기업 뉴스 브리핑**\n\n"
            full_text = header + news_text

            # 4096자 제한 처리
            if len(full_text) <= 4096:
                chunks = [full_text]
            else:
                chunks = []
                remaining = full_text
                while remaining:
                    if len(remaining) <= 4096:
                        chunks.append(remaining)
                        break
                    split_at = remaining.rfind("\n", 0, 4096)
                    if split_at == -1 or split_at < 2048:
                        split_at = 4096
                    chunks.append(remaining[:split_at])
                    remaining = remaining[split_at:]

            from telegram.constants import ParseMode
            for chunk in chunks:
                try:
                    await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN)
                except Exception:
                    await bot.send_message(chat_id=chat_id, text=chunk)

        except Exception as e:
            logger.error(f"뉴스 발송 오류 (chat_id={chat_id}): {e}")

    logger.info("일일 뉴스 발송 완료")


def create_scheduler(bot) -> AsyncIOScheduler:
    """매일 오전 7시(KST) 뉴스 발송 스케줄러를 생성합니다."""
    _load_subscriptions()

    scheduler = AsyncIOScheduler(timezone=KST)
    scheduler.add_job(
        send_daily_news,
        trigger=CronTrigger(hour=7, minute=0, timezone=KST),
        args=[bot],
        id="daily_news",
        name="일일 기업 뉴스 브리핑",
        replace_existing=True,
    )
    return scheduler
