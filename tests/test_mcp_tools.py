"""MCP tool registration contract for the 0.11.0 release cut.

These assertions do not need STEP fixtures or OCCT — they only inspect the
static TOOLS / TOOL_HANDLERS tables. PyPI 0.10.0 shipped 23 tools; 0.11.0 must
advertise run_harness and reach 24.
"""
import unittest

import cadclaw_mcp.server as server


class TestMcpToolRegistration(unittest.TestCase):
    def test_run_harness_is_advertised_and_tool_count_is_24(self):
        names = {tool["name"] for tool in server.TOOLS}
        self.assertIn("run_harness", names)
        self.assertIn("run_harness", server.TOOL_HANDLERS)
        self.assertEqual(len(server.TOOLS), 24)
        self.assertEqual(len(server.TOOL_HANDLERS), 24)
        self.assertEqual(names, set(server.TOOL_HANDLERS))


if __name__ == "__main__":
    unittest.main()
