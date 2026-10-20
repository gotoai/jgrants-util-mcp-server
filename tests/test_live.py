"""Against the real Jグランツ API. Run with JGRANTS_LIVE=1."""

import json
import os

import pytest
from mcp import Client

from jgrants_util_mcp_server.server import mcp

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("JGRANTS_LIVE") != "1", reason="set JGRANTS_LIVE=1"),
]


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
        text = structured(
            await client.call_tool(
                "read_attachment",
                {"subsidy_id": detail["id"], "kind": pdf["kind"], "index": pdf["index"]},
            )
        )
        assert text["total_chars"] > 0 and text["text"].startswith("--- page 1 ---")
