"""Plugin and extension system for TeAI Builder."""

from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from teai_builder.config.paths import get_runtime_subdir


@dataclass
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    entrypoint: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    root_dir: Path | None = None
    manifest_path: Path | None = None
    legacy: bool = False


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    module: Any | None = None
    enabled: bool = True


class PluginSystem:
    MANIFEST_NAME = "teai-extension.toml"

    def __init__(self, plugins_dir: Path | None = None) -> None:
        if plugins_dir is None:
            plugins_dir = get_runtime_subdir("plugins")
        self.plugins_dir = plugins_dir
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.loaded: dict[str, LoadedPlugin] = {}

    def discover(self) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        manifest_dirs: set[Path] = set()
        for path in sorted(self.plugins_dir.iterdir()):
            if not path.is_dir():
                continue
            manifest_path = path / self.MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            manifest = self._load_extension_manifest(manifest_path)
            if manifest:
                manifests.append(manifest)
                manifest_dirs.add(path.resolve())
        for path in self.plugins_dir.glob("*.py"):
            if path.resolve().parent in manifest_dirs:
                continue
            manifest = self._load_manifest(path)
            if manifest:
                manifests.append(manifest)
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> LoadedPlugin:
        module_path = self._module_path_for_manifest(manifest)
        spec = importlib.util.spec_from_file_location(manifest.plugin_id, module_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Could not load plugin entrypoint: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded = LoadedPlugin(manifest=manifest, module=module)
        self.loaded[manifest.plugin_id] = loaded
        return loaded

    def _module_path_for_manifest(self, manifest: PluginManifest) -> Path:
        if manifest.root_dir is not None:
            module_path = manifest.root_dir / manifest.entrypoint
        else:
            module_path = self.plugins_dir / manifest.entrypoint
        if module_path.suffix != ".py":
            module_path = module_path.with_suffix(".py")
        return module_path

    def _load_extension_manifest(self, path: Path) -> PluginManifest | None:
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            extension = raw.get("extension")
            if not isinstance(extension, dict):
                return None
            plugin_id = str(extension["id"]).strip()
            name = str(extension.get("name") or plugin_id).strip()
            version = str(extension["version"]).strip()
            entrypoint = str(extension["entrypoint"]).strip()
            description = str(extension.get("description") or "").strip()
            capabilities = extension.get("capabilities") or []
            if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
                return None
            manifest = PluginManifest(
                plugin_id=plugin_id,
                name=name,
                version=version,
                entrypoint=entrypoint,
                description=description,
                capabilities=list(capabilities),
                metadata={
                    key: value
                    for key, value in raw.items()
                    if key != "extension"
                },
                root_dir=path.parent,
                manifest_path=path,
            )
            module_path = self._module_path_for_manifest(manifest)
            if not module_path.is_file():
                return None
            return manifest
        except Exception:
            return None

    def _load_manifest(self, path: Path) -> PluginManifest | None:
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            if module is None:
                return None
            spec.loader.exec_module(module)
            return PluginManifest(
                plugin_id=getattr(module, "PLUGIN_ID", path.stem),
                name=getattr(module, "NAME", path.stem),
                version=getattr(module, "VERSION", "0.0.0"),
                entrypoint=getattr(module, "ENTRYPOINT", path.stem),
                description=getattr(module, "DESCRIPTION", ""),
                capabilities=getattr(module, "CAPABILITIES", []),
                root_dir=path.parent,
                manifest_path=path,
                legacy=True,
            )
        except Exception:
            return None
