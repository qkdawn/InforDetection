"""Local HTTP bridge exposing structured Horizon stages to n8n."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .mcp.errors import HorizonMcpError
from .mcp.service import HorizonPipelineService
from .reporting import generate_xiaohongshu_report


_RUN_LOCK = threading.Lock()
_CADENCES = {"daily", "weekly", "reserve"}


def _read_request(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if length > 64 * 1024:
        raise ValueError("Request body is too large")
    if not length:
        return {}
    payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _require_run_id(options: dict[str, Any]) -> str:
    run_id = options.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    return run_id.strip()


def _parse_threshold(options: dict[str, Any]) -> float | None:
    threshold = options.get("threshold")
    if threshold is None:
        return None
    threshold = float(threshold)
    if not 0 <= threshold <= 10:
        raise ValueError("threshold must be between 0 and 10")
    return threshold


def _parse_cadence(options: dict[str, Any]) -> str:
    cadence = str(options.get("cadence") or "daily").strip().lower()
    if cadence not in _CADENCES:
        raise ValueError("cadence must be daily, weekly, or reserve")
    return cadence


def _stage_items(
    service: HorizonPipelineService,
    run_id: str,
    stage: str,
    *,
    max_items: int = 500,
) -> list[dict[str, Any]]:
    return service.get_run_stage(
        run_id=run_id,
        stage=stage,
        max_items=max_items,
    )["items"]


def _pipeline_stats(
    service: HorizonPipelineService,
    run_id: str,
) -> dict[str, Any]:
    meta = service.get_run_meta(run_id)["meta"]
    score = None
    if "scored_count" in meta:
        score = {
            "scored": meta.get("scored_count", 0),
            "selected": meta.get("selected_count", 0),
        }
    filtered = None
    if "filtered_count" in meta:
        filtered = {
            "kept": meta.get("filtered_count", 0),
            "removed_by_topic_dedup": meta.get("topic_dedup_removed", 0),
            "removed_by_balanced_digest": meta.get("balanced_digest_removed", 0),
        }
    enrichment = None
    if "enrichment_status" in meta:
        enrichment = {
            "status": meta.get("enrichment_status"),
            "enriched": meta.get("enriched_count", 0),
            "failed": meta.get("enrichment_failed_count", 0),
        }
    return {
        "fetch": {
            "fetched": meta.get("raw_count", 0),
            "raw_before_merge": meta.get("raw_count_before_merge", 0),
            "seen_duplicates_removed": meta.get("seen_duplicate_count", 0),
            "status": meta.get("fetch_status"),
        },
        "score": score,
        "filter": filtered,
        "enrich": enrichment,
        "meta": meta,
    }


async def _fetch_stage(options: dict[str, Any]) -> dict[str, Any]:
    removed_options = sorted({"topic_id", "pool", "content_topics"} & options.keys())
    if removed_options:
        raise ValueError(
            f"unsupported fetch options: {', '.join(removed_options)}; use cadence"
        )
    cadence = _parse_cadence(options)
    default_hours = {"daily": 24, "weekly": 168, "reserve": 720}
    hours = int(options.get("hours", default_hours[cadence]))
    if not 1 <= hours <= 720:
        raise ValueError("hours must be between 1 and 720")

    service = HorizonPipelineService()
    fetch_options: dict[str, Any] = {
        "hours": hours,
        "cadence": cadence,
        "content_topics": True,
    }
    if "deduplicate_seen" in options:
        fetch_options["deduplicate_seen"] = bool(options["deduplicate_seen"])
    fetch = await service.fetch_items(**fetch_options)
    return {
        "ok": True,
        "run_id": fetch["run_id"],
        "stage": "raw",
        "content_topics": fetch.get("content_topics", []),
        "cadence": cadence,
        "stats": {"fetch": fetch},
    }


async def _score_stage(options: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(options)
    service = HorizonPipelineService()
    raw = service.get_run_stage(run_id=run_id, stage="raw", max_items=1)
    if raw["count"] == 0:
        return {
            "ok": True,
            "run_id": run_id,
            "stage": "raw",
            "skipped": True,
            "stats": {"score": None},
        }

    score = await service.score_items(run_id=run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "stage": "scored",
        "stats": {"score": score},
    }


async def _filter_stage(options: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(options)
    threshold = _parse_threshold(options)
    topic_dedup = bool(options.get("topic_dedup", True))

    service = HorizonPipelineService()
    if not service.run_store.has_stage(run_id, "scored"):
        raw = service.get_run_stage(run_id=run_id, stage="raw", max_items=1)
        if raw["count"] == 0:
            return {
                "ok": True,
                "run_id": run_id,
                "stage": "raw",
                "skipped": True,
                "stats": {"filter": None},
            }

    filtered = await service.filter_items(
        run_id=run_id,
        threshold=threshold,
        topic_dedup=topic_dedup,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "stage": "filtered",
        "stats": {"filter": filtered},
    }


async def _enrich_stage(options: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(options)
    max_items = int(options.get("max_items", 500))
    if not 1 <= max_items <= 2000:
        raise ValueError("max_items must be between 1 and 2000")

    service = HorizonPipelineService()
    if not service.run_store.has_stage(run_id, "filtered"):
        raw = service.get_run_stage(run_id=run_id, stage="raw", max_items=1)
        if raw["count"] == 0:
            stats = _pipeline_stats(service, run_id)
            stats["enrich"] = None
            return {
                "ok": True,
                "run_id": run_id,
                "stage": "raw",
                "skipped": True,
                "items": [],
                "stats": stats,
            }

    filtered = service.get_run_stage(run_id=run_id, stage="filtered", max_items=1)
    if filtered["count"] == 0:
        stats = _pipeline_stats(service, run_id)
        stats["enrich"] = None
        return {
            "ok": True,
            "run_id": run_id,
            "stage": "filtered",
            "skipped": True,
            "items": [],
            "stats": stats,
        }

    enrichment = await service.enrich_items(run_id=run_id)
    stage = "enriched" if enrichment["status"] != "failure" else "filtered"
    stats = _pipeline_stats(service, run_id)
    stats["enrich"] = enrichment
    return {
        "ok": True,
        "run_id": run_id,
        "stage": stage,
        "items": _stage_items(service, run_id, stage, max_items=max_items),
        "stats": stats,
    }


async def _report_stage(options: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(options)
    max_cards = int(options.get("max_cards", 12))
    if not 4 <= max_cards <= 30:
        raise ValueError("max_cards must be between 4 and 30")

    service = HorizonPipelineService()
    if service.run_store.has_stage(run_id, "enriched"):
        stage = "enriched"
    elif service.run_store.has_stage(run_id, "filtered"):
        stage = "filtered"
    elif service.run_store.has_stage(run_id, "raw"):
        stage = "raw"
    else:
        raise ValueError("run_id must have a raw, filtered, or enriched stage")

    items = _stage_items(service, run_id, stage, max_items=2000)
    meta = service.get_run_meta(run_id)["meta"]
    report = await generate_xiaohongshu_report(
        run_id=run_id,
        items=items,
        meta=meta,
        max_cards=max_cards,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "stage": "report",
        "report": report,
    }


_POST_ROUTES = {
    "/fetch": _fetch_stage,
    "/score": _score_stage,
    "/filter": _filter_stage,
    "/enrich": _enrich_stage,
    "/report": _report_stage,
}


class N8nApiHandler(BaseHTTPRequestHandler):
    server_version = "HorizonN8nBridge/2.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path == "/topics":
            try:
                query = parse_qs(parsed.query)
                cadence = (query.get("cadence") or ["daily"])[0]
                result = HorizonPipelineService().list_topics(cadence=cadence)
                self._write_json(HTTPStatus.OK, {"ok": True, **result})
            except HorizonMcpError as exc:
                self._write_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    {"ok": False, "error": exc.message, "code": exc.code},
                )
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        stage_handler = _POST_ROUTES.get(self.path)
        if stage_handler is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
            return

        if not _RUN_LOCK.acquire(blocking=False):
            self._write_json(
                HTTPStatus.CONFLICT,
                {
                    "ok": False,
                    "error": "A Horizon pipeline stage is already in progress",
                },
            )
            return

        try:
            options = _read_request(self)
            result = asyncio.run(stage_handler(options))
            self._write_json(HTTPStatus.OK, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except HorizonMcpError as exc:
            self._write_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"ok": False, "error": exc.message, "code": exc.code},
            )
        except Exception as exc:  # pragma: no cover - process boundary safety net
            self.log_error("Pipeline failed: %s", exc)
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "Horizon pipeline failed"},
            )
        finally:
            _RUN_LOCK.release()

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"n8n-api: {format % args}", flush=True)


def main() -> None:
    host = os.getenv("HORIZON_API_HOST", "0.0.0.0")
    port = int(os.getenv("HORIZON_API_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), N8nApiHandler)
    print(f"Horizon n8n bridge listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
