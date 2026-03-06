from __future__ import annotations

"""
텔레그램 Claude 봇
- 텍스트 메세지 → Claude 응답
- 이미지 업로드 → Claude 분석/설명
- 문서 업로드 → Claude 요약
- 대화 히스토리 유지
"""

import logging
import asyncio
import aiohttp
import aiofiles
import tempfile
import os
import queue
import re
import threading

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction, ParseMode

import claude_client
import news_scheduler
from config import (
    TELEGRAM_BOT_TOKEN,
    ALLOWED_USER_IDS,
    MAX_HISTORY_MESSAGES,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 사용자별 대화 히스토리 저장 (메모리)
# key: user_id, value: list of {"role": ..., "content": ...}
conversation_history: dict[int, list[dict]] = {}


def is_allowed(user_id: int) -> bool:
    """허용된 사용자인지 확인합니다."""
    if not ALLOWED_USER_IDS:
        return True  # 제한 없음 (설정 안 한 경우)
    return user_id in ALLOWED_USER_IDS


def get_history(user_id: int) -> list[dict]:
    return conversation_history.get(user_id, [])


def add_to_history(user_id: int, role: str, content: str | list) -> None:
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append({"role": role, "content": content})
    # 히스토리 길이 제한
    if len(conversation_history[user_id]) > MAX_HISTORY_MESSAGES * 2:
        conversation_history[user_id] = conversation_history[user_id][-MAX_HISTORY_MESSAGES * 2:]


def clear_history(user_id: int) -> None:
    conversation_history[user_id] = []


MAX_MSG_LEN = 4096


def _split_text(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    """텍스트를 max_len 단위로 분할합니다 (줄바꿈 경계 우선)."""
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks


async def send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )


async def send_long_message(update: Update, text: str, parse_mode=None) -> None:
    """긴 메시지를 4096자 단위로 분할해서 전송합니다."""
    for chunk in _split_text(text):
        sent = False
        if parse_mode:
            try:
                await update.message.reply_text(chunk, parse_mode=parse_mode)
                sent = True
            except Exception:
                pass
        if not sent:
            await update.message.reply_text(chunk)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("접근 권한이 없습니다.")
        return

    clear_history(user_id)
    await update.message.reply_text(
        "안녕하세요! 저는 Claude AI 비서입니다. 🤖\n\n"
        "**사용 방법:**\n"
        "• 텍스트 메세지 → Claude가 답변\n"
        "• 이미지 전송 → Claude가 분석\n"
        "• 문서 전송 (PDF, TXT 등) → Claude가 요약\n\n"
        "**명령어:**\n"
        "/start - 대화 초기화\n"
        "/clear - 대화 히스토리 삭제\n"
        "/help - 도움말\n"
        "/news - 매일 오전 7시 기업 뉴스 자동 알림\n\n"
        "무엇을 도와드릴까요?",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "**Claude AI 비서 도움말**\n\n"
        "**텍스트 메세지**\n"
        "그냥 메세지를 입력하면 Claude가 답변합니다.\n"
        "이전 대화 내용을 기억하며 자연스럽게 이어갑니다.\n\n"
        "**이미지 전송**\n"
        "사진을 보내면 Claude가 분석하고 설명합니다.\n"
        "이미지와 함께 질문도 할 수 있습니다.\n"
        "예: (사진 첨부) + '이 음식의 칼로리를 추정해줘'\n\n"
        "**문서 전송**\n"
        "PDF, TXT, 문서 파일을 보내면 요약해드립니다.\n"
        "파일과 함께 지시도 할 수 있습니다.\n"
        "예: (파일 첨부) + '핵심 내용만 3줄로 요약해줘'\n\n"
        "**명령어**\n"
        "/start - 대화 초기화 (히스토리 삭제)\n"
        "/clear - 대화 히스토리만 삭제\n"
        "/help - 이 도움말 보기\n\n"
        "**뉴스 자동 알림**\n"
        "/news 기업1,기업2 - 매일 오전 7시 뉴스 알림 설정\n"
        "/news\\_off - 뉴스 알림 해제\n"
        "/news\\_now - 지금 바로 뉴스 받기\n"
        "예: `/news 삼성전자,SK하이닉스,현대차`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return
    clear_history(user_id)
    await update.message.reply_text("대화 히스토리가 초기화되었습니다. 새로운 대화를 시작하세요!")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("접근 권한이 없습니다.")
        return

    user_text = update.message.text
    history = get_history(user_id)

    try:
        sent_message = await update.message.reply_text("⏳")

        q: queue.Queue = queue.Queue()

        def produce():
            try:
                for chunk in claude_client.stream_claude(history, user_text):
                    q.put(("chunk", chunk))
            except Exception as e:
                q.put(("error", str(e)))
            finally:
                q.put(("done", None))

        threading.Thread(target=produce, daemon=True).start()

        accumulated = ""
        last_edit_time = asyncio.get_running_loop().time()
        EDIT_INTERVAL = 1.5  # 텔레그램 rate limit 방지용 간격 (초)

        while True:
            try:
                event_type, data = q.get_nowait()
            except queue.Empty:
                now = asyncio.get_running_loop().time()
                if accumulated and now - last_edit_time >= EDIT_INTERVAL:
                    try:
                        await sent_message.edit_text(accumulated + " ▌")
                        last_edit_time = now
                    except Exception:
                        pass
                await asyncio.sleep(0.05)
                continue

            if event_type == "chunk":
                accumulated += data
            elif event_type == "error":
                logger.error(f"스트리밍 오류: {data}")
                await sent_message.edit_text(f"오류가 발생했습니다: {data}")
                return
            elif event_type == "done":
                break

        # 완료 후 마크다운 적용해서 최종 메시지 표시
        chunks = _split_text(accumulated)
        try:
            await sent_message.edit_text(chunks[0], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await sent_message.edit_text(chunks[0])

        for chunk in chunks[1:]:
            try:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.message.reply_text(chunk)

        add_to_history(user_id, "user", user_text)
        add_to_history(user_id, "assistant", accumulated)

    except Exception as e:
        logger.error(f"텍스트 처리 오류: {e}")
        await update.message.reply_text(f"오류가 발생했습니다: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return

    caption = update.message.caption or ""
    history = get_history(user_id)

    await send_typing(update, context)

    try:
        # 가장 고화질 이미지 선택
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        async with aiohttp.ClientSession() as session:
            async with session.get(file.file_path) as resp:
                image_data = await resp.read()

        reply = await asyncio.to_thread(
            claude_client.ask_claude_with_image,
            history,
            caption,
            image_data,
            "image/jpeg",
        )
        add_to_history(user_id, "user", caption or "[이미지 전송]")
        add_to_history(user_id, "assistant", reply)
        await send_long_message(update, reply, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"이미지 처리 오류: {e}")
        await update.message.reply_text(f"이미지 처리 중 오류가 발생했습니다: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return

    doc = update.message.document
    caption = update.message.caption or ""
    history = get_history(user_id)
    filename = doc.file_name or "document"
    mime_type = doc.mime_type or ""

    await send_typing(update, context)

    try:
        file = await context.bot.get_file(doc.file_id)

        # 임시 파일로 다운로드
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
            tmp_path = tmp.name

        try:
            await file.download_to_drive(tmp_path)

            # 파일 타입에 따라 처리
            if mime_type.startswith("image/"):
                async with aiofiles.open(tmp_path, "rb") as f:
                    image_data = await f.read()
                reply = await asyncio.to_thread(
                    claude_client.ask_claude_with_image,
                    history,
                    caption,
                    image_data,
                    mime_type,
                )
            elif filename.lower().endswith((".docx", ".doc")) or mime_type in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            ):
                file_text = await asyncio.to_thread(_read_docx, tmp_path)
                if file_text:
                    reply = await asyncio.to_thread(
                        claude_client.ask_claude_with_document,
                        history,
                        caption,
                        file_text,
                        filename,
                    )
                else:
                    reply = "워드 파일에서 텍스트를 읽을 수 없습니다."
            elif mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
                async with aiofiles.open(tmp_path, "rb") as f:
                    pdf_data = await f.read()
                reply = await asyncio.to_thread(
                    claude_client.ask_claude_with_pdf,
                    history,
                    caption,
                    pdf_data,
                )
            else:
                # 텍스트 기반 파일 읽기 시도
                file_text = await _read_file_text(tmp_path, mime_type)
                if file_text:
                    reply = await asyncio.to_thread(
                        claude_client.ask_claude_with_document,
                        history,
                        caption,
                        file_text,
                        filename,
                    )
                else:
                    reply = f"'{filename}' 파일 형식은 현재 텍스트 추출을 지원하지 않습니다.\n지원 형식: PDF, TXT, 마크다운, 코드 파일, CSV 등"
        finally:
            os.unlink(tmp_path)

        add_to_history(user_id, "user", caption or f"[파일 전송: {filename}]")
        add_to_history(user_id, "assistant", reply)
        await send_long_message(update, reply, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"문서 처리 오류: {e}")
        await update.message.reply_text(f"파일 처리 중 오류가 발생했습니다: {e}")


def _read_docx(path: str) -> str | None:
    """워드 파일에서 텍스트를 추출합니다."""
    try:
        from docx import Document
        doc = Document(path)
        text = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        if len(text) > 50000:
            text = text[:50000] + "\n\n[... 파일이 너무 길어 앞부분만 처리합니다 ...]"
        return text or None
    except Exception:
        return None


async def _read_file_text(path: str, mime_type: str) -> str | None:
    """파일에서 텍스트를 추출합니다."""
    text_mimes = [
        "text/", "application/json", "application/xml",
        "application/javascript", "application/x-yaml",
        "application/csv",
    ]
    is_text = any(mime_type.startswith(m) for m in text_mimes)

    if not is_text:
        # 확장자로 추가 판단
        text_extensions = {".txt", ".md", ".csv", ".json", ".xml", ".yaml",
                           ".yml", ".py", ".js", ".ts", ".html", ".css",
                           ".sh", ".log", ".ini", ".toml", ".env"}
        ext = os.path.splitext(path)[1].lower()
        is_text = ext in text_extensions

    if is_text:
        async with aiofiles.open(path, "r", encoding="utf-8", errors="replace") as f:
            content = await f.read()
        # 너무 긴 경우 앞부분만
        if len(content) > 50000:
            content = content[:50000] + "\n\n[... 파일이 너무 길어 앞부분만 처리합니다 ...]"
        return content

    return None


async def news_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """뉴스 알림 설정: /news 기업1,기업2,..."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_allowed(user_id):
        await update.message.reply_text("접근 권한이 없습니다.")
        return

    # context.args는 같은 줄만 인식 → 줄바꿈 입력도 처리
    full_text = update.message.text or ""
    _match = re.match(r"^/news(?:@\S+)?\s*([\s\S]*)", full_text, re.IGNORECASE)
    args_text = _match.group(1).strip() if _match else ""
    if not args_text:
        current = news_scheduler.get_subscription(chat_id)
        if current:
            await update.message.reply_text(
                f"📰 현재 뉴스 알림 설정:\n{', '.join(current)}\n\n"
                "매일 오전 7시(KST)에 뉴스를 전송합니다.\n\n"
                "변경: /news 기업1,기업2,...\n"
                "취소: /news\\_off",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "📰 **뉴스 자동 알림 설정**\n\n"
                "매일 오전 7시에 기업 뉴스를 자동으로 받아볼 수 있습니다.\n\n"
                "**사용법:**\n"
                "`/news 메리츠금융지주,SK하이닉스,현대차`\n\n"
                "기업명을 쉼표로 구분해서 입력해주세요.",
                parse_mode="Markdown"
            )
        return

    # 쉼표, 줄바꿈, 공백으로 분리
    companies = [c.strip() for c in re.split(r"[,\n]+", args_text) if c.strip()]
    if not companies:
        await update.message.reply_text("기업명을 입력해주세요.\n예: `/news 삼성전자,SK하이닉스`", parse_mode="Markdown")
        return

    news_scheduler.set_subscription(chat_id, companies)
    await update.message.reply_text(
        f"✅ 뉴스 알림이 설정되었습니다!\n\n"
        f"**등록 기업:** {', '.join(companies)}\n"
        f"**발송 시간:** 매일 오전 7시 (KST)\n\n"
        f"내일부터 자동으로 뉴스 브리핑을 보내드립니다. 📰\n"
        f"취소하려면 /news\\_off",
        parse_mode="Markdown"
    )


async def news_alert_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """뉴스 알림 취소: /news_off"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_allowed(user_id):
        return

    if news_scheduler.remove_subscription(chat_id):
        await update.message.reply_text("🔕 뉴스 알림이 취소되었습니다.")
    else:
        await update.message.reply_text("현재 설정된 뉴스 알림이 없습니다.")


async def news_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """지금 바로 뉴스 받기: /news_now"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_allowed(user_id):
        return

    companies = news_scheduler.get_subscription(chat_id)
    if not companies:
        await update.message.reply_text(
            "등록된 기업이 없습니다.\n먼저 /뉴스알림으로 기업을 등록해주세요."
        )
        return

    await update.message.reply_text(f"📰 뉴스 검색 중... ({', '.join(companies)}) ⏳")
    try:
        news_text = await asyncio.to_thread(news_scheduler.search_news_for_companies, companies)
        full_text = "📰 **기업 뉴스 브리핑**\n\n" + news_text
        for chunk in _split_text(full_text):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)
    except Exception as e:
        await update.message.reply_text(f"뉴스 검색 중 오류가 발생했습니다: {e}")


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "현재 지원하는 형식: 텍스트, 이미지, 문서 파일\n"
        "음성/동영상은 아직 지원하지 않습니다."
    )


async def post_init(application: Application) -> None:
    """봇 시작 시 명령어 목록 등록 및 스케줄러 시작"""
    await application.bot.set_my_commands([
        BotCommand("start", "대화 초기화"),
        BotCommand("clear", "대화 히스토리 삭제"),
        BotCommand("help", "도움말"),
        BotCommand("news", "기업 뉴스 자동 알림 설정"),
        BotCommand("news_off", "뉴스 알림 취소"),
        BotCommand("news_now", "지금 바로 뉴스 받기"),
    ])

    scheduler = news_scheduler.create_scheduler(application.bot)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("뉴스 스케줄러 시작됨")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN 환경 변수가 설정되지 않았습니다.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("news", news_alert_command))
    app.add_handler(CommandHandler("news_off", news_alert_cancel_command))
    app.add_handler(CommandHandler("news_now", news_now_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO | filters.AUDIO, handle_unsupported))

    logger.info("Claude 텔레그램 봇 시작됨")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
