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
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import claude_client

# 한국 주요 종목 Yahoo Finance 심볼 매핑
_KR_TICKERS: dict[str, str] = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "LG에너지솔루션": "373220.KS",
    "삼성바이오로직스": "207940.KS", "현대차": "005380.KS", "기아": "000270.KS",
    "셀트리온": "068270.KS", "POSCO홀딩스": "005490.KS", "삼성SDI": "006400.KS",
    "LG화학": "051910.KS", "카카오": "035720.KS", "NAVER": "035420.KS",
    "네이버": "035420.KS", "현대모비스": "012330.KS", "KB금융": "105560.KS",
    "신한지주": "055550.KS", "하나금융지주": "086790.KS", "우리금융지주": "316140.KS",
    "메리츠금융지주": "138040.KS", "삼성생명": "032830.KS", "한국전력": "015760.KS",
    "SK텔레콤": "017670.KS", "KT": "030200.KS", "LG전자": "066570.KS",
    "SK이노베이션": "096770.KS", "두산에너빌리티": "034020.KS",
    "한화에어로스페이스": "012450.KS", "한국항공우주": "047810.KS", "KAI": "047810.KS",
    "삼성물산": "028260.KS", "현대건설": "000720.KS", "LG": "003550.KS",
    "SK": "034730.KS", "삼성전기": "009150.KS", "HD현대중공업": "329180.KS",
    "한국조선해양": "009540.KS", "HMM": "011200.KS", "대한항공": "003490.KS",
    "이마트": "139480.KS", "CJ제일제당": "097950.KS", "하이브": "352820.KS",
    "크래프톤": "259960.KS", "에코프로비엠": "247540.KQ", "에코프로": "086520.KQ",
    "포스코퓨처엠": "003670.KS", "엘앤에프": "066970.KQ", "카카오뱅크": "323410.KS",
    "카카오페이": "377300.KS", "토스뱅크": "289080.KQ", "현대제철": "004020.KS",
    "롯데케미칼": "011170.KS", "SK바이오팜": "326030.KS", "삼성증권": "016360.KS",
    "미래에셋증권": "006800.KS", "한국금융지주": "071050.KS", "NH투자증권": "005940.KS",
    "기업은행": "024110.KS", "BNK금융지주": "138930.KS", "DGB금융지주": "139130.KS",
    "JB금융지주": "175330.KS", "DB손해보험": "005830.KS", "삼성화재": "000810.KS",
    "현대해상": "001450.KS", "한화손해보험": "000370.KS",
    "인카금융서비스": "456040.KQ", "한솔케미칼": "014680.KS",
    "인텍플러스": "064290.KQ", "토모큐브": "393210.KQ",
    "웨이브일렉트로": "346090.KQ",
}


def get_stock_price(company: str) -> str | None:
    """yfinance로 한국 주식 주가를 조회합니다."""
    symbol = _KR_TICKERS.get(company)
    if not symbol:
        logger.info(f"종목 매핑 없음: {company}")
        return None
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="5d")
        if not hist.empty:
            price = int(hist["Close"].iloc[-1])
            if len(hist) >= 2:
                prev = hist["Close"].iloc[-2]
                change_pct = (price - prev) / prev * 100
                sign = "+" if change_pct >= 0 else ""
                return f"{price:,}원 ({sign}{change_pct:.2f}%)"
            return f"{price:,}원"
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


def _fetch_google_news_rss(company: str, max_items: int = 5) -> list[dict]:
    """구글 뉴스 RSS에서 기업 관련 최신 기사를 파싱합니다."""
    query = urllib.parse.quote(company)
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    try:
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"구글 뉴스 RSS 요청 실패 ({company}): {e}")
        return []

    articles = []
    try:
        root = ET.fromstring(resp.text)
        channel = root.find("channel")
        if channel is None:
            return []
        cutoff = datetime.now(pytz.utc) - timedelta(days=2)
        for item in channel.findall("item")[:max_items * 3]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date_str = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            try:
                pub_dt = parsedate_to_datetime(pub_date_str)
                if pub_dt < cutoff:
                    continue
                date_label = pub_dt.astimezone(KST).strftime("%m/%d %H:%M")
            except Exception:
                date_label = pub_date_str[:16] if pub_date_str else ""

            # 구글 뉴스 타이틀은 "기사제목 - 언론사" 형태
            if " - " in title:
                headline, media = title.rsplit(" - ", 1)
            else:
                headline, media = title, source

            articles.append({"title": headline.strip(), "media": media.strip(), "date": date_label, "link": link})
            if len(articles) >= max_items:
                break
    except ET.ParseError as e:
        logger.warning(f"RSS XML 파싱 오류 ({company}): {e}")

    return articles


def search_news_for_one_company(company: str, today: str) -> str:
    """단일 기업의 최신 뉴스를 구글 뉴스 RSS로 검색합니다."""
    articles = _fetch_google_news_rss(company)
    if not articles:
        return "최근 뉴스 없음 (검색 결과 없음)"

    lines = []
    for a in articles:
        link = a.get("link", "")
        if link:
            lines.append(f"• [{a['date']}] [{a['title']}]({link}) ({a['media']})")
        else:
            lines.append(f"• [{a['date']}] {a['title']} ({a['media']})")
    return "\n".join(lines)


def search_news_for_companies(companies: list[str]) -> str:
    """기업 목록에 대한 최근 뉴스 + 주가를 반환합니다."""
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")

    results = []
    for company in companies:
        logger.info(f"검색 중: {company}")

        price = get_stock_price(company)
        price_line = f"주가: {price}" if price else "주가: 조회 불가"

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
