"""针对结构化数值状态的生成后一致性审计。"""

import re
from datetime import UTC, datetime
from numbers import Number
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.models import AuditIssueRecord, StateEntryRecord
from backend.schemas import AuditStatus
from backend.utils import json_dumps, json_loads


class AuditService:
    """从 AI 回复中发现与当前状态明显冲突的数值。"""

    def audit_message(
        self,
        db: Session,
        chat_id: str,
        message_id: str,
        content: str,
        state_entries: list[StateEntryRecord],
    ) -> list[AuditIssueRecord]:
        issues: list[AuditIssueRecord] = []

        for entry in state_entries:
            expected = json_loads(entry.value_json)
            if isinstance(expected, bool) or not isinstance(expected, Number):
                continue

            pattern = re.compile(
                rf"{re.escape(entry.key)}[^\d-]{{0,12}}(-?\d+(?:\.\d+)?)",
                re.IGNORECASE,
            )
            for match in pattern.finditer(content):
                raw_actual = match.group(1)
                actual = float(raw_actual) if "." in raw_actual else int(raw_actual)
                if float(actual) == float(expected):
                    continue

                start = max(match.start() - 30, 0)
                end = min(match.end() + 30, len(content))
                evidence = content[start:end]
                issue = AuditIssueRecord(
                    id=str(uuid4()),
                    chat_id=chat_id,
                    message_id=message_id,
                    category="numeric_state_conflict",
                    severity="medium",
                    description=(
                        f"回复中的“{entry.entity}.{entry.key}”与已批准状态不一致"
                    ),
                    expected_value_json=json_dumps(expected),
                    actual_value_json=json_dumps(actual),
                    evidence=evidence,
                    status=AuditStatus.OPEN.value,
                    created_at=datetime.now(UTC),
                )
                db.add(issue)
                issues.append(issue)
                break

        if issues:
            db.commit()
            for issue in issues:
                db.refresh(issue)
        return issues
