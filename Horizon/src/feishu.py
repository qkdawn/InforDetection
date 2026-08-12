"""Deliver generated Horizon reports to a Feishu group bot."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


FEISHU_API_ROOT = "https://open.feishu.cn/open-apis"


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    chat_id: str

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        values = {
            name: os.getenv(name, "").strip()
            for name in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHAT_ID")
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(
                "missing Feishu environment variables: " + ", ".join(missing)
            )
        return cls(
            app_id=values["FEISHU_APP_ID"],
            app_secret=values["FEISHU_APP_SECRET"],
            chat_id=values["FEISHU_CHAT_ID"],
        )


def _report_path(value: Any, *, root: Path, suffix: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"report artifact path must be a non-empty {suffix} path")
    path = Path(value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("report artifact path is outside the configured output directory")
    if path.suffix.lower() != suffix or not path.is_file():
        raise ValueError(f"report artifact is not an existing {suffix} file")
    return path


def validate_report_artifacts(report: dict[str, Any]) -> tuple[Path, list[Path]]:
    """Resolve and validate report files before sending them externally."""
    root = Path(os.getenv("HORIZON_REPORT_OUTPUT_DIR", "/app/output")).resolve()
    markdown = _report_path(report.get("markdown"), root=root, suffix=".md")
    raw_cards = report.get("cards")
    if not isinstance(raw_cards, list):
        raise ValueError("report cards must be a list")
    cards = [_report_path(path, root=root, suffix=".png") for path in raw_cards]
    return markdown, cards


class FeishuReportSender:
    """Upload report artifacts and send them to one Feishu group."""

    def __init__(self, config: FeishuConfig, *, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self._token = ""

    async def deliver(
        self,
        *,
        report: dict[str, Any],
        markdown: Path,
        cards: list[Path],
    ) -> dict[str, Any]:
        self._token = await self._tenant_access_token()
        await self._send_text(self._summary(report, len(cards)))

        image_message_ids = []
        for card in cards:
            image_key = await self._upload_image(card)
            image_message_ids.append(
                await self._send_message("image", {"image_key": image_key})
            )
            await asyncio.sleep(0.25)

        file_key = await self._upload_file(markdown)
        file_message_id = await self._send_message("file", {"file_key": file_key})
        return {
            "chat_id": self.config.chat_id,
            "card_count": len(image_message_ids),
            "image_message_ids": image_message_ids,
            "file_message_id": file_message_id,
        }

    async def _tenant_access_token(self) -> str:
        response = await self.client.post(
            f"{FEISHU_API_ROOT}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.config.app_id,
                "app_secret": self.config.app_secret,
            },
        )
        payload = self._payload(response, "Feishu authentication")
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Feishu authentication returned no access token")
        return token

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _upload_image(self, path: Path) -> str:
        with path.open("rb") as image:
            response = await self.client.post(
                f"{FEISHU_API_ROOT}/im/v1/images",
                headers=self._headers,
                data={"image_type": "message"},
                files={"image": (path.name, image, "image/png")},
            )
        payload = self._payload(response, f"uploading {path.name}")
        image_key = payload.get("data", {}).get("image_key")
        if not isinstance(image_key, str) or not image_key:
            raise RuntimeError(f"Feishu returned no image key for {path.name}")
        return image_key

    async def _upload_file(self, path: Path) -> str:
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as source:
            response = await self.client.post(
                f"{FEISHU_API_ROOT}/im/v1/files",
                headers=self._headers,
                data={"file_type": "stream", "file_name": path.name},
                files={"file": (path.name, source, media_type)},
            )
        payload = self._payload(response, f"uploading {path.name}")
        file_key = payload.get("data", {}).get("file_key")
        if not isinstance(file_key, str) or not file_key:
            raise RuntimeError(f"Feishu returned no file key for {path.name}")
        return file_key

    async def _send_text(self, text: str) -> str:
        return await self._send_message("text", {"text": text})

    async def _send_message(self, msg_type: str, content: dict[str, Any]) -> str:
        response = await self.client.post(
            f"{FEISHU_API_ROOT}/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers=self._headers,
            json={
                "receive_id": self.config.chat_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
        )
        payload = self._payload(response, f"sending {msg_type} message")
        message_id = payload.get("data", {}).get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise RuntimeError(f"Feishu returned no message ID for {msg_type} message")
        return message_id

    @staticmethod
    def _payload(response: httpx.Response, operation: str) -> dict[str, Any]:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"{operation} returned an invalid response")
        if payload.get("code", 0) != 0:
            raise RuntimeError(
                f"{operation} failed: code={payload.get('code')}, "
                f"message={payload.get('msg', 'unknown error')}"
            )
        return payload

    @staticmethod
    def _summary(report: dict[str, Any], card_count: int) -> str:
        return "\n".join(
            [
                f"{report.get('name') or 'Horizon 游戏创意雷达'} · {report.get('date', '')}",
                f"候选材料：{int(report.get('fetched') or 0)} 条",
                f"创意线索：{int(report.get('selected') or 0)} 条",
                f"报告卡片：{card_count} 张",
                "完整 Markdown 报告见随后发送的文件。",
            ]
        )


async def deliver_report_to_feishu(report: dict[str, Any]) -> dict[str, Any]:
    """Validate and deliver one report with environment-backed credentials."""
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    markdown, cards = validate_report_artifacts(report)
    async with httpx.AsyncClient(timeout=120.0) as client:
        sender = FeishuReportSender(FeishuConfig.from_env(), client=client)
        return await sender.deliver(report=report, markdown=markdown, cards=cards)
