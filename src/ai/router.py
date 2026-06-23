"""AI model router - routes tasks to the appropriate AI provider and model."""

import logging

from .claude_client import ClaudeClient
from .groq_client import GroqClient
from .ollama_client import OllamaClient
from src.utils.security import sanitize_error

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_TASK = {
    "job_scoring": 1024,
    "resume_generation": 4096,
    "cover_letter": 1024,
    "form_field_answer": 256,
}
MAX_TOKENS_ABSOLUTE = 4096

TASK_TIERS = {
    "job_scoring": "cheap",
    "resume_generation": "quality",
    "cover_letter": "quality",
    "form_field_answer": "cheap",
}


class AIRouter:
    """Routes AI requests to the appropriate provider based on task type."""

    def __init__(self, config: dict):
        ai_config = config.get("ai", {})

        self.primary_provider = ai_config.get("primary_provider", "anthropic")
        self.fallback_provider = ai_config.get("fallback_provider", "groq")

        anthropic_config = ai_config.get("anthropic", {})
        groq_config = ai_config.get("groq", {})
        ollama_config = ai_config.get("ollama", {})

        self.claude = None
        self.groq = None
        self.ollama = None

        api_key = anthropic_config.get("api_key", "")
        if api_key:
            self.claude = ClaudeClient(api_key=api_key)

        groq_key = groq_config.get("api_key", "")
        if groq_key:
            self.groq = GroqClient(
                api_key=groq_key,
                daily_limit=groq_config.get("rate_limit", 14400),
            )

        if ollama_config.get("enabled", False) or self.primary_provider == "ollama":
            self.ollama = OllamaClient(
                host=ollama_config.get("host", "http://localhost:11434"),
                timeout=ollama_config.get("timeout", 120.0),
            )

        # Validate at least one provider is configured
        if not self.claude and not self.groq and not self.ollama:
            raise RuntimeError(
                "No AI providers configured. "
                "Set ANTHROPIC_API_KEY, GROQ_API_KEY, or enable ollama in config."
            )

        configured = []
        if self.claude:
            configured.append("Anthropic (Claude)")
        if self.groq:
            configured.append("Groq")
        if self.ollama:
            configured.append("Ollama (local)")
        logger.info("AI providers configured: %s", ", ".join(configured))

        self.models = anthropic_config.get("models", {
            "cheap": "claude-haiku-4-5-20251001",
            "quality": "claude-sonnet-4-6",
        })
        self.groq_model = groq_config.get("model", "llama-3.3-70b-versatile")
        self.ollama_models = ollama_config.get("models", {
            "cheap": "qwen2.5:7b",
            "quality": "qwen2.5:32b-instruct",
        })

        routing = ai_config.get("routing", {})
        self.task_routing = {**TASK_TIERS, **routing}

    def _get_client_and_model(self, task: str, use_fallback: bool = False):
        """Determine which client and model to use for a task."""
        tier = self.task_routing.get(task, "cheap")
        provider = self.fallback_provider if use_fallback else self.primary_provider

        if provider == "anthropic" and self.claude:
            model = self.models.get(tier, self.models.get("cheap"))
            return self.claude, model
        elif provider == "groq" and self.groq:
            return self.groq, self.groq_model
        elif provider == "ollama" and self.ollama:
            model = self.ollama_models.get(tier, self.ollama_models.get("cheap"))
            return self.ollama, model
        # Fallback cascade: prefer whatever is configured
        elif self.claude:
            model = self.models.get(tier, self.models.get("cheap"))
            return self.claude, model
        elif self.groq:
            return self.groq, self.groq_model
        elif self.ollama:
            model = self.ollama_models.get(tier, self.ollama_models.get("cheap"))
            return self.ollama, model
        else:
            raise RuntimeError("No AI providers configured. Check your API keys.")

    def _cap_tokens(self, task: str, requested: int) -> int:
        """Enforce hard token limits per task."""
        task_cap = MAX_TOKENS_PER_TASK.get(task, MAX_TOKENS_ABSOLUTE)
        return min(requested, task_cap, MAX_TOKENS_ABSOLUTE)

    def route(self, task: str, prompt: str, system_prompt: str = "",
              max_tokens: int = 1024, temperature: float = 0.7) -> str:
        """Route a text completion request to the appropriate AI provider."""
        max_tokens = self._cap_tokens(task, max_tokens)
        client, model = self._get_client_and_model(task)

        try:
            result = client.complete(
                prompt=prompt, model=model, max_tokens=max_tokens,
                system_prompt=system_prompt, temperature=temperature,
            )
            logger.info("AI [%s] %s/%s: OK", task, type(client).__name__, model)
            return result
        except Exception as e:
            logger.warning("Primary provider failed for %s: %s. Trying fallback...", task, sanitize_error(e))
            client, model = self._get_client_and_model(task, use_fallback=True)
            result = client.complete(
                prompt=prompt, model=model, max_tokens=max_tokens,
                system_prompt=system_prompt, temperature=temperature,
            )
            logger.info("AI [%s] fallback %s/%s: OK", task, type(client).__name__, model)
            return result

    def route_json(self, task: str, prompt: str, system_prompt: str = "",
                   max_tokens: int = 2048, temperature: float = 0.3) -> dict:
        """Route a JSON completion request to the appropriate AI provider."""
        max_tokens = self._cap_tokens(task, max_tokens)
        client, model = self._get_client_and_model(task)

        try:
            result = client.complete_json(
                prompt=prompt, model=model, max_tokens=max_tokens,
                system_prompt=system_prompt, temperature=temperature,
            )
            logger.info("AI JSON [%s] %s/%s: OK", task, type(client).__name__, model)
            return result
        except Exception as e:
            logger.warning("Primary provider failed for %s: %s. Trying fallback...", task, sanitize_error(e))
            client, model = self._get_client_and_model(task, use_fallback=True)
            result = client.complete_json(
                prompt=prompt, model=model, max_tokens=max_tokens,
                system_prompt=system_prompt, temperature=temperature,
            )
            logger.info("AI JSON [%s] fallback %s/%s: OK", task, type(client).__name__, model)
            return result

    @property
    def cost_summary(self) -> str:
        """Return a summary of estimated costs."""
        parts = []
        if self.claude:
            parts.append(f"Claude: ~${self.claude.estimated_cost:.4f}")
            parts.append(f"  Tokens: {self.claude.total_input_tokens} in / {self.claude.total_output_tokens} out")
        if self.groq:
            parts.append(f"Groq: {self.groq.requests_remaining} requests remaining today")
        if self.ollama:
            parts.append(
                f"Ollama (local): {self.ollama.total_input_tokens} in / "
                f"{self.ollama.total_output_tokens} out (no cost)"
            )
        return "\n".join(parts) if parts else "No providers active"
