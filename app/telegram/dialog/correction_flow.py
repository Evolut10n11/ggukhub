from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.core.utils import normalize_text
from app.telegram.dialog.models import DialogSessionData
from app.telegram.dialog.state_machine import category_from_text
from app.telegram.extractors import ExtractedReportContext


@dataclass(slots=True)
class CorrectionUpdate:
    data: DialogSessionData
    correction_field: str | None
    parsed_category: str | None
    phone_to_sync: str | None
    has_structured_updates: bool


class DialogCorrectionFlow:
    def __init__(
        self,
        *,
        categories: Iterable[str],
        label_resolver: Callable[[str], str],
    ) -> None:
        self._categories = tuple(categories)
        self._label_resolver = label_resolver

    def apply(
        self,
        *,
        data: DialogSessionData,
        extracted: ExtractedReportContext,
        text: str,
    ) -> CorrectionUpdate:
        updated = data.model_copy()
        if extracted.jk:
            updated.jk = extracted.jk
        if extracted.house:
            updated.house = extracted.house
        if extracted.entrance:
            updated.entrance = extracted.entrance
        if extracted.apartment:
            updated.apartment = extracted.apartment
        if extracted.phone:
            updated.phone = extracted.phone

        parsed_category = category_from_text(
            text,
            categories=self._categories,
            label_resolver=self._label_resolver,
        )
        if parsed_category is not None:
            updated.category = parsed_category
            updated.auto_category = parsed_category

        return CorrectionUpdate(
            data=updated,
            correction_field=self.correction_field_from_text(text),
            parsed_category=parsed_category,
            phone_to_sync=extracted.phone,
            has_structured_updates=any(
                value is not None
                for value in (
                    extracted.jk,
                    extracted.house,
                    extracted.entrance,
                    extracted.apartment,
                    extracted.phone,
                    parsed_category,
                )
            ),
        )

    @staticmethod
    def correction_field_from_text(text: str) -> str | None:
        value = normalize_text(text)
        if value in {"категория", "категорию", "тип", "тип заявки"}:
            return "category"
        if value in {"адрес", "дом", "подъезд", "квартира"}:
            return "address"
        if value in {"телефон", "номер", "номер телефона"}:
            return "phone"
        if value in {"описание", "описание проблемы", "проблему", "текст"}:
            return "problem"
        return None
