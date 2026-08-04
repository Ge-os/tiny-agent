from __future__ import annotations

"""CLI entry point.

Creates .tiny-agent/ config dir in the target project on first run,
loads model config, builds the agent (Python jinja2 prompt templates),
runs interactive or one-shot mode.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import ApiClient
from app.context import ContextBuilder
from app.judge import Judge
from app.loop import AgentLoop
from app.prompts.roles import agent_names
from app.rag import Rag
from front.app import MinimalUI
from tools import register_builtin_tools
from tools.guards.state import SessionState
from tools.registry import get_registry

DEFAULT_TINY_DIR = ".tiny-agent"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_model(config: dict, model_name: str | None) -> dict:
    if model_name is None:
        model_name = config.get("default_model")
    for m in config.get("models", []):
        if m["name"] == model_name:
            return m
    sys.exit(f"Model '{model_name}' not found in config.json. Available: {[m['name'] for m in config.get('models', [])]}")


def ensure_project_config(cwd: str, model: dict) -> Path:
    """Create .tiny-agent/ with config.json if missing."""
    tiny_dir = Path(cwd) / DEFAULT_TINY_DIR
    tiny_dir.mkdir(exist_ok=True)
    (tiny_dir / "rules").mkdir(exist_ok=True)
    cfg_path = tiny_dir / "config.json"
    if not cfg_path.exists():
        project_cfg = {
            "model": model["name"],
            "auto_mode": False,
            "search_mode": "bm25",
            "tool_execution": "direct",  # "direct" | "subagent"
            "hidden_mode": True,
            "max_turns": 30,
        }
        cfg_path.write_text(json.dumps(project_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return tiny_dir


def build_judge(global_cfg: dict, cwd: str) -> Judge | None:
    """Judge: prefer a cloud/stronger model when a key is present; else skip (no local self-judge by default)."""
    for m in global_cfg.get("models", []):
        if m["provider"] in ("llamacpp", "ollama"):
            continue
        if m.get("api_key_env") and os.environ.get(m["api_key_env"]):
            client = ApiClient(
                endpoint=m["endpoint"],
                model=m["model"],
                api_key_env=m.get("api_key_env"),
                context_window=m.get("context_window", 8192),
                max_tokens=m.get("max_tokens", 2048),
                temperature=0.0,
            )
            if client.health_check():
                return Judge(client, cwd)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(prog="tiny-agent", description="Coding agent harness for tiny LLMs")
    parser.add_argument("--model", default=None, help="Model name from config.json")
    parser.add_argument("--agent", default="coder", help=f"Agent role: {', '.join(agent_names())}")
    parser.add_argument("--cwd", default=".", help="Project directory to operate in")
    parser.add_argument("--config", default="config.json", help="Path to global config.json")
    parser.add_argument("--no-judge", action="store_true", help="Disable LLM-as-judge")
    parser.add_argument("--list-models", action="store_true", help="List available models")
    parser.add_argument("--list-agents", action="store_true", help="List available agent roles")
    parser.add_argument("-p", "--prompt", default=None, help="One-shot prompt (non-interactive)")
    args = parser.parse_args()

    global_cfg = load_config(args.config)
    if args.list_models:
        for m in global_cfg.get("models", []):
            print(f"  {m['name']:<20} {m['provider']:<10} {m['model']}")
        return
    if args.list_agents:
        for a in agent_names():
            print(f"  {a}")
        return

    model = resolve_model(global_cfg, args.model)
    cwd = os.path.abspath(args.cwd)
    if not os.path.isdir(cwd):
        sys.exit(f"cwd '{cwd}' does not exist")

    ensure_project_config(cwd, model)
    project_cfg = json.loads((Path(cwd) / DEFAULT_TINY_DIR / "config.json").read_text(encoding="utf-8"))

    state = SessionState()
    register_builtin_tools(cwd, state)
    registry = get_registry()

    client = ApiClient(
        endpoint=model["endpoint"],
        model=model["model"],
        api_key_env=model.get("api_key_env"),
        context_window=model.get("context_window", 8192),
        max_tokens=model.get("max_tokens", 1024),
        temperature=0.2,
    )
    if not client.health_check():
        sys.exit(f"Model server at {model['endpoint']} is not reachable. Start llama-server / provider first.")

    ctx = ContextBuilder(cwd, model.get("context_window", 8192), project_cfg)
    rag = Rag()
    ui = MinimalUI()
    ui.start()

    def on_log(kind: str, text: str) -> None:
        getattr(ui, kind, ui.system)(text)

    def on_confirm(q: str, d: str) -> str:
        return ui.confirm(q, d)

    judge = None
    if not args.no_judge:
        judge = build_judge(global_cfg, cwd)
        if judge:
            ui.system(f"LLM-as-judge: {judge.client.model}")
        else:
            ui.system("LLM-as-judge: disabled (no cloud model with API key configured)")

    loop = AgentLoop(
        client=client,
        registry=registry,
        context_builder=ctx,
        state=state,
        cwd=cwd,
        agent_name=args.agent,
        max_turns=project_cfg.get("max_turns", 30),
        confirm_callback=on_confirm,
        log_callback=on_log,
        rag=rag,
        judge=judge,
    )

    ui.system(f"tiny-agent: model={model['name']} agent={loop.agent_name} cwd={cwd}")
    ui.system("Commands: /exit, /ls, /rules, /summary")
    if args.prompt:
        result = loop.run(args.prompt)
        print()
        print("=" * 60)
        print("FINAL:", result)
        return

    while True:
        text = ui.prompt()
        if text is None:
            break
        if text == "/exit":
            break
        if text == "/ls":
            ui.system("\n".join(sorted(os.listdir(cwd))))
            continue
        if text == "/rules":
            rules_dir = Path(cwd) / ".tiny-agent" / "rules"
            for p in sorted(rules_dir.glob("*.md")):
                ui.system(p.name)
            continue
        if text == "/summary":
            ui.system(loop.summary or "(no summary yet)")
            continue
        loop.run(text)


if __name__ == "__main__":
    main()
