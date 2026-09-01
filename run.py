"""
PromiseProof - Master Execution Entrypoint
Starts both the FastMCP Server and the FastAPI Web Studio, and refuses to boot
a broken configuration silently (missing API key, MCP server that never comes up).
"""

import os
import subprocess  # nosec B404 - only ever launches our own mcp_server/server.py, no shell, no user input
import sys
import threading
import time

import httpx
import uvicorn
from dotenv import load_dotenv

# See mcp_server/server.py for why this is needed: Windows consoles/pipes
# default to cp1252 and crash on this file's emoji unless forced to UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

MCP_READY_TIMEOUT_SECONDS = 15


def warn_on_missing_config():
    """The scorecard, the MCP tools and the verification cycle all work with no
    key. Only the live extraction demo (/api/extract-stream) needs one - warn,
    don't refuse to boot."""
    if not os.getenv("NEBIUS_API_KEY"):
        print("\n⚠  NEBIUS_API_KEY is not set - the scorecard and MCP tools still work,")
        print("   but the live 'extract a promise' demo will return an error until you set it")
        print("   (copy .env.example to .env, key from https://studio.nebius.com/).\n")


def start_mcp_server():
    """Runs the FastMCP server in a background thread."""
    server_path = os.path.join(os.path.dirname(__file__), "mcp_server", "server.py")
    # Long-running daemon thread wrapping the MCP server process for the
    # lifetime of the app - its exit code is not meaningful to check here.
    # Fixed argv (this interpreter + our own script path), no shell, no
    # untrusted input.
    subprocess.run([sys.executable, server_path], check=False)  # nosec B603


def wait_for_mcp_server(mcp_url: str, timeout_seconds: int = MCP_READY_TIMEOUT_SECONDS) -> bool:
    """Poll the MCP server until it accepts connections instead of guessing with a fixed sleep."""
    base_url = mcp_url.rsplit("/mcp", 1)[0]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            httpx.get(base_url, timeout=1.0)
            return True
        except httpx.TransportError:
            time.sleep(0.3)
        except Exception:  # noqa: BLE001 - any HTTP response (even 404/406 on a bare GET) means the server is up, regardless of exact exception type
            return True
    return False


def main():
    print("""
    ==================================================================
      PROMISEPROOF - MACHINE-VERIFIABLE ACCOUNTABILITY FOR
      PUBLIC PRODUCT PROMISES
      Nebius x NVIDIA Global AI Hackathon Submission
    ==================================================================
    """)

    warn_on_missing_config()

    # 8080 matches mcp_server/server.py's own MCP_SERVER_PORT default for local
    # dev. Docker/Cloud Run always sets MCP_SERVER_URL explicitly to 8081 (see
    # Dockerfile) to avoid colliding with the web app on the single exposed
    # port, so this fallback is only ever reached in local runs.
    mcp_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8080/mcp")

    # 1. Start FastMCP Server in background thread
    print(f"[1/2] Launching FastMCP Server on {mcp_url} ...")
    mcp_thread = threading.Thread(target=start_mcp_server, daemon=True)
    mcp_thread.start()

    if wait_for_mcp_server(mcp_url):
        print("   FastMCP Server is up.")
    else:
        print(f"   WARNING: FastMCP Server did not respond within {MCP_READY_TIMEOUT_SECONDS}s.")
        print("      MCP ledger tools will be unreachable until it comes up.")

    # 2. Start Web Studio Backend
    # Cloud Run always injects PORT and expects the container to bind to it -
    # ignoring it and trusting only WEB_APP_PORT works today only because the
    # Dockerfile happens to set both to 8080. A deploy with a different
    # --port would silently keep listening on the wrong port and fail health
    # checks. PORT wins when present; WEB_APP_PORT/8000 covers local dev.
    web_port = int(os.getenv("PORT") or os.getenv("WEB_APP_PORT", "8000"))
    print(f"[2/2] Launching Interactive Web Studio on http://127.0.0.1:{web_port} ...\n")
    print(f"Open your browser at: http://127.0.0.1:{web_port}\n")

    uvicorn.run(
        "web_app.app:app",
        host="0.0.0.0",  # nosec B104 - Cloud Run's health check probes from outside the container and needs this; 127.0.0.1 only accepts loopback connections
        port=web_port,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()
