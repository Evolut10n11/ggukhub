from __future__ import annotations

import logging

from app.config import Settings
from app.responders.base import BaseResponder
from app.responders.rule_responder import RuleResponder

logger = logging.getLogger(__name__)


def create_responder(settings: Settings) -> BaseResponder:
    if settings.use_llm and settings.llm_responder_enabled and settings.llm_base_url and settings.llm_model:
        try:
            from app.responders.llm_responder import LLMResponder

            return LLMResponder(settings)
        except Exception as error:
            logger.info("LLM responder unavailable, fallback to RuleResponder: %s", error)
    return RuleResponder()
