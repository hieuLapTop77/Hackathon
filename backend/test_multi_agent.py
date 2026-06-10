import asyncio
import os
import sys

# Add the app directory inside the Docker container to the python path
sys.path.append("/app")

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path="/app/backend/.env") # fallback if env isn't fully loaded in shell

from backend.src.api.agent_graph import run_copilot_graph

async def test_queries():
    # Clear semantic cache to avoid getting stale offline fallback results
    try:
        from backend.src.api.semantic_cache import get_cache
        get_cache().invalidate_all()
        print("Semantic cache cleared successfully for testing.")
    except Exception as e:
        print(f"Could not clear semantic cache: {e}")

    # Langfuse SDK diagnostic
    try:
        import langfuse
        print(f"Langfuse SDK version: {getattr(langfuse, '__version__', 'unknown')}")
        from langfuse import Langfuse
        lf = Langfuse(
            host=os.getenv("LANGFUSE_HOST", "http://localhost:4000"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-default"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-default"),
        )
        print(f"Langfuse client initialized with host: {os.getenv('LANGFUSE_HOST', 'http://localhost:4000')}")
        if hasattr(lf, "trace"):
            t = lf.trace(name="test_trace_creation")
            print(f"Test trace created successfully: {t.id}")
        elif hasattr(lf, "start_observation"):
            t = lf.start_observation(name="test_trace_creation", as_type="span")
            print("Test trace created successfully via start_observation.")
            if hasattr(t, "end"):
                t.end()
    except Exception as e:
        print("Langfuse diagnostic failed:")
        import traceback
        traceback.print_exc()

    # Reconfigure stdout to support utf-8 print on Windows/Unix terminals
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    test_cases = [
        "dự đoán giá vé của Vietjet ngày hôm nay",
        "so sánh giá vé Vietjet hôm nay với các hãng khác đường bay SGN đến HAN",
        "dự đoán giá vé Vietjet hôm nay và điều chỉnh giá vé phù hợp so với đối thủ cạnh tranh"
    ]

    for query in test_cases:
        print("\n" + "="*80)
        print(f"TESTING QUERY: {query}")
        print("="*80)
        try:
            result = await run_copilot_graph(query)
            print("\n>>> THINKING:")
            print(result.get("thinking"))
            print("\n>>> MESSAGE:")
            print(result.get("message"))
            print("\n>>> TOOLS CALLED:")
            for tool in result.get("tools_called", []):
                print(f"  - {tool['name']}({tool.get('args', '')}) -> {tool.get('result', '')}")
            print("\n>>> ACTION:")
            print(result.get("action"))
        except Exception as e:
            print(f"An error occurred: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(test_queries())
