from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import dspy
from dotenv import load_dotenv


DEFAULT_TASK = (
    "Сгенерируй системный промпт для Telegram-бота УК «Зелёный сад». "
    "Бот принимает обращения жителей, мягко ведет диалог по шагам, "
    "собирает данные заявки и передает в диспетчерскую."
)
DEFAULT_OUTPUT = Path("app/prompts/system.dspy.txt")
DEFAULT_EXAMPLES = Path("app/prompts/examples.json")


class SystemPromptBuilderSignature(dspy.Signature):
    """
    Build a strict production system prompt for housing support assistant.
    """

    task: str = dspy.InputField(desc="Business task in Russian.")
    policy_constraints: str = dspy.InputField(desc="Mandatory policies and forbidden behavior.")
    domain_context: str = dspy.InputField(desc="Domain context: channels, categories, data policy.")
    style_examples: str = dspy.InputField(desc="Few-shot style excerpts.")
    system_prompt: str = dspy.OutputField(
        desc=(
            "Final Russian system prompt only. "
            "No markdown wrappers, no explanations."
        )
    )


class SystemPromptBuilder(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.generate = dspy.Predict(SystemPromptBuilderSignature)

    def forward(self, task: str, policy_constraints: str, domain_context: str, style_examples: str):
        return self.generate(
            task=task,
            policy_constraints=policy_constraints,
            domain_context=domain_context,
            style_examples=style_examples,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate system prompt with DSPy.")
    parser.add_argument("--task", default=DEFAULT_TASK, help="Task description for prompt generation.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to output system prompt txt.")
    parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES), help="Path to examples.json.")
    parser.add_argument("--model", default=None, help="Override LLM model id.")
    parser.add_argument("--base-url", default=None, help="Override OpenAI-compatible /v1 URL.")
    parser.add_argument("--max-examples", type=int, default=8, help="How many examples to include.")
    return parser.parse_args()


def _require_env_or_args(args: argparse.Namespace) -> tuple[str, str, str]:
    model = args.model or os.getenv("LLM_MODEL", "").strip() or "Qwen3.5-35B-A3B"
    base_url = args.base_url or os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip() or "local"
    if not base_url:
        raise RuntimeError("LLM_BASE_URL is required (for local OpenAI-compatible endpoint).")
    if not base_url.lower().endswith("/v1"):
        raise RuntimeError("LLM_BASE_URL must end with /v1")
    return model, base_url, api_key


def _configure_dspy(model: str, base_url: str, api_key: str) -> None:
    model_id = model if "/" in model else f"openai/{model}"
    lm_kwargs: dict[str, object] = {
        "api_key": api_key,
        "api_base": base_url,
        "temperature": 0.1,
        "max_tokens": 1400,
    }
    if "qwen3.5" in model.lower():
        lm_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    lm = dspy.LM(model_id, **lm_kwargs)
    dspy.configure(lm=lm)


def _load_examples(path: Path, max_examples: int) -> str:
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return ""
    chunks: list[str] = []
    for item in data[:max_examples]:
        user = str(item.get("user", "")).strip()
        assistant = str(item.get("assistant", "")).strip()
        if user and assistant:
            chunks.append(f"Пользователь: {user}\nАссистент: {assistant}")
    return "\n\n".join(chunks)


def _policy_constraints() -> str:
    return (
        "1) Тон: заботливая поддержка, коротко, спокойно, по шагам.\n"
        "2) Никогда не выдумывать сроки и причины неисправности.\n"
        "3) Если данных нет, честно говорить: «уточняю» или «создам заявку».\n"
        "4) Всегда уточнять ЖК и адрес (дом/подъезд/квартира), если не хватает данных.\n"
        "5) Контакты мастеров не выдавать, только диспетчер/заявка.\n"
        "6) Допустимо собирать ФИО, телефон, квартиру, адрес.\n"
        "7) Ответы без канцелярита."
    )


def _domain_context() -> str:
    return (
        "Канал: Telegram.\n"
        "Интеграция: Bitrix24.\n"
        "Категории: water_off, water_leak, electricity_off, elevator, heating, sewage, intercom, cleaning, other.\n"
        "При массовом инциденте использовать единое уведомление и сохранять заявку.\n"
        "Текущая задача бота: помочь жителю оформить корректную заявку в диспетчерскую."
    )


def _sanitize_output(raw: str) -> str:
    text = raw.strip()
    text = text.removeprefix("```").removesuffix("```").strip()
    if text.lower().startswith("system prompt:"):
        text = text.split(":", 1)[1].strip()
    return text


def _ensure_minimum_requirements(text: str) -> str:
    must_have = [
        "Заботливая поддержка",
        "не выдумывай сроки и причины",
        "уточняй ЖК и адрес",
        "контакты мастеров не выдавай",
    ]
    lower = text.lower()
    missing = [item for item in must_have if item.lower() not in lower]
    if not missing:
        return text

    appendix = (
        "\n\nОбязательные ограничения:\n"
        "- Стиль: «Заботливая поддержка».\n"
        "- Не выдумывай сроки и причины неисправности.\n"
        "- Всегда уточняй ЖК и адрес (дом/подъезд/квартира), если данных нет.\n"
        "- Контакты мастеров не выдавай, только диспетчер/заявка."
    )
    return text + appendix


def main() -> int:
    load_dotenv()
    args = parse_args()

    model, base_url, api_key = _require_env_or_args(args)
    _configure_dspy(model=model, base_url=base_url, api_key=api_key)

    examples_text = _load_examples(Path(args.examples), max_examples=args.max_examples)
    program = SystemPromptBuilder()
    prediction = program(
        task=args.task,
        policy_constraints=_policy_constraints(),
        domain_context=_domain_context(),
        style_examples=examples_text,
    )
    prompt = _sanitize_output(str(getattr(prediction, "system_prompt", "") or "").strip())
    prompt = _ensure_minimum_requirements(prompt)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output_path),
                "model": model,
                "base_url": base_url,
                "chars": len(prompt),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

