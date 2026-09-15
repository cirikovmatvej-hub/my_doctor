"""Admin-only utilities — currently just /stats for QR/deep-link attribution."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_TELEGRAM_IDS
from data.resources import BADS
from database.db import get_acquisition_stats

router = Router()


def _display_name(source: str) -> str:
    key = source.removeprefix("qr_")
    return BADS.get(key, {}).get("name", source)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    # Silent no-op for non-admins rather than an "access denied" reply —
    # that would confirm the command exists at all to anyone who tries it.
    if message.from_user.id not in ADMIN_TELEGRAM_IDS:
        return

    rows = await get_acquisition_stats()
    if not rows:
        await message.answer("📊 Пока нет ни одного перехода по отслеживаемым ссылкам.")
        return

    lines = ["📊 <b>Переходы по QR/deep-link источникам</b>\n"]
    total_scans = 0
    total_new = 0
    for source, scans, new_users in rows:
        new_users = new_users or 0
        total_scans += scans
        total_new += new_users
        lines.append(
            f"<b>{_display_name(source)}</b> (<code>{source}</code>)\n"
            f"  переходов: {scans}, новых пользователей: {new_users}"
        )

    lines.append(f"\n<b>Итого:</b> переходов {total_scans}, новых пользователей {total_new}")
    await message.answer("\n".join(lines), parse_mode="HTML")
