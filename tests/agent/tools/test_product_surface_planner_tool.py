from __future__ import annotations

import pytest

from teai_builder.agent.tools.product_surface_planner import PlanProductSurfacesTool


@pytest.mark.asyncio
async def test_plan_product_surfaces_returns_desktop_solution_for_cursor_like_product() -> None:
    tool = PlanProductSurfacesTool()

    result = await tool.execute(
        project_name="cursor-suite",
        user_request=(
            "Build a Cursor-like AI coding app with a desktop app, website for downloads, "
            "user login, billing, and account management."
        ),
    )

    assert result["primary_platform"] == "desktop"
    assert result["request_kind"] == "multi-surface"
    assert result["scaffold_strategy"] == "solution-scaffold"
    assert result["recommended_scaffold_platform"] == "solution"
    assert result["recommended_scaffold_template"] == "desktop-suite"
    assert [surface["platform"] for surface in result["surfaces"]] == ["desktop", "backend", "web"]
    assert "auth" in result["shared_capabilities"]
    assert "account-management" in result["shared_capabilities"]
    assert result["should_block_scaffolding"] is False
    assert result["product_brief"]["backend"]["required"] is True
    assert result["product_brief"]["ui_direction"]["color_theme"]["primary"] == "#14b8a6"
    assert result["research_tracks"][0]["track"] == "product-shape"
    assert result["implementation_phases"][0]["name"] == "Product Definition"
    assert result["initial_tasks"][0]["title"] == "Expand the rough idea into a detailed product brief"


@pytest.mark.asyncio
async def test_plan_product_surfaces_keeps_mobile_game_native_not_html() -> None:
    tool = PlanProductSurfacesTool()

    result = await tool.execute(
        project_name="racing-fever",
        user_request="Build a car racing mobile game for Android and iOS with polished publishable gameplay.",
    )

    assert result["primary_platform"] == "mobile"
    assert result["scaffold_strategy"] == "single-scaffold"
    assert result["recommended_scaffold_platform"] == "mobile"
    assert [surface["platform"] for surface in result["surfaces"]] == ["mobile"]
    assert any("Do not collapse the native product" in note for note in result["notes"])
    assert result["product_brief"]["ui_direction"]["color_theme"]["primary"] == "#ef4444"
    assert "game loop polish" in result["product_brief"]["core_features"]


@pytest.mark.asyncio
async def test_plan_product_surfaces_uses_split_scaffold_for_extension_suite() -> None:
    tool = PlanProductSurfacesTool()

    result = await tool.execute(
        project_name="research-copilot",
        user_request=(
            "Build a Chrome extension with a companion dashboard, backend API, team workspaces, "
            "and account login."
        ),
    )

    assert result["primary_platform"] == "extension"
    assert result["request_kind"] == "multi-surface"
    assert result["scaffold_strategy"] == "split-scaffold"
    assert [step["platform"] for step in result["scaffold_plan"]] == ["extension", "backend", "web"]
    assert result["scaffold_plan"][0]["path"] == "research-copilot/extension"
    assert result["scaffold_plan"][2]["template"] == "saas"
    assert "team-workspaces" in result["shared_capabilities"]
    assert result["product_brief"]["backend"]["required"] is True
    assert any(task["id"] == "2.2" for task in result["initial_tasks"])
