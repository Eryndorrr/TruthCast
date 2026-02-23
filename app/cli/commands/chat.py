"""Chat command - Interactive conversation mode."""

import json
import signal
import sys
from typing import Any, Dict, Generator, Optional

import typer

from app.cli.client import APIClient, APIError
from app.cli.lib.state_manager import get_state_value, update_state



def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single SSE line.
    
    Args:
        line: Raw SSE line (e.g., "data: {...}")
    
    Returns:
        Parsed event dict or None if not a data line
    """
    if not line.strip():
        return None
    
    if not line.startswith("data:"):
        return None
    
    # Strip "data: " prefix
    json_str = line[5:].strip()
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None


def stream_chat_message(
    client: APIClient, session_id: str, user_input: str
) -> Generator[Dict[str, Any], None, None]:
    """
    Stream chat message to backend and yield SSE events.
    
    Args:
        client: API client instance
        session_id: Chat session ID
        user_input: User message text
    
    Yields:
        Parsed SSE event dicts
    """
    path = f"/chat/sessions/{session_id}/messages/stream"
    payload = {"text": user_input}
    
    try:
        response = client.stream("POST", path, json=payload)  # type: ignore[attr-defined]
        
        with response:  # type: ignore[attr-defined]
            for line in response.iter_lines():
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                
                event = parse_sse_line(line)
                if event:
                    yield event
    except APIError as e:
        # Re-raise API errors to be handled by caller
        raise


def render_token(content: str) -> None:
    """Render a token (incremental content) without newline."""
    print(content, end="", flush=True)


def render_stage(stage: str, status: str) -> None:
    """Render a stage update."""
    stage_emoji = {
        "risk": "🔍",
        "claims": "📋",
        "evidence_search": "🌐",
        "evidence_align": "🔗",
        "report": "📊",
        "simulation": "🎭",
        "content": "✍️",
    }
    
    status_emoji = {
        "running": "⏳",
        "done": "✅",
        "failed": "❌",
    }
    
    stage_name = {
        "risk": "风险快照",
        "claims": "主张抽取",
        "evidence_search": "证据检索",
        "evidence_align": "证据对齐",
        "report": "综合报告",
        "simulation": "舆情预演",
        "content": "应对内容",
    }
    
    emoji = stage_emoji.get(stage, "📌")
    status_mark = status_emoji.get(status, "")
    name = stage_name.get(stage, stage)
    
    if status == "running":
        print(f"\n{emoji} {name}中...")
    elif status == "done":
        print(f"{status_mark} {name}完成")


def render_message(message: Dict[str, Any]) -> None:
    """Render a complete message with actions and references."""
    content = message.get("content", "")
    actions = message.get("actions", [])
    references = message.get("references", [])
    
    # Print main content
    if content:
        print(f"\n{content}")
    
    # Print actions
    if actions:
        print("\n[相关操作]")
        for action in actions:
            label = action.get("label", "")
            command = action.get("command", "")
            href = action.get("href", "")
            
            if command:
                print(f"  • {label}: {command}")
            elif href:
                print(f"  • {label}: {href}")
    
    # Print references
    if references:
        print("\n[参考链接]")
        for ref in references[:5]:  # Limit to 5
            title = ref.get("title", "")
            href = ref.get("href", "")
            description = ref.get("description", "")
            
            print(f"  • {title}")
            if href:
                print(f"    {href}")
            if description:
                print(f"    {description}")


def render_error(error_msg: str) -> None:
    """Render an error message."""
    print(f"\n❌ 错误: {error_msg}")


def handle_sse_stream(
    client: APIClient, session_id: str, user_input: str
) -> None:
    """
    Handle SSE stream and render events.
    
    Args:
        client: API client instance
        session_id: Chat session ID
        user_input: User message text
    """
    try:
        for event in stream_chat_message(client, session_id, user_input):
            event_type = event.get("type")
            data = event.get("data", {})
            
            if event_type == "token":
                content = data.get("content", "")
                render_token(content)
            
            elif event_type == "stage":
                stage = data.get("stage", "")
                status = data.get("status", "")
                render_stage(stage, status)
            
            elif event_type == "message":
                message = data.get("message", {})
                render_message(message)
            
            elif event_type == "error":
                error_msg = data.get("message", "Unknown error")
                render_error(error_msg)
            
            elif event_type == "done":
                print()  # Final newline
                break
    
    except APIError as e:
        print(f"\n{e.user_friendly_message()}", file=sys.stderr)
    except Exception as e:
        print(f"\n❌ 意外错误: {e}", file=sys.stderr)


def create_session(client: APIClient) -> Optional[str]:
    """
    Create a new chat session.
    
    Args:
        client: API client instance
    
    Returns:
        Session ID or None if failed
    """
    try:
        response = client.post("/chat/sessions", json={})
        return response.get("session_id")
    except APIError as e:
        print(f"\n{e.user_friendly_message()}", file=sys.stderr)
        return None


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    print("\n\n[✓] 已退出对话模式", file=sys.stderr)
    sys.exit(0)


def chat(
    session_id: str = typer.Option(
        None,
        "--session-id",
        "-s",
        help="Session ID for continuing an existing conversation"
    )
) -> None:
    """
    Interactive chat mode for multi-turn conversations.
    
    Supports commands like:
    - /analyze <text>: Analyze news content
    - /why: Ask for explanation
    - /compare: Compare two analysis records
    - /help: Show available commands
    - /exit or quit: Exit chat mode
    """
    # Register Ctrl+C handler
    signal.signal(signal.SIGINT, signal_handler)
    from app.cli.main import get_global_config
    
    config = get_global_config()
    
    # Initialize API client
    client = APIClient(
        base_url=config.api_base,
        timeout=config.timeout,
        retry_times=config.retry_times,
    )
    
    # Get or create session
    if not session_id:
        # Try to load last session from state
        session_id = get_state_value("last_session_id") or None
    
    if not session_id:
        # Create new session
        print("🔄 创建新会话...")
        session_id = create_session(client)
        if not session_id:
            print("❌ 无法创建会话", file=sys.stderr)
            raise typer.Exit(1)
        
        # Save to state
        update_state("last_session_id", session_id)
        print(f"✅ 会话已创建: {session_id}\n")
    else:
        print(f"🔄 使用会话: {session_id}\n")
    
    # Welcome message
    print("=" * 60)
    print("TruthCast 对话工作台 - 交互式分析模式")
    print("=" * 60)
    print()
    print("💡 提示:")
    print("  • 输入 /help 查看可用命令")
    print("  • 输入 /analyze <文本> 开始分析")
    print("  • 输入 /exit 或 quit 退出")
    print()
    print("=" * 60)
    print()
    
    # REPL loop
    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            # Check for exit commands
            if user_input.lower() in ["/exit", "quit", "exit"]:
                print("\n[✓] 已退出对话模式")
                break
            
            # Send to backend and stream response
            print()  # Blank line before assistant response
            handle_sse_stream(client, session_id, user_input)
            print()  # Blank line after response
        
        except EOFError:
            # Handle Ctrl+D (Unix) or Ctrl+Z (Windows)
            print("\n\n[✓] 已退出对话模式")
            break
    
    # Clean exit
    client.close()
