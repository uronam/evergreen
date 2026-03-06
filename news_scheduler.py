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

# 종목코드 캐시 (기업명 → 코드)
_ticker_cache: dict[str, str] = {}


def get_stock_price(company: str) -> str | None:
    """pykrx로 오늘 주가(현재가·등락률)를 조회합니다."""
    try:
        from pykrx import stock as krx
        from datetime import datetime

        today_str = datetime.now(KST).strftime("%Y%m%d")

        # 종목코드 조회 (캐시 활용)
        if company not in _ticker_cache:
            for market in ("ALL",):
                tickers = krx.get_market_ticker_list(today_str, market=market)
                for t in tickers:
                    name = krx.get_market_ticker_name(t)
                    if name == company:
                        _ticker_cache[company] = t
                        break
                if company in _ticker_cache:
                    break

        ticker = _ticker_cache.get(company)
        if not ticker:
            return None

        df = krx.get_market_ohlcv(today_str, today_str, ticker)
        if df.empty:
            return None

        row = df.iloc[-1]
        close = int(row.get("종가", row.iloc[3]))
        change_pct = float(row.get("등락률", 0))
        sign = "+" if change_pct >= 0 else ""
        return f"{close:,}원 ({sign}{change_pct:.2f}%)"
    except Exception as e:
        logger.warning(f"주가 조회 실패 ({company}): {e}")
        return None

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


def search_news_for_one_company(company: str, today: str) -> str:
    """단일 기업의 오늘 뉴스를 검색합니다."""
    prompt = (
        f"오늘은 {today}입니다.\n"
        f"web_search 도구로 '{company} 뉴스 {today}' 를 검색해줘.\n\n"
        f"검색 결과에서 {today} 또는 어제 날짜로 실제 게시된 기사만 골라서:\n"
        f"- 뉴스 제목과 핵심 내용 1~2줄\n"
        f"- 기사 날짜 명시\n"
        f"검색 결과에 {today} 기준 기사가 없으면 '최근 뉴스 없음'으로 표시해줘.\n"
        f"절대로 학습 데이터나 기억에서 만들어내지 말고, 검색 결과에 있는 기사만 사용해줘."
    )
    try:
        return claude_client.ask_claude([], prompt)
    except Exception as e:
        logger.error(f"뉴스 검색 오류 ({company}): {e}")
        return f"검색 오류: {e}"


def search_news_for_companies(companies: list[str]) -> str:
    """기업 목록에 대한 최근 24시간 뉴스 + 실시간 주가를 반환합니다."""
    from datetime import datetime
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")

    results = []
    for company in companies:
        logger.info(f"검색 중: {company}")

        # 실시간 주가 (pykrx)
        price = get_stock_price(company)
        price_line = f"현재가: {price}" if price else "현재가: 조회 불가"

        # 오늘 뉴스 (Claude web_search)
        news = search_news_for_one_company(company, today)

        results.append(f"### {company}\n{price_line}\n{news}")

    return "\n\n".join(results)


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
