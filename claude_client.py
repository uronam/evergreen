import base64
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS, SYSTEM_PROMPT


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH_TOOL = [{"type": "web_search_20250305", "name": "web_search"}]
WEB_SEARCH_BETAS = ["web-search-2025-03-05"]


def _extract_text(content: list) -> str:
    """응답 content 블록에서 텍스트만 추출합니다."""
    return "".join(
        block.text for block in content
        if hasattr(block, "type") and block.type == "text" and hasattr(block, "text")
    )


def ask_claude(history: list[dict], user_message: str) -> str:
    """텍스트 메세지로 Claude에게 질문합니다."""
    messages = history + [{"role": "user", "content": user_message}]
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=WEB_SEARCH_TOOL,
        messages=messages,
        betas=WEB_SEARCH_BETAS,
    )
    return _extract_text(response.content)


def ask_claude_with_image(history: list[dict], user_message: str, image_data: bytes, media_type: str) -> str:
    """이미지와 함께 Claude에게 질문합니다."""
    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_b64,
            },
        },
        {"type": "text", "text": user_message or "이 이미지를 분석하고 설명해 주세요."},
    ]
    messages = history + [{"role": "user", "content": content}]
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=WEB_SEARCH_TOOL,
        messages=messages,
        betas=WEB_SEARCH_BETAS,
    )
    return _extract_text(response.content)


def ask_claude_with_document(history: list[dict], user_message: str, file_text: str, filename: str) -> str:
    """문서 내용과 함께 Claude에게 질문합니다."""
    doc_prompt = f"[첨부 파일: {filename}]\n\n{file_text}\n\n---\n\n{user_message or '위 문서를 요약하고 핵심 내용을 정리해 주세요.'}"
    return ask_claude(history, doc_prompt)


def ask_claude_with_pdf(history: list[dict], user_message: str, pdf_data: bytes) -> str:
    """PDF를 직접 Claude에게 전송합니다 (Claude API 네이티브 PDF 지원)."""
    pdf_b64 = base64.standard_b64encode(pdf_data).decode("utf-8")
    content = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        },
        {"type": "text", "text": user_message or "이 PDF 문서를 요약하고 핵심 내용을 정리해 주세요."},
    ]
    messages = history + [{"role": "user", "content": content}]
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=WEB_SEARCH_TOOL,
        messages=messages,
        betas=WEB_SEARCH_BETAS,
    )
    return _extract_text(response.content)


def stream_claude(history: list[dict], user_message: str):
    """Claude 응답을 스트리밍으로 생성합니다."""
    messages = history + [{"role": "user", "content": user_message}]
    with client.beta.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=WEB_SEARCH_TOOL,
        messages=messages,
        betas=WEB_SEARCH_BETAS,
    ) as stream:
        for text in stream.text_stream:
            yield text
