"""Large SillyTavern character-card payload boundaries."""

from uuid import uuid4

from backend.schemas import CharacterTemplateCreate, WorldBookEntryCreate


def test_large_v3_character_card_payload_fits_local_storage_limits() -> None:
    character = CharacterTemplateCreate(
        name="大型角色卡",
        avatar="data:image/png;base64," + "A" * 7_800_000,
        world_book_ids=[uuid4() for _ in range(216)],
    )
    entry = WorldBookEntryCreate(title="变量更新规则", content="设定" * 10_801)

    assert len(character.world_book_ids) == 216
    assert len(entry.content) == 21_602
