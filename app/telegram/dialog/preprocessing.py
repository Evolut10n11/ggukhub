from __future__ import annotations

from dataclasses import dataclass

from app.core.models import User
from app.core.storage import Storage
from app.core.utils import normalize_text
from app.telegram.dialog.models import DialogSessionData, DialogSnapshot
from app.telegram.dialog.state_machine import is_report_status_request, merge_extracted_context
from app.telegram.extractors import ExtractedReportContext, extract_report_context


@dataclass(slots=True)
class DialogPreprocessResult:
    text: str
    normalized_text: str
    extracted: ExtractedReportContext
    data: DialogSessionData
    status_requested: bool
    phone_synced: bool


class DialogInputPreprocessor:
    def __init__(self, *, storage: Storage, housing_complexes: list[str]) -> None:
        self._storage = storage
        self._housing_complexes = list(housing_complexes)

    async def preprocess(
        self,
        *,
        user: User,
        snapshot: DialogSnapshot,
        text: str,
    ) -> DialogPreprocessResult:
        stripped_text = text.strip()
        extracted = extract_report_context(stripped_text, self._housing_complexes)
        data = merge_extracted_context(snapshot.data, extracted)
        phone_synced = await self._sync_extracted_phone(user, extracted)
        return DialogPreprocessResult(
            text=stripped_text,
            normalized_text=normalize_text(stripped_text),
            extracted=extracted,
            data=data,
            status_requested=is_report_status_request(stripped_text),
            phone_synced=phone_synced,
        )

    async def _sync_extracted_phone(self, user: User, extracted: ExtractedReportContext) -> bool:
        if not extracted.phone or extracted.phone == user.phone:
            return False
        await self._storage.update_user_phone(user.id, extracted.phone)
        user.phone = extracted.phone
        return True
