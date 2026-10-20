"""The server against Kari's skill-style MCP contract, over a real MCP session."""

import re

from mcp import Client

from jgrants_util_mcp_server.guideline import GUIDELINE, SECTIONS
from jgrants_util_mcp_server.server import mcp

TOOL_DESCRIPTION_TARGET = 1000


async def test_instructions_are_short_and_point_to_the_guideline():
    async with Client(mcp) as client:
        instructions = client.instructions or ""
    assert 0 < len(instructions) <= 200, len(instructions)
    assert "load_guideline" in instructions


async def test_server_name_is_stable_ascii_and_title_is_set():
    async with Client(mcp) as client:
        info = client.server_info
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", info.name), info.name
    assert info.title


async def test_load_guideline_is_present_read_only_and_stands_alone():
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    tool = tools["load_guideline"]
    assert tool.annotations and tool.annotations.read_only_hint is True
    assert "before your first search" in (tool.description or "")


async def test_every_tool_description_is_short_and_tool_specific():
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {
        "load_guideline",
        "search_subsidies",
        "get_subsidy_detail",
        "read_attachment",
    }
    for tool in tools:
        description = tool.description or ""
        assert 0 < len(description) <= TOOL_DESCRIPTION_TARGET, (tool.name, len(description))
        if tool.name != "load_guideline":
            assert "出典" not in description, f"{tool.name}: conditions of use belong in the guideline"


async def test_tool_descriptions_have_no_docstring_layout():
    async with Client(mcp) as client:
        tools = (await client.list_tools()).tools
    for tool in tools:
        assert "\n" not in (tool.description or ""), tool.name


def test_guideline_carries_the_conditions_of_use():
    assert "出典：Jグランツ（jGrants）" in GUIDELINE


async def test_guideline_tool_takes_no_arguments_and_returns_the_whole_guideline():
    async with Client(mcp) as client:
        tool = {tool.name: tool for tool in (await client.list_tools()).tools}["load_guideline"]
        result = await client.call_tool("load_guideline", {})
    assert not tool.input_schema.get("properties")
    assert not result.is_error
    text = result.content[0].text
    assert text == GUIDELINE
    for section in SECTIONS.values():
        assert section in text
