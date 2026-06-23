from pathlib import Path

from teai_builder.integrations.plugin_system import PluginSystem


def test_plugin_system_discovers_manifest_based_extensions(tmp_path: Path):
    plugin_dir = tmp_path / "sample-extension"
    plugin_dir.mkdir()
    (plugin_dir / "teai-extension.toml").write_text(
        """
[extension]
id = "sample-extension"
name = "Sample Extension"
version = "1.2.3"
entrypoint = "main.py"
description = "Sample"
capabilities = ["tools", "channels"]
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )

    system = PluginSystem(tmp_path)
    manifests = system.discover()

    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest.plugin_id == "sample-extension"
    assert manifest.name == "Sample Extension"
    assert manifest.version == "1.2.3"
    assert manifest.entrypoint == "main.py"
    assert manifest.capabilities == ["tools", "channels"]
    assert manifest.legacy is False


def test_plugin_system_loads_manifest_based_extension(tmp_path: Path):
    plugin_dir = tmp_path / "sample-extension"
    plugin_dir.mkdir()
    (plugin_dir / "teai-extension.toml").write_text(
        """
[extension]
id = "sample-extension"
version = "0.1.0"
entrypoint = "plugin"
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        "VALUE = 7\n",
        encoding="utf-8",
    )

    system = PluginSystem(tmp_path)
    manifest = system.discover()[0]
    loaded = system.load_plugin(manifest)

    assert loaded.module is not None
    assert loaded.module.VALUE == 7


def test_plugin_system_keeps_legacy_single_file_plugins(tmp_path: Path):
    (tmp_path / "legacy_demo.py").write_text(
        "\n".join(
            [
                'PLUGIN_ID = "legacy-demo"',
                'NAME = "Legacy Demo"',
                'VERSION = "0.0.1"',
                'ENTRYPOINT = "legacy_demo"',
            ]
        ),
        encoding="utf-8",
    )

    system = PluginSystem(tmp_path)
    manifests = system.discover()

    assert len(manifests) == 1
    assert manifests[0].plugin_id == "legacy-demo"
    assert manifests[0].legacy is True
