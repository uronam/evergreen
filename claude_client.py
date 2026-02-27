import base64
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS, SYSTEM_PROMPT


client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ask_claude(history: list[dict], user_message: str) -> str:
    """텍스트 메세지로 Claude에게 질문합니다."""
    messages = history + [{"role": "user", "content": user_message}]
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


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
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text


def ask_claude_with_document(history: list[dict], user_message: str, file_text: str, filename: str) -> str:
    """문서 내용과 함께 Claude에게 질문합니다."""
    doc_prompt = f"[첨부 파일: {filename}]\n\n{file_text}\n\n---\n\n{user_message or '위 문서를 요약하고 핵심 내용을 정리해 주세요.'}"
    return ask_claude(history, doc_prompt)
