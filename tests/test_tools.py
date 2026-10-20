"""Tool behaviour with the Jグランツ API replaced by canned answers."""

import base64
import json

import pytest
from mcp import Client

from jgrants_util_mcp_server import server
from jgrants_util_mcp_server.text import UnsupportedAttachment, attachment_text, html_to_text

SEARCH_RESULTS = [
    {
        "id": f"a0W00000000000{n:04d}",
        "title": f"補助金{n}",
        "target_area_search": "東京都",
        "subsidy_max_limit": 1000000,
        "target_number_of_employees": "300名以下",
        "acceptance_start_datetime": "2026-04-01T00:00:00.000Z",
        "acceptance_end_datetime": "2027-03-31T14:59:00.000Z",
    }
    for n in range(25)
]

DETAIL = {
    "id": "a0W2x000005iqyXEAQ",
    "title": "テスト補助金",
    "detail": "<p><strong>■目的</strong></p><p>創業を支援します。</p><ul><li>要件A</li></ul>",
    "subsidy_max_limit": 0,
    "front_subsidy_detail_page_url": "https://www.jgrants-portal.go.jp/subsidy/a0W2x000005iqyXEAQ",
    "application_guidelines": [
        {"name": "公募要領.txt", "data": base64.b64encode("第1条 目的\n".encode() * 500).decode()}
    ],
    "application_form": [{"name": "様式.docx", "data": base64.b64encode(b"PK\x03\x04").decode()}],
}


class FakeClient:
    def __init__(self):
        self.searches: list[dict[str, str]] = []

    async def search(self, params):
        self.searches.append(params)
        return SEARCH_RESULTS

    async def detail(self, subsidy_id):
        return DETAIL


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(server, "_client", client)
    monkeypatch.setattr(server, "_attachment_texts", type(server._attachment_texts)())
    return client


def structured(result):
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


async def test_search_pages_results_and_joins_multi_value_filters(fake):
    async with Client(server.mcp) as client:
        first = structured(
            await client.call_tool(
                "search_subsidies",
                {
                    "keyword": "創業",
                    "target_area_search": "東京都",
                    "industry": ["情報通信業", "製造業"],
                    "limit": 10,
                },
            )
        )
        last = structured(
            await client.call_tool("search_subsidies", {"keyword": "創業", "offset": 20})
        )
    assert first["total_count"] == 25
    assert len(first["subsidies"]) == 10 and first["next_offset"] == 10
    assert first["subsidies"][0]["portal_url"].endswith("/subsidy/a0W000000000000000")
    assert len(last["subsidies"]) == 5 and last["next_offset"] is None
    sent = fake.searches[0]
    assert sent["industry"] == "情報通信業 / 製造業"
    assert sent["acceptance"] == "1" and sent["target_area_search"] == "東京都"


async def test_search_rejects_a_keyword_with_spaces_with_advice(fake):
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_subsidies", {"keyword": "港区 スタートアップ"})
    assert result.is_error
    assert "without spaces" in result.content[0].text
    assert fake.searches == []


async def test_search_rejects_a_value_outside_the_api_enum(fake):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_subsidies", {"keyword": "創業", "target_area_search": "港区"}
        )
    assert result.is_error


async def test_detail_lists_attachments_without_their_data(fake):
    async with Client(server.mcp) as client:
        detail = structured(
            await client.call_tool("get_subsidy_detail", {"subsidy_id": DETAIL["id"]})
        )
    assert detail["overview"].startswith("■目的")
    assert "・要件A" in detail["overview"]
    assert detail["portal_url"] == DETAIL["front_subsidy_detail_page_url"]
    assert [a["kind"] for a in detail["attachments"]] == ["application_guidelines", "application_form"]
    assert "data" not in json.dumps(detail["attachments"])


async def test_read_attachment_pages_through_the_text(fake):
    async with Client(server.mcp) as client:
        first = structured(
            await client.call_tool(
                "read_attachment",
                {"subsidy_id": DETAIL["id"], "kind": "application_guidelines", "max_chars": 1000},
            )
        )
        second = structured(
            await client.call_tool(
                "read_attachment",
                {
                    "subsidy_id": DETAIL["id"],
                    "kind": "application_guidelines",
                    "offset": first["next_offset"],
                    "max_chars": 1000,
                },
            )
        )
    assert first["total_chars"] == len("第1条 目的\n" * 500)
    assert len(first["text"]) == 1000 and first["next_offset"] == 1000
    assert second["offset"] == 1000


async def test_read_attachment_explains_an_unreadable_format(fake):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "read_attachment", {"subsidy_id": DETAIL["id"], "kind": "application_form"}
        )
    assert result.is_error
    assert DETAIL["front_subsidy_detail_page_url"] in result.content[0].text


def test_html_to_text_keeps_lines_and_drops_markup():
    assert html_to_text('<p><span style="x">A&amp;B</span></p><p><br></p><p>C</p>') == "A&B\n\nC"
    assert html_to_text(None) == ""


def test_attachment_text_reads_shift_jis_text_and_refuses_word():
    data = base64.b64encode("公募要領".encode("cp932")).decode()
    assert attachment_text("readme.txt", data) == "公募要領"
    with pytest.raises(UnsupportedAttachment):
        attachment_text("form.docx", base64.b64encode(b"PK").decode())
