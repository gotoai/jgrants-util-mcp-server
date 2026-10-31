"""Against the real Jグランツ API. Run with JGRANTS_LIVE=1."""

import json
import os
import re

import pytest
from mcp import Client

from jgrants_util_mcp_server import server
from jgrants_util_mcp_server.api import JGrantsClient
from jgrants_util_mcp_server.server import mcp

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("JGRANTS_LIVE") != "1", reason="set JGRANTS_LIVE=1"),
]


@pytest.fixture(autouse=True)
def fresh_client(monkeypatch):
    # Each test runs on its own event loop; the server's HTTP client binds to the
    # first loop that uses it, so share none between tests.
    monkeypatch.setattr(server, "_client", JGrantsClient())


def structured(result):
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


async def test_search_detail_and_attachment_end_to_end():
    async with Client(mcp) as client:
        found = structured(
            await client.call_tool(
                "search_subsidies", {"keyword": "補助金", "target_area_search": "東京都"}
            )
        )
        assert found["total_count"] > 0
        pdf = None
        for subsidy in found["subsidies"][:10]:
            detail = structured(
                await client.call_tool("get_subsidy_detail", {"subsidy_id": subsidy["id"]})
            )
            assert detail["portal_url"].startswith("https://www.jgrants-portal.go.jp/subsidy/")
            pdf = next(
                (a for a in detail["attachments"] if (a["name"] or "").lower().endswith(".pdf")),
                None,
            )
            if pdf:
                break
        if pdf is None:
            pytest.skip("no PDF attachment among the first results")
        result = await client.call_tool(
            "read_attachment",
            {"subsidy_id": detail["id"], "kind": pdf["kind"], "index": pdf["index"]},
        )
        if result.is_error:
            # A scanned PDF is refused, never passed off as read.
            assert "OCR" in result.content[0].text, result.content
            return
        text = structured(result)
        assert text["text"].startswith("--- page 1 ---")
        assert re.sub(r"--- page \d+ ---", "", text["text"]).strip()


async def test_overseas_area_is_accepted_by_the_api():
    async with Client(mcp) as client:
        structured(
            await client.call_tool(
                "search_subsidies",
                {"keyword": "補助金", "target_area_search": "海外", "acceptance": False},
            )
        )
