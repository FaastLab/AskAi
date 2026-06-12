"""The MCP tool catalogue the inspector UI + stdio server share (pure)."""

from __future__ import annotations

from faastlab_askai_mcp.server import tool_specs


def test_catalogue_lists_the_expected_tools() -> None:
    names = {t["name"] for t in tool_specs("demo")}
    assert names == {"search_documents", "ask", "get_document", "get_summary", "list_recent"}


def test_every_tool_has_name_description_and_schema() -> None:
    for t in tool_specs("demo"):
        assert t["name"] and t["description"]
        schema = t["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_required_args_are_declared() -> None:
    by_name = {t["name"]: t for t in tool_specs("demo")}
    assert by_name["ask"]["inputSchema"]["required"] == ["question"]
    assert by_name["search_documents"]["inputSchema"]["required"] == ["query"]


def test_tenant_label_flows_into_descriptions() -> None:
    # The label is surfaced so an agent knows which corpus it's querying.
    assert "indian-railway" in tool_specs("indian-railway")[0]["description"]
