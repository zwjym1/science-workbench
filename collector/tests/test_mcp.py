"""Real local stdio protocol; never starts browser or platform requests."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPTests(unittest.TestCase):
    def test_protocol_submit_query(self):
        async def scenario(folder):
            env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]),'COLLECTOR_DATA_DIR':folder,'COLLECTOR_DATABASE_URL':'sqlite:///'+str(Path(folder)/'mcp.sqlite')}
            params=StdioServerParameters(command=sys.executable,args=['-m','dycollector.mcp_server'],env=env)
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    listing=await session.list_tools()
                    self.assertEqual({t.name for t in listing.tools},{'submit_collection','get_job','get_result','list_jobs','resume_job','submit_search'})
                    submitted=await session.call_tool('submit_collection',{'video_url':'7667409251216819441'})
                    self.assertFalse(submitted.is_error)
                    listing=await session.call_tool('list_jobs',{})
                    self.assertFalse(listing.is_error)
                    bad=await session.call_tool('submit_collection',{'video_url':'http://127.0.0.1/'})
                    self.assertTrue(bad.is_error)
        with tempfile.TemporaryDirectory() as folder: asyncio.run(scenario(folder))
