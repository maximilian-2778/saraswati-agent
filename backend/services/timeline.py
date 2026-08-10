"""Story-time normalization, progression and contradiction detection."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import TimelineAnchorRecord


_ABSOLUTE_PATTERNS = (
    re.compile(r"(?P<y>\d{4})[-/.年](?P<m>\d{1,2})[-/.月](?P<d>\d{1,2})日?(?:[ T，,]*(?P<h>\d{1,2})[:点时](?P<minute>\d{1,2})?分?)?"),
)
_RELATIVE = re.compile(r"(?P<n>\d+|一|两|二|三|四|五|六|七|八|九|十)(?P<u>分钟|小时|天|日|周|个月|月|年)(?P<direction>后|前)")
_FLASHBACK = re.compile(r"回忆|闪回|倒叙|梦境|时间旅行|穿越|回到过去")
_CN_NUMBERS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_story_time(value: str, base: datetime | None = None) -> datetime | None:
    text = value.strip()
    for pattern in _ABSOLUTE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return datetime(
                    int(match.group("y")), int(match.group("m")), int(match.group("d")),
                    int(match.group("h") or 0), int(match.group("minute") or 0), tzinfo=UTC,
                )
            except ValueError:
                return None
    if base is None:
        return None
    if re.search(r"次日|翌日|第二天", text):
        return base + timedelta(days=1)
    if re.search(r"同日|当天", text):
        return base
    match = _RELATIVE.search(text)
    if not match:
        return None
    raw = match.group("n")
    count = int(raw) if raw.isdigit() else _CN_NUMBERS.get(raw, 0)
    unit = match.group("u")
    days = count * ({"天": 1, "日": 1, "周": 7, "个月": 30, "月": 30, "年": 365}.get(unit, 0))
    delta = timedelta(days=days) if days else timedelta(hours=count if unit == "小时" else 0, minutes=count if unit == "分钟" else 0)
    return base + delta if match.group("direction") == "后" else base - delta


class TimelineService:
    def list(self, db: Session, chat_id: str) -> list[TimelineAnchorRecord]:
        return list(db.scalars(select(TimelineAnchorRecord).where(
            TimelineAnchorRecord.chat_id == chat_id
        ).order_by(TimelineAnchorRecord.created_at, TimelineAnchorRecord.id)).all())

    def current(self, db: Session, chat_id: str) -> tuple[TimelineAnchorRecord | None, datetime | None]:
        current: TimelineAnchorRecord | None = None
        resolved: datetime | None = None
        for anchor in self.list(db, chat_id):
            if anchor.is_conflict:
                continue
            candidate = parse_story_time(anchor.story_time, resolved)
            current, resolved = anchor, candidate or resolved
        return current, resolved

    def create(
        self, db: Session, chat_id: str, story_time: str, description: str,
        source_message_id: str | None = None,
    ) -> TimelineAnchorRecord:
        duplicate = db.scalar(select(TimelineAnchorRecord).where(
            TimelineAnchorRecord.chat_id == chat_id,
            TimelineAnchorRecord.story_time == story_time.strip(),
            TimelineAnchorRecord.source_message_id == source_message_id,
        ))
        if duplicate:
            return duplicate
        previous, previous_time = self.current(db, chat_id)
        proposed = parse_story_time(story_time, previous_time)
        is_conflict = bool(
            proposed and previous_time and proposed < previous_time
            and not _FLASHBACK.search(f"{story_time} {description}")
        )
        reason = ""
        if is_conflict:
            reason = f"该时间早于当前时间锚点“{previous.story_time if previous else ''}”，且未标记为回忆、倒叙或时间旅行。"
        now = datetime.now(UTC)
        record = TimelineAnchorRecord(
            id=str(uuid4()), chat_id=chat_id, story_time=story_time.strip(),
            description=description.strip(), source_message_id=source_message_id,
            is_conflict=is_conflict, conflict_reason=reason, created_at=now, updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def context_text(self, db: Session, chat_id: str) -> str:
        anchors = self.list(db, chat_id)
        valid = [item for item in anchors if not item.is_conflict]
        if not valid:
            return ""
        current = valid[-1]
        lines = [f"当前故事时间：{current.story_time}（{current.description}）"]
        if len(valid) > 1:
            lines.append("最近时间推进：")
            lines.extend(f"- {item.story_time}：{item.description}" for item in valid[-4:-1])
        conflicts = [item for item in anchors if item.is_conflict]
        if conflicts:
            lines.append(f"检测到 {len(conflicts)} 条待核对的时间矛盾；不要据此倒退当前时间。")
        lines.append("续写时以当前故事时间为准；除非明确写出回忆、倒叙或时间旅行，否则时间只能保持或向前推进。")
        return "\n".join(lines)


timeline_service = TimelineService()
