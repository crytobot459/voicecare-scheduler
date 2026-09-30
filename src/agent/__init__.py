"""VoiceCare agent harness — pure English, LLM-first.

Public surface used by CLI, Streamlit, video and tests.
Keys are read from environment only, never logged.
"""
from .loop import run_agent_turn
from .config import key_status, has_assemblyai, has_gemini

__all__ = ["run_agent_turn", "key_status", "has_assemblyai", "has_gemini"]
