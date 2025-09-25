# src/core/llm_wrapper.py
"""Rate-limited LLM wrapper module.

This module provides a shared RateLimitedLLM wrapper and factory functions
to create rate-limited LLM instances consistently across the codebase.
"""

from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableLambda
from .rate_limiter import rate_limiter


class RateLimitedLLM:
    """Wrapper to apply rate limiting to LLM calls"""
    
    def __init__(self, llm):
        self.llm = llm
    
    async def ainvoke(self, messages, **kwargs):
        return await rate_limiter.execute_with_limit(
            "openai",
            self.llm.ainvoke,
            messages,
            **kwargs
        )
    
    def __getattr__(self, name):
        # Delegate all other attributes to the wrapped LLM
        return getattr(self.llm, name)

    def as_runnable(self):
        async def _run(messages, **kwargs):
            return await rate_limiter.execute_with_limit(
                "openai", self.llm.ainvoke, messages, **kwargs
            )
        return RunnableLambda(_run)

    # --- LangChain integration helpers ---
    # Some helpers like create_react_agent expect a ChatModel with
    # methods such as bind_tools / with_structured_output. If callers
    # invoke these on the wrapper, ensure the resulting Runnable still
    # executes through our rate limiter.

    def _wrap_runnable(self, runnable):
        async def _run(messages, **kwargs):
            return await rate_limiter.execute_with_limit(
                "openai", runnable.ainvoke, messages, **kwargs
            )
        return RunnableLambda(_run)

    def bind_tools(self, tools, *args, **kwargs):
        bound = self.llm.bind_tools(tools, *args, **kwargs)
        return self._wrap_runnable(bound)

    def with_structured_output(self, schema, *args, **kwargs):
        bound = self.llm.with_structured_output(schema, *args, **kwargs)
        return self._wrap_runnable(bound)


def create_rate_limited_llm(model: str, **kwargs) -> RateLimitedLLM:
    """Factory function to create rate-limited LLMs
    
    Args:
        model: Model identifier (e.g., "openai:gpt-4.1")
        **kwargs: Additional arguments passed to init_chat_model
        
    Returns:
        RateLimitedLLM instance
    """
    base_llm = init_chat_model(model=model, **kwargs)
    return RateLimitedLLM(base_llm)
