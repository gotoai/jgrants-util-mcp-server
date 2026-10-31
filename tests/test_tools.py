"""Tool behaviour with the Jグランツ API replaced by canned answers."""

import base64
import copy
import io
import json
import threading

import pytest
from mcp import Client
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

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


def pdf_base64(*pages: str) -> str:
    """A PDF whose pages carry these texts; an empty string makes an image-only page."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for text in pages:
        page = writer.add_blank_page(612, 792)
        if text:
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
    out = io.BytesIO()
    writer.write(out)
    return base64.b64encode(out.getvalue()).decode()


class FakeClient:
    def __init__(self):
        self.searches: list[dict[str, str]] = []
        self.detail_value = copy.deepcopy(DETAIL)

    async def search(self, params):
        self.searches.append(params)
        return SEARCH_RESULTS

    async def detail(self, subsidy_id):
        return self.detail_value


def guidelines(fake, name, data):
    fake.detail_value["application_guidelines"] = [{"name": name, "data": data}]


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


@pytest.mark.parametrize("keyword", ["  ", " a ", "\u3000x\u3000"])
async def test_search_checks_the_keyword_length_after_trimming(fake, keyword):
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_subsidies", {"keyword": keyword})
    assert result.is_error
    assert "at least 2 characters" in result.content[0].text
    assert fake.searches == []


async def test_search_accepts_overseas_as_an_area(fake):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_subsidies", {"keyword": "輸出", "target_area_search": "海外"}
        )
    assert not result.is_error, result.content
    assert fake.searches[0]["target_area_search"] == "海外"


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


async def test_read_attachment_follows_a_revised_attachment(fake):
    args = {"subsidy_id": DETAIL["id"], "kind": "application_guidelines"}
    guidelines(fake, "公募要領.txt", base64.b64encode("第1版".encode()).decode())
    async with Client(server.mcp) as client:
        first = structured(await client.call_tool("read_attachment", args))
        guidelines(fake, "公募要領.txt", base64.b64encode("第2版".encode()).decode())
        second = structured(await client.call_tool("read_attachment", args))
    assert (first["text"], second["text"]) == ("第1版", "第2版")


async def test_read_attachment_extracts_off_the_event_loop(fake, monkeypatch):
    threads = []

    def recording(name, data):
        threads.append(threading.get_ident())
        return attachment_text(name, data)

    monkeypatch.setattr(server, "attachment_text", recording)
    async with Client(server.mcp) as client:
        structured(
            await client.call_tool(
                "read_attachment", {"subsidy_id": DETAIL["id"], "kind": "application_guidelines"}
            )
        )
    assert threads and threads[0] != threading.get_ident()


async def test_read_attachment_lists_pdf_pages_without_text(fake):
    guidelines(fake, "公募要領.pdf", pdf_base64("Eligibility", "", "Expenses"))
    async with Client(server.mcp) as client:
        text = structured(
            await client.call_tool(
                "read_attachment", {"subsidy_id": DETAIL["id"], "kind": "application_guidelines"}
            )
        )
    assert text["pages_without_text"] == [2]
    assert "Eligibility" in text["text"] and "Expenses" in text["text"]


async def test_read_attachment_refuses_a_scanned_pdf_with_the_portal_url(fake):
    guidelines(fake, "公募要領.pdf", pdf_base64("", ""))
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "read_attachment", {"subsidy_id": DETAIL["id"], "kind": "application_guidelines"}
        )
    assert result.is_error
    assert "OCR" in result.content[0].text
    assert DETAIL["front_subsidy_detail_page_url"] in result.content[0].text


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
    assert attachment_text("readme.txt", data).text == "公募要領"
    with pytest.raises(UnsupportedAttachment):
        attachment_text("form.docx", base64.b64encode(b"PK").decode())


@pytest.mark.parametrize(
    "argv", [["--port", "9000"], ["--allowed-host", "demo.mcp.gotoai.com"], ["--host", "0.0.0.0"]]
)
def test_main_refuses_http_options_with_stdio(monkeypatch, argv):
    runs = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: runs.append(a))
    monkeypatch.setattr("sys.argv", ["jgrants-util-mcp-server", *argv])
    with pytest.raises(SystemExit):
        server.main()
    assert runs == []


def test_main_serves_http_with_defaults(monkeypatch):
    runs = []
    monkeypatch.setattr(server.mcp, "run", lambda *a, **k: runs.append((a, k)))
    monkeypatch.setattr("sys.argv", ["jgrants-util-mcp-server", "--transport", "streamable-http"])
    server.main()
    [(args, kwargs)] = runs
    assert args == ("streamable-http",)
    assert (kwargs["host"], kwargs["port"], kwargs["transport_security"]) == ("127.0.0.1", 8000, None)
