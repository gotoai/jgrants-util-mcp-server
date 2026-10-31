"""A skill-style MCP server for the Jグランツ public subsidy API.

Built to Kari's skill-style MCP contract
(kari/docs/design_skill-style-mcp-server.md in the Kari repo): a one-sentence
`instructions`, a `load_guideline` tool carrying everything that concerns the
tool set as a whole — conditions of use included — and tool-specific
descriptions on the other tools.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from collections import OrderedDict
from importlib.metadata import version
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field

from .api import (
    ATTACHMENT_KINDS,
    MULTI_VALUE_SEPARATOR,
    PORTAL_URL,
    Area,
    AttachmentKind,
    Employees,
    Industry,
    JGrantsClient,
    JGrantsError,
    SortField,
    SortOrder,
    UsePurpose,
)
from .guideline import GUIDELINE
from .text import (
    AttachmentText,
    NoTextLayer,
    UnsupportedAttachment,
    attachment_text,
    html_to_text,
)

SERVER_NAME = "jgrants-util"

INSTRUCTIONS = (
    "Jグランツ（日本の補助金ポータル）の公開APIで、補助金の検索・詳細・募集要項を"
    "閲覧するツール群です。補助金や助成金を調べるときに使い、最初に load_guideline を"
    "呼んでください。"
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_ATTACHMENT_CHARS = 6000
MAX_ATTACHMENT_CHARS = 20000
ATTACHMENT_TEXT_CACHE_SIZE = 16
MIN_KEYWORD_CHARS = 2
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000

mcp = MCPServer(
    SERVER_NAME,
    title="Jグランツ補助金ユーティリティ",
    description="Unofficial MCP server for the Jグランツ public API. Not affiliated with the Digital Agency.",
    version=version("jgrants-util-mcp-server"),
    instructions=INSTRUCTIONS,
)

_client = JGrantsClient()
# Keyed by the attachment's content, not its position: the detail it comes from
# expires, and a revised or reordered attachment must not return the old text.
_attachment_texts: OrderedDict[str, AttachmentText] = OrderedDict()

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


@mcp.tool(
    description=(
        "Usage guideline for the Jグランツ tools: how to search, read details and attachments, "
        "what Jグランツ covers, and the conditions of use. Read it before your first search."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def load_guideline() -> str:
    return GUIDELINE


@mcp.tool(
    description=(
        "Search Jグランツ subsidies by keyword and filters. Returns one page of summaries with "
        "each subsidy's id and portal_url; total_count and next_offset tell whether more pages "
        "exist."
    ),
    annotations=_READ_ONLY,
)
async def search_subsidies(
    keyword: Annotated[
        str,
        Field(description="One search term, 2–255 characters, no spaces.", max_length=255),
    ],
    target_area_search: Annotated[Area | None, Field(description="Target area.")] = None,
    industry: Annotated[list[Industry] | None, Field(description="Industries, any of.")] = None,
    use_purpose: Annotated[list[UsePurpose] | None, Field(description="Purposes, any of.")] = None,
    target_number_of_employees: Annotated[
        Employees | None, Field(description="Employee-count bracket.")
    ] = None,
    acceptance: Annotated[bool, Field(description="Only subsidies open for applications now.")] = True,
    sort: SortField = "acceptance_end_datetime",
    order: SortOrder = "ASC",
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    keyword = keyword.strip()
    if len(keyword) < MIN_KEYWORD_CHARS:
        raise ToolError(f"keyword must be at least {MIN_KEYWORD_CHARS} characters.")
    if any(c.isspace() for c in keyword):
        raise ToolError(
            "keyword must be a single term without spaces. Put the area, industry, purpose "
            "or employee count in their own arguments, and try one term at a time."
        )
    params = {
        "keyword": keyword,
        "sort": sort,
        "order": order,
        "acceptance": "1" if acceptance else "0",
    }
    if target_area_search:
        params["target_area_search"] = target_area_search
    if industry:
        params["industry"] = MULTI_VALUE_SEPARATOR.join(industry)
    if use_purpose:
        params["use_purpose"] = MULTI_VALUE_SEPARATOR.join(use_purpose)
    if target_number_of_employees:
        params["target_number_of_employees"] = target_number_of_employees

    try:
        results = await _client.search(params)
    except JGrantsError as error:
        raise ToolError(str(error)) from error

    page = results[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(results) else None
    return {
        "total_count": len(results),
        "offset": offset,
        "next_offset": next_offset,
        "subsidies": [_summary(item) for item in page],
    }


@mcp.tool(
    description=(
        "Get one subsidy's full details: overview, eligibility, subsidy rate, amounts, dates, "
        "portal_url, and a list of its attachments (read them with read_attachment)."
    ),
    annotations=_READ_ONLY,
)
async def get_subsidy_detail(
    subsidy_id: Annotated[str, Field(description="The id from search_subsidies.", max_length=18)],
) -> dict[str, Any]:
    try:
        detail = await _client.detail(subsidy_id)
    except JGrantsError as error:
        raise ToolError(str(error)) from error

    return {
        "id": detail.get("id"),
        "title": detail.get("title"),
        "catch_phrase": detail.get("subsidy_catch_phrase"),
        "overview": html_to_text(detail.get("detail")),
        "use_purpose": detail.get("use_purpose"),
        "industry": detail.get("industry"),
        "target_area": detail.get("target_area_search"),
        "target_area_detail": detail.get("target_area_detail"),
        "target_employees": detail.get("target_number_of_employees"),
        "subsidy_rate": detail.get("subsidy_rate"),
        "max_amount_yen": detail.get("subsidy_max_limit"),
        "acceptance_start": detail.get("acceptance_start_datetime"),
        "acceptance_end": detail.get("acceptance_end_datetime"),
        "project_end_deadline": detail.get("project_end_deadline"),
        "online_application": detail.get("request_reception_presence"),
        "multiple_applications_allowed": detail.get("is_enable_multiple_request"),
        "portal_url": detail.get("front_subsidy_detail_page_url") or _portal_url(subsidy_id),
        "attachments": [
            {"kind": kind, "index": index, "name": file.get("name"), "size_bytes": _size(file)}
            for kind in ATTACHMENT_KINDS
            for index, file in enumerate(detail.get(kind) or [])
        ],
    }


@mcp.tool(
    description=(
        "Read an attachment's text (PDF, page by page) in pieces of max_chars; continue from "
        "next_offset. pages_without_text lists PDF pages that are images only. Other formats "
        "cannot be read here."
    ),
    annotations=_READ_ONLY,
)
async def read_attachment(
    subsidy_id: Annotated[str, Field(description="The subsidy's id.", max_length=18)],
    kind: Annotated[AttachmentKind, Field(description="Attachment kind, from get_subsidy_detail.")],
    index: Annotated[int, Field(ge=0, description="Attachment index within its kind.")] = 0,
    offset: Annotated[int, Field(ge=0, description="Character offset to read from.")] = 0,
    max_chars: Annotated[int, Field(ge=500, le=MAX_ATTACHMENT_CHARS)] = DEFAULT_ATTACHMENT_CHARS,
) -> dict[str, Any]:
    name, extracted = await _attachment(subsidy_id, kind, index)
    text = extracted.text
    piece = text[offset : offset + max_chars]
    end = offset + len(piece)
    return {
        "name": name,
        "total_chars": len(text),
        "offset": offset,
        "next_offset": end if end < len(text) else None,
        "pages_without_text": list(extracted.pages_without_text),
        "text": piece,
    }


async def _attachment(subsidy_id: str, kind: str, index: int) -> tuple[str, AttachmentText]:
    # Always through the detail, which is cached with an expiry, so the text
    # follows the attachment as Jグランツ currently has it.
    try:
        detail = await _client.detail(subsidy_id)
    except JGrantsError as error:
        raise ToolError(str(error)) from error
    files = detail.get(kind) or []
    if index >= len(files):
        raise ToolError(f"This subsidy has {len(files)} attachment(s) of kind {kind}.")
    file = files[index]
    name = file.get("name") or f"{kind}-{index}"
    data = file.get("data") or ""
    key = hashlib.sha256(f"{name}\0{data}".encode()).hexdigest()
    if key in _attachment_texts:
        _attachment_texts.move_to_end(key)
        return name, _attachment_texts[key]
    url = detail.get("front_subsidy_detail_page_url") or _portal_url(subsidy_id)
    try:
        # pypdf is synchronous and slow on large PDFs; off the event loop, other
        # requests and cancellation keep being served while it runs.
        extracted = await asyncio.to_thread(attachment_text, name, data)
    except NoTextLayer as error:
        raise ToolError(
            f"{name} has no text layer — it is a scanned image and needs OCR; open it from {url}."
        ) from error
    except UnsupportedAttachment as error:
        raise ToolError(f"{name} is not a PDF or text file; open it from {url}.") from error
    _attachment_texts[key] = extracted
    while len(_attachment_texts) > ATTACHMENT_TEXT_CACHE_SIZE:
        _attachment_texts.popitem(last=False)
    return name, extracted


def _summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "target_area": item.get("target_area_search"),
        "max_amount_yen": item.get("subsidy_max_limit"),
        "target_employees": item.get("target_number_of_employees"),
        "acceptance_start": item.get("acceptance_start_datetime"),
        "acceptance_end": item.get("acceptance_end_datetime"),
        "portal_url": _portal_url(item.get("id") or ""),
    }


def _portal_url(subsidy_id: str) -> str:
    return PORTAL_URL.format(id=subsidy_id)


def _size(file: dict[str, Any]) -> int:
    data = file.get("data") or ""
    return len(data) * 3 // 4 - data.count("=", -2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jグランツ skill-style MCP server")
    # stdio by default: a client that installed this package starts the process
    # itself and talks to it over the pipe, which needs no port, no host name and
    # no reverse proxy. Serving it over HTTP is the deliberate case, so it is the
    # one that says so.
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    # The HTTP options default to None so that giving one with stdio can be
    # caught: it would otherwise be ignored without a word.
    parser.add_argument("--host", help=f"HTTP only. Default {DEFAULT_HTTP_HOST}.")
    parser.add_argument("--port", type=int, help=f"HTTP only. Default {DEFAULT_HTTP_PORT}.")
    parser.add_argument(
        "--allowed-host",
        action="append",
        metavar="HOST[:PORT]",
        help="HTTP only. Host header to accept, e.g. demo.mcp.gotoai.com behind a reverse "
        "proxy. Repeatable.",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        given = [
            flag
            for flag, value in (
                ("--host", args.host),
                ("--port", args.port),
                ("--allowed-host", args.allowed_host),
            )
            if value is not None
        ]
        if given:
            parser.error(f"{', '.join(given)} need --transport streamable-http")
        mcp.run("stdio")
        return

    security = None
    if args.allowed_host:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=args.allowed_host,
            allowed_origins=[],
        )
    mcp.run(
        "streamable-http",
        host=args.host or DEFAULT_HTTP_HOST,
        port=args.port if args.port is not None else DEFAULT_HTTP_PORT,
        transport_security=security,
    )


if __name__ == "__main__":
    main()
