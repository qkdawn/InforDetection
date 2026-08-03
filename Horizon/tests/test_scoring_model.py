from types import SimpleNamespace

from src.models import AIConfig
from src.orchestrator import HorizonOrchestrator


def _orchestrator(ai: AIConfig) -> HorizonOrchestrator:
    orchestrator = object.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(ai=ai)
    return orchestrator


def test_scoring_model_overrides_default_model() -> None:
    ai = AIConfig(
        provider="openai",
        model="gpt-5.6-sol",
        scoring_model="gpt-5.6-luna",
        api_key_env="OPENAI_API_KEY",
    )

    scoring_ai = _orchestrator(ai)._scoring_ai_config()

    assert scoring_ai.model == "gpt-5.6-luna"
    assert ai.model == "gpt-5.6-sol"


def test_scoring_model_falls_back_to_default_model() -> None:
    ai = AIConfig(
        provider="openai",
        model="gpt-5.6-sol",
        api_key_env="OPENAI_API_KEY",
    )

    assert _orchestrator(ai)._scoring_ai_config().model == "gpt-5.6-sol"
