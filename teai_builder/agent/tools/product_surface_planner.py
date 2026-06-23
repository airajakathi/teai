"""Structured product surface planner for production-grade app builds."""

from __future__ import annotations

from typing import Any

from teai_builder.agent.tools.base import Tool, tool_parameters
from teai_builder.agent.tools.project_state import VALID_PLATFORMS
from teai_builder.agent.tools.schema import ArraySchema, BooleanSchema, ObjectSchema, StringSchema, tool_parameters_schema

_SURFACE_PLATFORMS = ("web", "mobile", "desktop", "cli", "backend", "extension", "bot", "solution")
_TARGETABLE_SURFACES = ("web", "mobile", "desktop", "cli", "backend", "extension", "bot")

_PRIMARY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mobile": (
        "mobile", "android", "ios", "iphone", "ipad", "expo", "react native", "play store",
        "app store", "touch", "car racing", "racing game", "mobile game",
    ),
    "desktop": (
        "desktop", "electron", "mac", "windows", "linux", "cursor", "ide", "editor",
        "native client", "installable desktop",
    ),
    "extension": (
        "extension", "chrome extension", "browser extension", "firefox addon", "firefox add-on",
        "edge extension", "content script",
    ),
    "bot": (
        "bot", "telegram bot", "discord bot", "slack bot", "whatsapp bot", "chatbot", "assistant bot",
    ),
    "cli": (
        "cli", "command line", "terminal app", "shell tool", "developer tool", "console app",
    ),
    "backend": (
        "backend", "api", "service", "server", "headless", "microservice", "webhook",
    ),
    "web": (
        "web", "website", "web app", "webapp", "dashboard", "portal", "landing page", "browser app",
        "admin panel", "frontend", "site",
    ),
}

_BACKEND_KEYWORDS = (
    "api", "backend", "server", "auth", "login", "account", "billing", "subscription", "sync",
    "cloud", "multiplayer", "leaderboard", "real-time", "realtime", "team", "workspace", "tenant",
    "dashboard", "admin", "webhook", "download", "release", "updates", "analytics",
)
_WEB_COMPANION_KEYWORDS = (
    "website", "landing", "marketing", "dashboard", "portal", "admin", "account", "download",
    "billing", "subscription", "manage", "team", "workspace", "browser",
)
_ACCOUNT_KEYWORDS = (
    "auth", "login", "account", "billing", "subscription", "team", "workspace", "tenant",
)
_GAME_KEYWORDS = (
    "game", "racing", "leaderboard", "multiplayer", "single-player", "single player", "cloud save",
)


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _display_name(value: str) -> str:
    cleaned = " ".join(part for part in str(value).replace("_", " ").replace("-", " ").split() if part)
    return cleaned.title() or "Project"


@tool_parameters(
    tool_parameters_schema(
        project_name=StringSchema("Project name for the planned product."),
        user_request=StringSchema(
            "Raw product idea or user request. Include the real request, not only the guessed platform.",
            min_length=3,
        ),
        platform_hint=StringSchema(
            "Optional explicit platform hint from the user or caller.",
            enum=list(_SURFACE_PLATFORMS) + ["unknown"],
            nullable=True,
        ),
        target_surfaces=ArraySchema(
            StringSchema(enum=list(_TARGETABLE_SURFACES)),
            description="Optional explicit delivery surfaces already requested by the user.",
            nullable=True,
        ),
        allow_multi_platform=BooleanSchema(
            description="Allow the planner to recommend multiple coordinated surfaces when the request implies them.",
            default=True,
        ),
        required=["project_name", "user_request"],
    )
)
class PlanProductSurfacesTool(Tool):
    """Analyze a product request into a structured surface and scaffold plan."""

    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "plan_product_surfaces"

    @property
    def description(self) -> str:
        return (
            "Analyze a software product request into a structured surface map, "
            "clarification list, and scaffold strategy. Use this before "
            "scaffold_project for any serious product build."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        project_name: str,
        user_request: str,
        platform_hint: str | None = None,
        target_surfaces: list[str] | None = None,
        allow_multi_platform: bool = True,
        **_: Any,
    ) -> dict[str, Any]:
        text = _normalize_text(user_request)
        explicit = self._explicit_surfaces(platform_hint, target_surfaces)
        detected = self._detected_surfaces(text)
        primary = self._choose_primary_platform(text, platform_hint, explicit, detected)

        surfaces = self._plan_surfaces(
            text=text,
            primary=primary,
            explicit=explicit,
            detected=detected,
            allow_multi_platform=allow_multi_platform,
        )
        shared_capabilities = self._shared_capabilities(text, surfaces)
        clarification_questions = self._clarification_questions(text, primary, surfaces, explicit)
        should_block = primary == "unknown"
        request_kind = "multi-surface" if len(surfaces) > 1 else "single-surface"
        scaffold_strategy, scaffold_plan = self._scaffold_strategy(project_name, primary, surfaces, text)

        recommended_scaffold_platform = scaffold_plan[0]["platform"] if scaffold_plan else primary
        recommended_scaffold_template = scaffold_plan[0]["template"] if scaffold_plan else None
        summary = self._summary(primary, surfaces, shared_capabilities, request_kind)
        notes = self._notes(text=text, primary=primary, surfaces=surfaces, scaffold_strategy=scaffold_strategy)
        product_brief = self._product_brief(
            project_name=project_name,
            text=text,
            primary=primary,
            surfaces=surfaces,
            shared_capabilities=shared_capabilities,
        )
        research_tracks = self._research_tracks(primary=primary, surfaces=surfaces, shared_capabilities=shared_capabilities)
        implementation_phases = self._implementation_phases(primary=primary, surfaces=surfaces)
        initial_tasks = self._initial_tasks(primary=primary, surfaces=surfaces)

        return {
            "project_name": project_name,
            "request_kind": request_kind,
            "primary_platform": primary,
            "recommended_scaffold_platform": recommended_scaffold_platform,
            "recommended_scaffold_template": recommended_scaffold_template,
            "scaffold_strategy": scaffold_strategy,
            "scaffold_plan": scaffold_plan,
            "surfaces": surfaces,
            "shared_capabilities": shared_capabilities,
            "clarification_questions": clarification_questions,
            "should_block_scaffolding": should_block,
            "summary": summary,
            "notes": notes,
            "product_brief": product_brief,
            "research_tracks": research_tracks,
            "implementation_phases": implementation_phases,
            "initial_tasks": initial_tasks,
        }

    @staticmethod
    def _explicit_surfaces(platform_hint: str | None, target_surfaces: list[str] | None) -> list[str]:
        surfaces: list[str] = []
        normalized_hint = (platform_hint or "").strip().lower()
        if normalized_hint in VALID_PLATFORMS and normalized_hint not in {"solution", "unknown"}:
            surfaces.append(normalized_hint)
        for value in target_surfaces or []:
            normalized = str(value or "").strip().lower()
            if normalized in _TARGETABLE_SURFACES:
                surfaces.append(normalized)
        return _unique_preserve_order(surfaces)

    @staticmethod
    def _detected_surfaces(text: str) -> list[str]:
        detected: list[str] = []
        for platform, keywords in _PRIMARY_KEYWORDS.items():
            if _has_any(text, keywords):
                detected.append(platform)
        return _unique_preserve_order(detected)

    @staticmethod
    def _choose_primary_platform(
        text: str,
        platform_hint: str | None,
        explicit: list[str],
        detected: list[str],
    ) -> str:
        normalized_hint = (platform_hint or "").strip().lower()
        if normalized_hint in _TARGETABLE_SURFACES:
            return normalized_hint
        if explicit:
            for candidate in explicit:
                if candidate in {"mobile", "desktop", "extension", "bot", "web", "cli", "backend"}:
                    return candidate
        if "mobile" in detected:
            return "mobile"
        if "desktop" in detected:
            return "desktop"
        if "extension" in detected:
            return "extension"
        if "bot" in detected:
            return "bot"
        if "web" in detected:
            return "web"
        if "cli" in detected:
            return "cli"
        if "backend" in detected:
            return "backend"
        return "unknown"

    @classmethod
    def _plan_surfaces(
        cls,
        *,
        text: str,
        primary: str,
        explicit: list[str],
        detected: list[str],
        allow_multi_platform: bool,
    ) -> list[dict[str, Any]]:
        ordered: list[str] = []
        if primary != "unknown":
            ordered.append(primary)
        ordered.extend(explicit)
        ordered.extend(detected)

        needs_backend = cls._needs_backend(text, primary, explicit, detected)
        needs_web = cls._needs_companion_web(text, primary, explicit, detected, needs_backend)

        if allow_multi_platform:
            if needs_backend:
                ordered.append("backend")
            if needs_web:
                ordered.append("web")

        if primary == "unknown":
            ordered = []

        normalized_order = _unique_preserve_order(ordered)
        priority = {
            "backend": 1,
            "web": 2,
            "mobile": 3,
            "desktop": 3,
            "extension": 4,
            "bot": 4,
            "cli": 5,
        }
        normalized_order.sort(
            key=lambda platform: (
                0 if platform == primary else priority.get(platform, 9),
                ordered.index(platform),
            )
        )

        surfaces: list[dict[str, Any]] = []
        for platform in normalized_order:
            if platform not in _TARGETABLE_SURFACES:
                continue
            role = cls._surface_role(platform, primary)
            surfaces.append(
                {
                    "platform": platform,
                    "role": role,
                    "required": True if platform in {primary, "backend"} else allow_multi_platform,
                    "reason": cls._surface_reason(platform, role, text),
                }
            )
        return surfaces

    @staticmethod
    def _needs_backend(text: str, primary: str, explicit: list[str], detected: list[str]) -> bool:
        if "backend" in explicit or "backend" in detected or primary == "backend":
            return True
        if primary == "web" and _has_any(text, _BACKEND_KEYWORDS):
            return True
        if primary in {"desktop", "mobile", "extension", "bot"} and _has_any(text, _BACKEND_KEYWORDS):
            return True
        return False

    @staticmethod
    def _needs_companion_web(
        text: str,
        primary: str,
        explicit: list[str],
        detected: list[str],
        needs_backend: bool,
    ) -> bool:
        if primary == "web":
            return False
        if "web" in explicit or "web" in detected:
            return True
        if primary in {"desktop", "mobile", "extension", "bot"} and _has_any(text, _WEB_COMPANION_KEYWORDS):
            return True
        if primary in {"desktop", "mobile"} and needs_backend and _has_any(text, _ACCOUNT_KEYWORDS):
            return True
        return False

    @staticmethod
    def _surface_role(platform: str, primary: str) -> str:
        if platform == primary:
            return "primary"
        if platform == "backend":
            return "shared-backend"
        if platform == "web":
            return "companion-web"
        return "companion"

    @staticmethod
    def _surface_reason(platform: str, role: str, text: str) -> str:
        if role == "primary":
            return f"Primary delivery surface inferred for the request: {platform}."
        if platform == "backend":
            if _has_any(text, _ACCOUNT_KEYWORDS):
                return "Shared backend needed for auth, accounts, billing, or synchronized state."
            if _has_any(text, _GAME_KEYWORDS):
                return "Backend needed for online gameplay features such as leaderboards, multiplayer, or cloud saves."
            return "Shared backend needed for APIs, data storage, and cross-surface coordination."
        if platform == "web":
            return "Companion web surface needed for downloads, account management, admin, or marketing flows."
        return f"Companion {platform} surface was requested or inferred from the product brief."

    @staticmethod
    def _shared_capabilities(text: str, surfaces: list[dict[str, Any]]) -> list[str]:
        platforms = {surface["platform"] for surface in surfaces}
        capabilities: list[str] = []
        if "backend" in platforms:
            capabilities.append("api-contract")
            capabilities.append("persistent-storage")
        if _has_any(text, _ACCOUNT_KEYWORDS):
            capabilities.extend(["auth", "account-management"])
        if "web" in platforms and any(platform in platforms for platform in {"desktop", "mobile", "extension", "bot"}):
            capabilities.append("release-and-account-portal")
        if "desktop" in platforms or "mobile" in platforms:
            capabilities.append("publishable-runtime")
        if _has_any(text, ("billing", "subscription", "payments")):
            capabilities.append("billing")
        if _has_any(text, ("team", "workspace", "collaboration", "collab")):
            capabilities.append("team-workspaces")
        if _has_any(text, ("multiplayer", "leaderboard", "realtime", "real-time", "cloud save")):
            capabilities.append("sync-and-realtime")
        if "bot" in platforms or "extension" in platforms:
            capabilities.append("background-jobs")
        return _unique_preserve_order(capabilities)

    @staticmethod
    def _clarification_questions(
        text: str,
        primary: str,
        surfaces: list[dict[str, Any]],
        explicit: list[str],
    ) -> list[str]:
        questions: list[str] = []
        if primary == "unknown":
            questions.append("Which platform should ship first: web, mobile, desktop, extension, bot, backend, or CLI?")
        if primary in {"mobile", "desktop"} and "web" in {surface["platform"] for surface in surfaces} and "web" not in explicit:
            questions.append("Should the first delivery also include a website for account management, downloads, or admin flows?")
        if primary in {"mobile", "desktop"} and not _has_any(text, ("android", "ios", "windows", "mac", "linux")):
            if primary == "mobile":
                questions.append("Which mobile stores matter first: iOS, Android, or both?")
            else:
                questions.append("Which desktop targets matter first: macOS, Windows, Linux, or all three?")
        if primary == "mobile" and _has_any(text, _GAME_KEYWORDS) and not _has_any(
            text, ("multiplayer", "single-player", "single player", "leaderboard", "cloud save")
        ):
            questions.append("Is the game single-player only, or should v1 include multiplayer, leaderboards, or cloud saves?")
        if "backend" in {surface["platform"] for surface in surfaces} and _has_any(text, _ACCOUNT_KEYWORDS):
            questions.append("Do you need user accounts, billing, and team workspaces in v1, or only a single-user local build first?")
        return _unique_preserve_order(questions)

    @staticmethod
    def _scaffold_strategy(
        project_name: str,
        primary: str,
        surfaces: list[dict[str, Any]],
        text: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        platforms = [surface["platform"] for surface in surfaces]
        if primary in {"desktop", "mobile"} and {"web", "backend"}.issubset(platforms):
            template = "desktop-suite" if primary == "desktop" else "mobile-suite"
            return (
                "solution-scaffold",
                [
                    {
                        "platform": "solution",
                        "template": template,
                        "path": project_name,
                        "reason": "Current scaffold tool can bootstrap the native surface together with shared web and backend layers.",
                    }
                ],
            )

        if len(platforms) <= 1 and primary != "unknown":
            return (
                "single-scaffold",
                [
                    {
                        "platform": primary,
                        "template": None,
                        "path": project_name,
                        "reason": "A single platform scaffold is sufficient for the current request.",
                    }
                ],
            )

        steps: list[dict[str, Any]] = []
        for platform in platforms:
            template = "saas" if platform == "web" and "backend" in platforms and _has_any(
                text, _ACCOUNT_KEYWORDS + ("dashboard", "admin", "portal")
            ) else None
            path = f"{project_name}/{platform}"
            steps.append(
                {
                    "platform": platform,
                    "template": template,
                    "path": path,
                    "reason": "Split scaffold required because the current scaffold tool has no single bundled starter for this exact surface mix.",
                }
            )
        return "split-scaffold", steps

    @staticmethod
    def _summary(
        primary: str,
        surfaces: list[dict[str, Any]],
        shared_capabilities: list[str],
        request_kind: str,
    ) -> str:
        surface_names = ", ".join(surface["platform"] for surface in surfaces) or "unknown"
        if primary == "unknown":
            return "Planner could not safely infer the primary platform. Ask clarifying questions before scaffolding."
        capability_suffix = ""
        if shared_capabilities:
            capability_suffix = f" Shared capabilities: {', '.join(shared_capabilities)}."
        return (
            f"Treat this as a {request_kind} product led by {primary}. "
            f"Planned surfaces: {surface_names}.{capability_suffix}"
        )

    @staticmethod
    def _notes(
        *,
        text: str,
        primary: str,
        surfaces: list[dict[str, Any]],
        scaffold_strategy: str,
    ) -> list[str]:
        notes: list[str] = []
        if primary in {"mobile", "desktop"}:
            notes.append("Do not collapse the native product into a browser-only HTML file.")
        if scaffold_strategy == "split-scaffold":
            notes.append("Use the scaffold_plan paths to create coordinated subprojects under one product root.")
        if "backend" in {surface["platform"] for surface in surfaces}:
            notes.append("Document shared auth, storage, and API contracts before major implementation.")
        if primary == "mobile" and _has_any(text, _GAME_KEYWORDS):
            notes.append("Pick the game loop, rendering stack, and asset pipeline before content production.")
        return notes

    @classmethod
    def _product_brief(
        cls,
        *,
        project_name: str,
        text: str,
        primary: str,
        surfaces: list[dict[str, Any]],
        shared_capabilities: list[str],
    ) -> dict[str, Any]:
        display_name = _display_name(project_name)
        surface_names = [surface["platform"] for surface in surfaces]
        return {
            "name": display_name,
            "elevator_pitch": cls._elevator_pitch(display_name, primary, surface_names),
            "target_users": cls._target_users(text, primary),
            "core_user_problem": cls._core_user_problem(text, primary),
            "core_features": cls._core_features(text, primary, shared_capabilities),
            "primary_user_journey": cls._primary_user_journey(primary, shared_capabilities),
            "ui_direction": cls._ui_direction(text, primary),
            "backend": cls._backend_brief(shared_capabilities, primary),
            "success_metrics": cls._success_metrics(primary, shared_capabilities),
            "quality_bar": cls._quality_bar(primary),
            "delivery_surfaces": surface_names,
            "assumptions": cls._assumptions(text, primary, shared_capabilities),
        }

    @staticmethod
    def _elevator_pitch(display_name: str, primary: str, surface_names: list[str]) -> str:
        if primary == "unknown":
            return f"{display_name} needs one clarified launch platform before a safe build plan can be finalized."
        if len(surface_names) > 1:
            joined = ", ".join(surface_names)
            return f"{display_name} is a coordinated {primary}-led product suite spanning {joined}."
        return f"{display_name} is a production-grade {primary} product with a publishable first release."

    @staticmethod
    def _target_users(text: str, primary: str) -> list[str]:
        if _has_any(text, ("developer", "coding", "engineer", "programmer", "cursor", "editor", "ide")):
            return ["professional developers", "technical teams"]
        if _has_any(text, _GAME_KEYWORDS):
            return ["mobile gamers", "competitive players"]
        if _has_any(text, ("team", "workspace", "admin", "dashboard", "billing", "crm", "portal")):
            return ["operations teams", "account owners", "workspace administrators"]
        return [
            f"{primary} users" if primary != "unknown" else "end users",
            "operators who need a production-ready product rather than a prototype",
        ]

    @staticmethod
    def _core_user_problem(text: str, primary: str) -> str:
        if _has_any(text, ("cursor", "coding", "developer", "editor", "ide")):
            return "Users need a reliable productivity workflow that feels native, fast, and ready for daily work."
        if _has_any(text, _GAME_KEYWORDS):
            return "Players need polished gameplay, responsive controls, and a progression loop worth publishing."
        if _has_any(text, ("billing", "subscription", "account", "admin", "portal")):
            return "Customers need a clear way to sign in, manage accounts, and complete the core workflow without operator help."
        return (
            f"Users need a complete {primary} product that solves the requested job without falling back to a toy demo."
            if primary != "unknown"
            else "Users need the requested product delivered as a complete, coherent application."
        )

    @staticmethod
    def _core_features(text: str, primary: str, shared_capabilities: list[str]) -> list[str]:
        features: list[str] = []
        if primary == "desktop":
            features.extend(["native desktop shell", "local project/workspace UX", "publishable installer flow"])
        elif primary == "mobile":
            features.extend(["native mobile runtime", "touch-first controls", "store-ready onboarding and settings"])
        elif primary == "web":
            features.extend(["responsive app shell", "browser dashboard", "deployment-ready frontend architecture"])
        elif primary == "extension":
            features.extend(["browser extension runtime", "settings/dashboard surface"])
        elif primary == "bot":
            features.extend(["conversational automation flow", "background job handling"])
        elif primary == "backend":
            features.extend(["documented API service", "operational health and persistence"])
        elif primary == "cli":
            features.extend(["task-focused command interface", "helpful terminal UX"])
        if "auth" in shared_capabilities:
            features.append("authentication and session management")
        if "account-management" in shared_capabilities:
            features.append("account and workspace management")
        if "billing" in shared_capabilities:
            features.append("billing and subscription controls")
        if "sync-and-realtime" in shared_capabilities:
            features.append("sync, realtime, or leaderboard-ready backend flows")
        if _has_any(text, _GAME_KEYWORDS):
            features.extend(["game loop polish", "progression and scoring", "performance tuning for publishable gameplay"])
        return _unique_preserve_order(features)

    @staticmethod
    def _primary_user_journey(primary: str, shared_capabilities: list[str]) -> list[str]:
        journey = ["land in the product", "complete onboarding/setup", "use the primary core workflow"]
        if "auth" in shared_capabilities:
            journey.insert(1, "create an account or sign in")
        if "billing" in shared_capabilities:
            journey.append("manage plan or billing settings")
        if primary in {"desktop", "mobile"}:
            journey.insert(0, "discover the product and install or download it")
        return journey

    @staticmethod
    def _ui_direction(text: str, primary: str) -> dict[str, Any]:
        if _has_any(text, _GAME_KEYWORDS):
            return {
                "style_keywords": ["high-contrast", "energetic", "motion-forward", "arcade polish"],
                "color_theme": {
                    "primary": "#ef4444",
                    "accent": "#f59e0b",
                    "background": "#0f172a",
                    "surface": "#111827",
                },
                "layout_guidance": "Prioritize immersive visuals, readable HUD overlays, and touch-friendly controls.",
            }
        if primary in {"desktop", "cli"} or _has_any(text, ("cursor", "coding", "developer", "editor", "ide")):
            return {
                "style_keywords": ["focused", "professional", "high-information-density", "calm premium"],
                "color_theme": {
                    "primary": "#14b8a6",
                    "accent": "#84cc16",
                    "background": "#0f172a",
                    "surface": "#111827",
                },
                "layout_guidance": "Use a calm dark theme by default, strong hierarchy, and minimal distractions around the core workflow.",
            }
        return {
            "style_keywords": ["clean", "trustworthy", "modern", "production-ready"],
            "color_theme": {
                "primary": "#0f766e",
                "accent": "#65a30d",
                "background": "#f8fafc",
                "surface": "#ffffff",
            },
            "layout_guidance": "Keep navigation obvious, forms simple, and the primary action visible on every core screen.",
        }

    @staticmethod
    def _backend_brief(shared_capabilities: list[str], primary: str) -> dict[str, Any]:
        needs_backend = "api-contract" in shared_capabilities or primary == "backend"
        return {
            "required": needs_backend,
            "auth_strategy": (
                "Email/password plus session or token auth with account settings."
                if "auth" in shared_capabilities
                else "Anonymous or local-first mode is acceptable for the first slice."
            ),
            "core_services": _unique_preserve_order(
                [
                    "health and readiness endpoints" if needs_backend else "",
                    "application API" if needs_backend else "",
                    "account and workspace service" if "account-management" in shared_capabilities else "",
                    "billing integration surface" if "billing" in shared_capabilities else "",
                    "background jobs or async workers" if "background-jobs" in shared_capabilities else "",
                ]
            ),
            "data_entities": _unique_preserve_order(
                [
                    "user" if "auth" in shared_capabilities else "",
                    "workspace" if "team-workspaces" in shared_capabilities else "",
                    "subscription" if "billing" in shared_capabilities else "",
                    "app content and domain records" if needs_backend else "local domain models only",
                ]
            ),
        }

    @staticmethod
    def _success_metrics(primary: str, shared_capabilities: list[str]) -> list[str]:
        metrics = [
            f"The {primary} runtime builds and launches cleanly." if primary != "unknown" else "The chosen runtime builds and launches cleanly.",
            "A new user can complete the primary flow end-to-end without manual intervention.",
            "Verification covers the core runtime plus the main account or admin flows.",
        ]
        if "billing" in shared_capabilities:
            metrics.append("Plan and billing states are testable in local and staging environments.")
        return metrics

    @staticmethod
    def _quality_bar(primary: str) -> list[str]:
        quality = [
            "Production-shaped project structure, not a one-file prototype.",
            "Local bootstrap, dev, and verification commands are documented and runnable.",
            "UX, data flow, and deployment assumptions are captured before major implementation.",
        ]
        if primary in {"mobile", "desktop"}:
            quality.append("Keep the native surface as the primary shipped experience, not a browser fallback.")
        return quality

    @staticmethod
    def _assumptions(text: str, primary: str, shared_capabilities: list[str]) -> list[str]:
        assumptions = [
            f"Launch the first release on {primary}." if primary != "unknown" else "Clarify the first launch platform before scaffolding.",
            "Default to a maintainable stack with strong local-development ergonomics.",
        ]
        if "auth" in shared_capabilities:
            assumptions.append("Account/auth flows are part of v1 unless the user explicitly requests a local-only first release.")
        if _has_any(text, _GAME_KEYWORDS):
            assumptions.append("Gameplay feel and performance tuning matter as much as raw feature count.")
        return assumptions

    @staticmethod
    def _research_tracks(primary: str, surfaces: list[dict[str, Any]], shared_capabilities: list[str]) -> list[dict[str, Any]]:
        surface_names = [surface["platform"] for surface in surfaces]
        tracks = [
            {
                "track": "product-shape",
                "goal": "Confirm user expectations, launch scope, and quality bar for the requested product.",
            },
            {
                "track": "ui-system",
                "goal": "Define screens, navigation, states, and a visual system including color theme and interaction patterns.",
            },
            {
                "track": "runtime-stack",
                "goal": f"Validate the recommended stack and packaging approach for {primary}.",
            },
        ]
        if "backend" in surface_names:
            tracks.append(
                {
                    "track": "backend-architecture",
                    "goal": "Choose APIs, persistence, auth/session model, and background-job boundaries.",
                }
            )
        if "billing" in shared_capabilities:
            tracks.append(
                {
                    "track": "billing-and-accounts",
                    "goal": "Map subscription states, entitlement checks, and account-management UX.",
                }
            )
        return tracks

    @staticmethod
    def _implementation_phases(primary: str, surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        phase_one_deliverables = [
            "Expanded product brief",
            "Research findings",
            "Architecture and UX decisions",
            "Approved implementation plan and tasks",
        ]
        phases = [
            {
                "phase": "Phase 1",
                "name": "Product Definition",
                "goal": "Turn the rough idea into a concrete brief, research packet, and plan.",
                "deliverables": phase_one_deliverables,
            },
            {
                "phase": "Phase 2",
                "name": "Foundation Build",
                "goal": "Scaffold the project structure, core runtime, and shared infrastructure.",
                "deliverables": [f"{primary} runtime scaffold" if primary != "unknown" else "runtime scaffold", "CI/dev scripts", "core data and auth foundations"],
            },
            {
                "phase": "Phase 3",
                "name": "Feature Delivery",
                "goal": "Implement the core user journey across every required surface.",
                "deliverables": [f"{surface['platform']} feature slice" for surface in surfaces] or ["primary feature slice"],
            },
            {
                "phase": "Phase 4",
                "name": "Verification and Release",
                "goal": "Prove the product builds, runs, and is ready for publishable handoff.",
                "deliverables": ["verification evidence", "release checklist", "known-issues log"],
            },
        ]
        return phases

    @staticmethod
    def _initial_tasks(primary: str, surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        surface_names = [surface["platform"] for surface in surfaces]
        tasks = [
            {
                "id": "1.1",
                "phase": "Phase 1",
                "title": "Expand the rough idea into a detailed product brief",
                "owner": "architect",
                "depends_on": [],
                "subtasks": [
                    "Lock the primary user problem and success criteria.",
                    "Define required surfaces, auth/account scope, and delivery assumptions.",
                    "Choose an initial UI direction including color theme and navigation shape.",
                ],
            },
            {
                "id": "1.2",
                "phase": "Phase 1",
                "title": "Research the stack, references, and architecture choices",
                "owner": "architect",
                "depends_on": ["1.1"],
                "subtasks": [
                    "Validate the runtime stack and project structure.",
                    "Research comparable products and extract must-have patterns.",
                    "Update the plan with confirmed libraries, risks, and open questions.",
                ],
            },
            {
                "id": "1.3",
                "phase": "Phase 1",
                "title": "Write the executable implementation plan and task board",
                "owner": "ceo",
                "depends_on": ["1.2"],
                "subtasks": [
                    "Break the work into phases, owners, and acceptance criteria.",
                    "Publish the initial task board before major coding begins.",
                ],
            },
            {
                "id": "2.1",
                "phase": "Phase 2",
                "title": f"Scaffold the {primary if primary != 'unknown' else 'primary'} runtime and core project structure",
                "owner": "frontend_engineer" if primary in {"web", "mobile", "desktop", "extension"} else "backend_engineer",
                "depends_on": ["1.3"],
                "subtasks": [
                    "Create the project scaffold and local runtime scripts.",
                    "Wire shared configuration, environment files, and verification hooks.",
                ],
            },
        ]
        if "backend" in surface_names:
            tasks.append(
                {
                    "id": "2.2",
                    "phase": "Phase 2",
                    "title": "Implement shared backend, auth, and persistence foundations",
                    "owner": "backend_engineer",
                    "depends_on": ["2.1"],
                    "subtasks": [
                        "Create API boundaries and data models.",
                        "Add auth, account, and operational health endpoints.",
                    ],
                }
            )
        if any(surface in surface_names for surface in {"web", "desktop", "mobile", "extension"}):
            tasks.append(
                {
                    "id": "3.1",
                    "phase": "Phase 3",
                    "title": "Build the core user-facing workflow and polish the UI",
                    "owner": "frontend_engineer",
                    "depends_on": ["2.1"] + (["2.2"] if "backend" in surface_names else []),
                    "subtasks": [
                        "Implement the main screens, states, and interactions.",
                        "Apply the design system, color theme, and empty/loading/error states.",
                    ],
                }
            )
        tasks.append(
            {
                "id": "4.1",
                "phase": "Phase 4",
                "title": "Run verification and prepare the release handoff",
                "owner": "qa_engineer",
                "depends_on": [tasks[-1]["id"]],
                "subtasks": [
                    "Run build and verification flows for each required surface.",
                    "Document proof, blockers, and release-readiness notes.",
                ],
            }
        )
        return tasks
