from __future__ import annotations

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Raised when a reasoning provider cannot produce output."""


class ReasoningProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from a prompt."""
