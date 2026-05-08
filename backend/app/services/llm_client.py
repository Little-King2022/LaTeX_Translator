import json
from typing import Any

import httpx


class LLMClient:
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        stream: bool = False,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return _extract_chat_content(data)

    async def test(self) -> dict[str, Any]:
        text = await self.chat(
            [{"role": "user", "content": "Reply with JSON: {\"ok\": true}"}],
            temperature=0,
            max_tokens=64,
        )
        try:
            parsed = json.loads(strip_markdown_fence(text))
        except json.JSONDecodeError:
            parsed = {"raw": text}
        return {"ok": True, "response": parsed}


def strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _extract_chat_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response did not include choices")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("LLM response choice has an invalid shape")

    message = choice.get("message")
    content: Any = None
    message_keys: list[str] = []
    if isinstance(message, dict):
        message_keys = sorted(message.keys())
        content = message.get("content")

    text = _content_to_text(content)
    if not text and isinstance(choice.get("text"), str):
        text = choice["text"]
    if text:
        return text

    reasoning_chars = 0
    if isinstance(message, dict) and isinstance(message.get("reasoning_content"), str):
        reasoning_chars = len(message["reasoning_content"])
    finish_reason = choice.get("finish_reason")
    usage = data.get("usage")
    raise ValueError(
        "LLM response content was empty "
        f"(finish_reason={finish_reason!r}, reasoning_content_chars={reasoning_chars}, "
        f"message_keys={message_keys}, usage={usage})"
    )


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""
