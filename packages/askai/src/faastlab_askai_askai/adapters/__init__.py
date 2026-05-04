"""Concrete LLM adapters — OpenAI / Azure OpenAI / Ollama."""

from faastlab_askai_askai.adapters.llm_ollama import OllamaLLM
from faastlab_askai_askai.adapters.llm_openai import OpenAIChatLLM

__all__ = ["OllamaLLM", "OpenAIChatLLM"]
