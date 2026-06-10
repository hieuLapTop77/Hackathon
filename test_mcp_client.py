"""
test_mcp_client.py
===================
Test client to connect to the SQL Server MCP Server and verify its tools.
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run_test():
    # Define parameters to launch the Python MCP server
    # We run it via the python interpreter pointing to the script path
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["backend/src/db/mcp_sqlserver.py"],
        env=os.environ.copy()
    )
    
    print("=" * 60)
    print("CONNECTING TO MCP SERVER VIA STDIO TRANSPORT...")
    print("=" * 60)
    
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # 1. Initialize the session
                await session.initialize()
                print("[OK] MCP Session initialized successfully!")
                
                # 2. List tools exposed by the server
                print("\nListing available tools:")
                tools_response = await session.list_tools()
                for idx, tool in enumerate(tools_response.tools, 1):
                    print(f"  {idx}. Tool Name: {tool.name}")
                    print(f"     Description: {tool.description}")
                    print(f"     Schema: {tool.inputSchema}")
                    print("-" * 40)
                
                # 3. Call tool: get_flight_by_search_term (search flight VJ100)
                print("\nCalling tool 'get_flight_by_search_term' for 'VJ100':")
                result = await session.call_tool(
                    "get_flight_by_search_term", 
                    arguments={"search_term": "VJ100"}
                )
                print("[Result]:")
                for item in result.content:
                    # Content is usually a TextContent object
                    print(getattr(item, 'text', str(item)))
                
                # 4. Call tool: get_airports_list
                print("\nCalling tool 'get_airports_list':")
                result_airports = await session.call_tool("get_airports_list")
                print("[Result]:")
                for item in result_airports.content:
                    print(getattr(item, 'text', str(item)))
                
                # 5. Call tool: update_flight_pricing (update dummy flight ID 9999)
                print("\nCalling tool 'update_flight_pricing' for ID 9999:")
                result_update = await session.call_tool(
                    "update_flight_pricing", 
                    arguments={"flight_id": 9999, "new_price": 1500000.0, "new_lf": 0.68}
                )
                print("[Result]:")
                for item in result_update.content:
                    print(getattr(item, 'text', str(item)))

    except Exception as e:
        print(f"\n[ERROR] Failed to run MCP Client Test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Configure stdout encoding to utf-8 to prevent UnicodeEncodeErrors on Windows terminals
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    # Ensure correct event loop policy on Windows to prevent loop errors
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(run_test())
