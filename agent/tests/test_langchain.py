import tempfile
import unittest
from pathlib import Path

from clipagent import langchain_agent
from clipagent.tools import ToolContext, build_tools


class ParityTests(unittest.TestCase):
    def test_native_registry_is_the_reference(self):
        tools = build_tools()
        self.assertEqual(len(tools), 5)
        self.assertEqual(len({t.name for t in tools}), 5)

    @unittest.skipUnless(langchain_agent.available(), 'langchain not installed')
    def test_framework_exposes_the_same_tool_names(self):
        ctx = ToolContext(Path(tempfile.mkdtemp()))
        built = langchain_agent.build_langchain_tools(ctx)
        self.assertEqual(sorted(t.name for t in built),
                         sorted(t.name for t in build_tools()))

    @unittest.skipUnless(langchain_agent.available(), 'langchain not installed')
    def test_parameter_surfaces_match(self):
        report = langchain_agent.parity_report()
        self.assertEqual(report.only_native, [])
        self.assertEqual(report.only_framework, [])
        self.assertEqual(report.schema_mismatch, [])

    def test_parity_report_is_explicit_when_framework_is_absent(self):
        if langchain_agent.available():
            self.skipTest('langchain installed; absence path not exercised')
        report = langchain_agent.parity_report()
        self.assertFalse(report.ok)
        self.assertEqual(report.only_native, sorted(t.name for t in build_tools()))


if __name__ == '__main__':
    unittest.main()
