from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)


# ── Main menu (5 buttons) ─────────────────────────────────────────────────

# Single source of truth for main-menu button texts — reused wherever a
# free-text FSM input needs to reject an accidental menu-button press instead
# of swallowing it as data (e.g. tracker.py's "enter a custom BAD name" step).
MAIN_MENU_LABELS: frozenset[str] = frozenset({
    "🤖 Консультация с ИИ",
    "💊 Подбор БАД",
    "📊 Мой трекер",
    "📔 Дневник",
    "📋 История",
    "👨‍👩‍👧 Семья",
    "⚙️ Мой профиль",
})


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Консультация с ИИ")],
            [KeyboardButton(text="💊 Подбор БАД"), KeyboardButton(text="📊 Мой трекер")],
            [KeyboardButton(text="📔 Дневник"),    KeyboardButton(text="📋 История")],
            [KeyboardButton(text="👨‍👩‍👧 Семья"),    KeyboardButton(text="⚙️ Мой профиль")],
        ],
        resize_keyboard=True,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


async def bail_if_menu_button(message: Message, state: FSMContext) -> bool:
    """If the user pressed a main-menu button while stuck in an unrelated
    free-text FSM step, exit that flow instead of swallowing the button label
    as data (e.g. a "supplement" or family member literally named
    "🤖 Консультация с ИИ"). Call at the top of any free-text state handler;
    if this returns True, the caller should return immediately."""
    if message.text in MAIN_MENU_LABELS:
        await state.clear()
        await message.answer(
            "Похоже, вы хотели перейти в другой раздел — вышел из текущего шага. "
            "Нажмите на кнопку ещё раз 👇",
            reply_markup=main_menu(),
        )
        return True
    return False


# ── Profile ───────────────────────────────────────────────────────────────

def gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👨 Мужской", callback_data="gender:male"),
                InlineKeyboardButton(text="👩 Женский",  callback_data="gender:female"),
            ]
        ]
    )


def age_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="До 18 лет", callback_data="age:under_18"),
                InlineKeyboardButton(text="18–30 лет", callback_data="age:18_30"),
            ],
            [
                InlineKeyboardButton(text="31–45 лет", callback_data="age:31_45"),
                InlineKeyboardButton(text="46–60 лет", callback_data="age:46_60"),
            ],
            [InlineKeyboardButton(text="60+ лет", callback_data="age:60_plus")],
        ]
    )


def skip_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    """Single 'Нет / Пропустить' inline button for health questions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Нет / Пропустить", callback_data=callback_data),
        ]]
    )


def update_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✏️ Обновить анкету", callback_data="profile:update"),
        ]]
    )


def pregnancy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤰 Да, беременна",       callback_data="pregnancy:pregnant")],
            [InlineKeyboardButton(text="🤱 Лактация",             callback_data="pregnancy:lactating")],
            [InlineKeyboardButton(text="❌ Нет / Не применимо",   callback_data="pregnancy:no")],
        ]
    )


def smoking_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚭 Не курю",          callback_data="smoking:never")],
            [InlineKeyboardButton(text="🕰 Бросил(а)",         callback_data="smoking:former")],
            [InlineKeyboardButton(text="🚬 Иногда (до 5/день)", callback_data="smoking:light")],
            [InlineKeyboardButton(text="🚬 Регулярно (5+/день)", callback_data="smoking:heavy")],
        ]
    )


def alcohol_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Не употребляю",        callback_data="alcohol:never")],
            [InlineKeyboardButton(text="🥂 Редко (по праздникам)", callback_data="alcohol:rarely")],
            [InlineKeyboardButton(text="🍷 Умеренно (1–2р/нед)",   callback_data="alcohol:moderate")],
            [InlineKeyboardButton(text="🍺 Часто (почти каждый день)", callback_data="alcohol:frequent")],
        ]
    )


def activity_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛋 Сидячий (почти нет движения)",   callback_data="activity:sedentary")],
            [InlineKeyboardButton(text="🚶 Лёгкая (прогулки, зарядка)",     callback_data="activity:light")],
            [InlineKeyboardButton(text="🏃 Умеренная (3–4 тренировки/нед)", callback_data="activity:moderate")],
            [InlineKeyboardButton(text="💪 Высокая (ежедневные нагрузки)",  callback_data="activity:high")],
        ]
    )


# ── Follow-up ─────────────────────────────────────────────────────────────

def followup_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Стало лучше",        callback_data=f"fu:better:{session_id}"),
                InlineKeyboardButton(text="🩺 Нужна консультация", callback_data=f"fu:new:{session_id}"),
            ]
        ]
    )


# ── BAD advisor ───────────────────────────────────────────────────────────

def bad_goals_keyboard(suggested_keys: list[str] | None = None) -> InlineKeyboardMarkup:
    from data.resources import BAD_GOALS

    suggested_keys = suggested_keys or []
    ordered_keys = [k for k in suggested_keys if k in BAD_GOALS] + [
        k for k in BAD_GOALS if k not in suggested_keys
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=("⭐ " if key in suggested_keys else "") + BAD_GOALS[key]["label"],
                callback_data=f"badgoal:{key}",
            )]
            for key in ordered_keys
        ]
    )


def goal_clarify_keyboard(goal_key: str, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"badclarify:{goal_key}:{option_key}")]
            for option_key, label in options
        ]
    )


# ── Tracker ───────────────────────────────────────────────────────────────

def track_start_keyboard(product_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔔 Начать курс", callback_data=f"track:start:{product_key}"),
        ]]
    )


def general_supplement_keyboard(name: str) -> InlineKeyboardMarkup:
    """For AI recommendations outside our catalog — starts the custom-BAD
    tracker flow pre-filled with this name (skips the "what's it called" step)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🔔 Отслеживать приём", callback_data=f"track:customstart:{name[:40]}"
            ),
        ]]
    )


def tracker_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Другой БАД", callback_data="track:custom")],
            [InlineKeyboardButton(text="📜 История курсов", callback_data="track:history")],
        ]
    )


def tracker_stop_list_keyboard(trackings: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """trackings: list of (tracking_id, display_name) — one row per active course."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 {name}", callback_data=f"track:delete:{tracking_id}")]
            for tracking_id, name in trackings
        ]
    )


def tracker_delete_confirm_keyboard(tracking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, остановить", callback_data=f"track:delete_confirm:{tracking_id}"),
        InlineKeyboardButton(text="❌ Отмена",         callback_data="track:delete_cancel"),
    ]])


def daily_doses_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="1 раз в день", callback_data="dailydoses:1"),
            InlineKeyboardButton(text="2 раза в день", callback_data="dailydoses:2"),
        ]]
    )


def timezone_keyboard() -> InlineKeyboardMarkup:
    zones = [
        ("UTC+2 Калининград", 2), ("UTC+3 Москва/СПб", 3), ("UTC+4 Самара", 4),
        ("UTC+5 Екатеринбург", 5), ("UTC+6 Омск", 6), ("UTC+7 Красноярск", 7),
        ("UTC+8 Иркутск", 8), ("UTC+9 Якутск", 9), ("UTC+10 Владивосток", 10),
        ("UTC+11 Магадан", 11), ("UTC+12 Камчатка", 12),
    ]
    rows = []
    for i in range(0, len(zones), 2):
        row = []
        for label, offset in zones[i:i+2]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"tz:{offset}"))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_keyboard(prefix: str, can_skip: bool = False) -> InlineKeyboardMarkup:
    """Grid of common times + 'Своё время' option."""
    times = ["07:00", "08:00", "09:00", "10:00", "12:00", "18:00",
             "19:00", "20:00", "21:00", "22:00"]
    rows = []
    for i in range(0, len(times), 3):
        rows.append([
            InlineKeyboardButton(text=t, callback_data=f"{prefix}:{t}")
            for t in times[i:i+3]
        ])
    last_row = [InlineKeyboardButton(text="✏️ Своё время", callback_data=f"{prefix}:custom")]
    if can_skip:
        last_row.append(InlineKeyboardButton(text="🚫 Не нужно", callback_data=f"{prefix}:none"))
    rows.append(last_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def intake_keyboard(tracking_id: int, time_of_day: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Принял",
                callback_data=f"intake:taken:{tracking_id}:{time_of_day}",
            ),
            InlineKeyboardButton(
                text="⏭ Пропустить",
                callback_data=f"intake:skip:{tracking_id}:{time_of_day}",
            ),
        ]]
    )


# ── Diary ─────────────────────────────────────────────────────────────────

def rating_keyboard(prefix: str, reverse: bool = False) -> InlineKeyboardMarkup:
    """1–5 rating row. reverse=True for scales where 1 is good (e.g. stress)."""
    if reverse:
        labels = {1: "😌 1", 2: "🙂 2", 3: "😐 3", 4: "😟 4", 5: "😰 5"}
    else:
        labels = {1: "😞 1", 2: "😕 2", 3: "😐 3", 4: "😊 4", 5: "😄 5"}
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=labels[i], callback_data=f"{prefix}:{i}")
            for i in range(1, 6)
        ]]
    )


def bads_taken_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data="diary:bads:yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="diary:bads:no"),
        ]]
    )


# ── Family ────────────────────────────────────────────────────────────────

def relation_keyboard() -> InlineKeyboardMarkup:
    relations = ["сын", "дочь", "муж", "жена", "мама", "папа", "брат", "сестра", "другое"]
    rows = []
    for i in range(0, len(relations), 3):
        rows.append([
            InlineKeyboardButton(text=r, callback_data=f"relation:{r}")
            for r in relations[i:i+3]
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def family_list_keyboard(members: list) -> InlineKeyboardMarkup:
    rows = []
    for member_id, name, relation in members:
        rows.append([InlineKeyboardButton(
            text=f"👤 {name} ({relation})",
            callback_data=f"family:view:{member_id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="family:add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def family_member_keyboard(member_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Обновить анкету", callback_data=f"family:edit:{member_id}")],
        [InlineKeyboardButton(text="🗑 Удалить профиль",  callback_data=f"family:delete:{member_id}")],
        [InlineKeyboardButton(text="◀️ Назад",            callback_data="family:list")],
    ])


def family_delete_keyboard(member_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить",  callback_data=f"family:delete_confirm:{member_id}"),
        InlineKeyboardButton(text="❌ Отмена",       callback_data=f"family:view:{member_id}"),
    ]])


def appointment_booked_keyboard(followup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, записался",  callback_data=f"appt:booked:{followup_id}"),
        InlineKeyboardButton(text="❌ Нет",            callback_data=f"appt:notbooked:{followup_id}"),
    ]])


def appointment_reason_keyboard(followup_id: int) -> InlineKeyboardMarkup:
    reasons = [
        ("💰 Дорого", "expensive"),
        ("⏰ Не было времени", "no_time"),
        ("🤔 Решил(а) понаблюдать", "watch"),
        ("📝 Другое", "other"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"appt:reason:{followup_id}:{key}")]
        for label, key in reasons
    ])


def appointment_remind_keyboard(followup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Завтра утром",   callback_data=f"appt:remind:{followup_id}:tomorrow")],
        [InlineKeyboardButton(text="📅 Через 3 дня",     callback_data=f"appt:remind:{followup_id}:3days")],
        [InlineKeyboardButton(text="🗓 Через неделю",    callback_data=f"appt:remind:{followup_id}:week")],
        [InlineKeyboardButton(text="✏️ Своя дата",       callback_data=f"appt:remind:{followup_id}:custom")],
        [InlineKeyboardButton(text="🚫 Не нужно",        callback_data=f"appt:remind:{followup_id}:none")],
    ])


def consult_for_keyboard(members: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="👤 Для себя", callback_data="consult_for:self")]]
    for member_id, name, relation in members:
        rows.append([InlineKeyboardButton(
            text=f"👥 {name} ({relation})",
            callback_data=f"consult_for:member:{member_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)
