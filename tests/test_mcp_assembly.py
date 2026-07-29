"""Tests for the MCP assembly tools and the inline visual-review path.

These drive `cadclaw_mcp.server.handle_request` directly (rather than spawning
a subprocess) so the image content blocks can be inspected byte-for-byte.
"""
import base64
import json
import tempfile
import unittest
from pathlib import Path

import cadclaw_mcp.server as server


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "L1_good.step"

SPEC_TEMPLATE = """
schema_version: assembly_spec.v0.1
meta:
  project: McpTest
  assembly_id: mcp_round
component_roots:
  - {root}
outputs:
  step: {root}/build/out.step
  views_dir: {root}/build/views
review_views:
  - name: iso_overview
    view: iso
    width: 320
    height: 240
  - name: front_check
    view: front
    width: 320
    height: 240
instances:
  - id: part_a
    role: fixture
    source_path: CAD/part.step
"""


def _call(name, args):
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    return response["result"]


def _payload(result):
    return json.loads(result["content"][0]["text"])


def _images(result):
    return [c for c in result["content"] if c["type"] == "image"]


class TestMcpAssemblyTools(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        cad = root / "CAD"
        cad.mkdir(parents=True)
        (cad / "part.step").write_bytes(FIXTURE.read_bytes())
        self.root = root
        self.spec = root / "spec.yaml"
        self.spec.write_text(
            SPEC_TEMPLATE.format(root=root.as_posix()), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    # --- registration ---------------------------------------------

    def test_assembly_tools_are_advertised(self):
        names = {t["name"] for t in server.TOOLS}
        for tool in [
            "assemble_validate_spec", "assemble_build", "assemble_check_round",
            "assemble_inspect_component", "assemble_render_views",
            "assemble_render_sequence",
        ]:
            self.assertIn(tool, names)
            self.assertIn(tool, server.TOOL_HANDLERS)

    def test_every_assembly_schema_requires_spec(self):
        for tool in server.TOOLS:
            if tool["name"].startswith("assemble_"):
                self.assertEqual(tool["inputSchema"]["required"], ["spec"])

    # --- validate / build ------------------------------------------

    def test_validate_spec_reports_pass_and_instance_count(self):
        payload = _payload(_call("assemble_validate_spec", {"spec": str(self.spec)}))
        self.assertEqual(payload["overall"], "pass")
        self.assertEqual(payload["meta"]["instances"], 1)

    def test_validate_spec_matches_the_library_function(self):
        """The MCP tool must not drift from `validate_assembly_spec`."""
        from cadclaw.assembly_compiler import validate_assembly_spec
        direct = validate_assembly_spec(str(self.spec)).to_dict()
        via_mcp = _payload(_call("assemble_validate_spec", {"spec": str(self.spec)}))
        self.assertEqual(direct["overall"], via_mcp["overall"])
        self.assertEqual(direct["meta"]["instances"], via_mcp["meta"]["instances"])

    def test_build_dry_run_does_not_write_a_step(self):
        payload = _payload(_call("assemble_build", {
            "spec": str(self.spec), "dry_run": True,
        }))
        self.assertIn(payload["overall"], {"pass", "warn"})
        self.assertFalse((self.root / "build" / "out.step").exists())

    def test_build_writes_the_step(self):
        _call("assemble_build", {"spec": str(self.spec)})
        self.assertTrue((self.root / "build" / "out.step").exists())

    # --- the visual-review step ------------------------------------

    def test_render_views_returns_decodable_png_images(self):
        result = _call("assemble_render_views", {"spec": str(self.spec)})
        # build first so there is a STEP to render
        if not _images(result):
            _call("assemble_build", {"spec": str(self.spec)})
            result = _call("assemble_render_views", {"spec": str(self.spec)})

        images = _images(result)
        self.assertEqual(len(images), 2)
        for image in images:
            self.assertEqual(image["mimeType"], "image/png")
            raw = base64.b64decode(image["data"])
            self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")

    def test_render_views_reports_the_rendered_count(self):
        _call("assemble_build", {"spec": str(self.spec)})
        payload = _payload(_call("assemble_render_views", {"spec": str(self.spec)}))
        self.assertEqual(payload["rendered_view_count"], 2)

    def test_return_images_false_suppresses_image_blocks(self):
        _call("assemble_build", {"spec": str(self.spec)})
        result = _call("assemble_render_views", {
            "spec": str(self.spec), "return_images": False,
        })
        self.assertEqual(_images(result), [])
        # the PNGs are still written to disk as the traceability artifact
        self.assertEqual(_payload(result)["rendered_view_count"], 2)

    def test_renders_are_written_to_disk_as_artifacts(self):
        _call("assemble_build", {"spec": str(self.spec)})
        _call("assemble_render_views", {"spec": str(self.spec)})
        pngs = list((self.root / "build" / "views").glob("*.png"))
        self.assertEqual(len(pngs), 2)

    def test_check_round_returns_images(self):
        result = _call("assemble_check_round", {"spec": str(self.spec)})
        self.assertEqual(len(_images(result)), 2)

    def test_inspect_component_renders_when_asked(self):
        result = _call("assemble_inspect_component", {
            "spec": str(self.spec), "source_path": "CAD/part.step",
            "render_views": True, "views": "front,iso",
        })
        self.assertEqual(len(_images(result)), 2)
        self.assertEqual(_payload(result)["meta"]["part_count"], 5)

    def test_inspect_component_without_renders_returns_no_images(self):
        result = _call("assemble_inspect_component", {
            "spec": str(self.spec), "source_path": "CAD/part.step",
        })
        self.assertEqual(_images(result), [])

    def test_inline_image_budget_is_enforced(self):
        paths = [str(self.root / f"v{i}.png") for i in range(server.MAX_INLINE_IMAGES + 3)]
        result = server._attach_images({
            "meta": {"review_views": [
                {"rendered": True, "output_path": p} for p in paths
            ]},
        }, return_images=True)
        self.assertEqual(len(result[server._IMAGES_KEY]), server.MAX_INLINE_IMAGES)
        self.assertEqual(result["inline_images_truncated"]["total"], len(paths))

    def test_unrendered_views_are_not_returned_as_images(self):
        result = server._attach_images({
            "meta": {"review_views": [
                {"rendered": False, "output_path": "missing.png"},
            ]},
        }, return_images=True)
        self.assertEqual(result["rendered_view_count"], 0)
        self.assertNotIn(server._IMAGES_KEY, result)

    def test_unreadable_image_degrades_to_text_not_a_crash(self):
        blocks = server._image_content_blocks([str(self.root / "does_not_exist.png")])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "text")

    def test_image_marker_never_leaks_into_the_json_payload(self):
        result = _call("assemble_check_round", {"spec": str(self.spec)})
        self.assertNotIn(server._IMAGES_KEY, _payload(result))

    # --- error handling --------------------------------------------

    def test_missing_spec_is_reported_as_an_error(self):
        result = _call("assemble_validate_spec", {
            "spec": str(self.root / "nope.yaml"),
        })
        self.assertTrue(result.get("isError"))

    def test_inspect_component_requires_a_selector(self):
        payload = _payload(_call("assemble_inspect_component", {"spec": str(self.spec)}))
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
