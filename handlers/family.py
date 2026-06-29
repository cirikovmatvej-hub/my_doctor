"""Family profiles — add/view/edit/delete health profiles for family members."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database.db import (
    create_family_member, delete_family_member, get_family_member,
    get_family_members, get_or_create_user, set_family_member_field,
)
from keyboards.keyboards import (
    activity_keyboard, age_keyboard, alcohol_keyboard,
    family_delete_keyboard, family_list_keyboard, family_member_keyboard,
    gender_keyboard, main_menu, pregnancy_keyboard, relation_keyboard,
    skip_keyboard, smoking_keyboard,
)

router = Router()

# ── Display helpers ────────────────────────────────────────────────────────

_GENDER    = {"male": "мужской", "female": "женский"}
_AGE       = {"under_18": "до 18", "18_30": "18–30", "31_45": "31–45", "46_60": "46–60", "60_plus": "60+"}
_SMOKING   = {"never": "не курит", "former": "бросил(а)", "light": "изредка", "heavy": "регулярно"}
_ALCOHOL   = {"never": "не употребляет", "rarely": "редко", "moderate": "умеренно", "frequent": "часто"}
_ACTIVITY  = {"sedentary": "сидячий", "light": "лёгкая", "moderate": "умеренная", "high": "высокая"}
_PREGNANCY = {"pregnant": "беременность", "lactating": "лактация", "no": "нет"}


def _v(val: str | None) -> str:
    v = (val or "").strip()
    return v if v and v not in ("нет", "не указано") else "—"


def _member_summary(m: dict) -> str:
    lines = [
        f"👤 Пол: {_GENDER.get(m.get('gender', ''), '—')}",
        f"🎂 Возраст: {_AGE.get(m.get('age_range', ''), '—')}",
        f"🏥 Хронические болезни: {_v(m.get('chronic_diseases'))}",
        f"⚠️ Аллергии: {_v(m.get('allergies'))}",
        f"💊 Постоянные лекарства: {_v(m.get('medications'))}",
    ]
    if m.get("gender") == "female":
        lines.append(f"🤰 Беременность/лактация: {_PREGNANCY.get(m.get('pregnancy') or '', '—')}")
    lines += [
        f"🔪 Операции/травмы: {_v(m.get('past_surgeries'))}",
        f"🧬 Наследственность: {_v(m.get('hereditary_diseases'))}",
        f"🚬 Курение: {_SMOKING.get(m.get('smoking') or '', '—')}",
        f"🍷 Алкоголь: {_ALCOHOL.get(m.get('alcohol') or '', '—')}",
        f"🏃 Активность: {_ACTIVITY.get(m.get('physical_activity') or '', '—')}",
        f"📏 Рост/вес: {_v(m.get('height_weight'))}",
    ]
    return "\n".join(lines)


# ── States ─────────────────────────────────────────────────────────────────

class FamilyState(StatesGroup):
    entering_name       = State()
    selecting_relation  = State()
    waiting_gender      = State()
    waiting_age         = State()
    waiting_chronic     = State()
    waiting_allergies   = State()
    waiting_medications = State()
    waiting_pregnancy   = State()
    waiting_surgeries   = State()
    waiting_hereditary  = State()
    waiting_smoking     = State()
    waiting_alcohol     = State()
    waiting_activity    = State()
    waiting_height      = State()


# ── Menu: Семья ────────────────────────────────────────────────────────────

@router.message(F.text == "👨‍👩‍👧 Семья")
async def cmd_family(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
    members = await get_family_members(user_id)

    if not members:
        text = (
            "👨‍👩‍👧 <b>Семья</b>\n\n"
            "Добавьте профили близких — и бот сможет консультировать с учётом "
            "их анкеты здоровья.\n\n"
            "<i>Например: «У Вани болит голова» — бот будет ориентироваться "
            "на профиль Вани, а не ваш.</i>"
        )
    else:
        names = ", ".join(name for _, name, _ in members)
        text = f"👨‍👩‍👧 <b>Семья</b>\n\nПрофили: {names}"

    await message.answer(text, parse_mode="HTML", reply_markup=family_list_keyboard(members))


# ── View member ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("family:view:"))
async def cb_family_view(call: CallbackQuery) -> None:
    member_id = int(call.data.split(":")[2])
    member = await get_family_member(member_id)
    if not member:
        await call.answer("Профиль не найден", show_alert=True)
        return
    summary = _member_summary(member)
    await call.message.edit_text(
        f"👤 <b>{member['name']}</b> ({member['relation']})\n\n{summary}",
        parse_mode="HTML",
        reply_markup=family_member_keyboard(member_id),
    )
    await call.answer()


@router.callback_query(F.data == "family:list")
async def cb_family_list(call: CallbackQuery) -> None:
    user_id = await get_or_create_user(call.from_user.id, call.from_user.username)
    members = await get_family_members(user_id)
    text = (
        f"👨‍👩‍👧 <b>Семья</b>\n\nПрофили: {', '.join(n for _, n, _ in members)}"
        if members else
        "👨‍👩‍👧 <b>Семья</b>\n\nПока нет добавленных профилей."
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=family_list_keyboard(members))
    await call.answer()


# ── Delete member ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("family:delete:") & ~F.data.contains("confirm"))
async def cb_family_delete(call: CallbackQuery) -> None:
    member_id = int(call.data.split(":")[2])
    member = await get_family_member(member_id)
    if not member:
        await call.answer("Профиль не найден", show_alert=True)
        return
    await call.message.edit_text(
        f"Удалить профиль <b>{member['name']}</b>? Это действие нельзя отменить.",
        parse_mode="HTML",
        reply_markup=family_delete_keyboard(member_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("family:delete_confirm:"))
async def cb_family_delete_confirm(call: CallbackQuery) -> None:
    member_id = int(call.data.split(":")[2])
    member = await get_family_member(member_id)
    name = member["name"] if member else "профиль"
    await delete_family_member(member_id)

    user_id = await get_or_create_user(call.from_user.id, call.from_user.username)
    members = await get_family_members(user_id)
    await call.message.edit_text(
        f"✅ Профиль <b>{name}</b> удалён.",
        parse_mode="HTML",
        reply_markup=family_list_keyboard(members),
    )
    await call.answer()


# ── Add member: name + relation ────────────────────────────────────────────

@router.callback_query(F.data == "family:add")
async def cb_family_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(FamilyState.entering_name)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "Как зовут этого человека?\n<i>Например: Ваня, Мама, Бабушка</i>",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(FamilyState.entering_name)
async def msg_family_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not (1 <= len(name) <= 50):
        await message.answer("Имя должно быть от 1 до 50 символов.")
        return
    await state.update_data(member_name=name)
    await state.set_state(FamilyState.selecting_relation)
    await message.answer(
        f"Кем вам приходится <b>{name}</b>?",
        parse_mode="HTML",
        reply_markup=relation_keyboard(),
    )


@router.callback_query(FamilyState.selecting_relation, F.data.startswith("relation:"))
async def cb_family_relation(call: CallbackQuery, state: FSMContext) -> None:
    relation = call.data.split(":")[1]
    data = await state.get_data()
    name = data["member_name"]

    user_id = await get_or_create_user(call.from_user.id, call.from_user.username)
    member_id = await create_family_member(user_id, name, relation)
    await state.update_data(member_id=member_id)

    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FamilyState.waiting_gender)
    await call.message.answer(
        f"Заполним анкету здоровья для <b>{name}</b>.\n"
        "Это поможет боту давать точные и безопасные советы 👇\n\n"
        "Пол:",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
    )
    await call.answer()


# ── Edit member (restart questionnaire) ───────────────────────────────────

@router.callback_query(F.data.startswith("family:edit:"))
async def cb_family_edit(call: CallbackQuery, state: FSMContext) -> None:
    member_id = int(call.data.split(":")[2])
    member = await get_family_member(member_id)
    if not member:
        await call.answer("Профиль не найден", show_alert=True)
        return
    await state.clear()
    await state.update_data(
        member_id=member_id,
        member_name=member["name"],
        gender=member.get("gender"),
    )
    await state.set_state(FamilyState.waiting_gender)
    await call.message.answer(
        f"Обновляем анкету для <b>{member['name']}</b>. Пол:",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
    )
    await call.answer()


# ── Health questionnaire ───────────────────────────────────────────────────

@router.callback_query(FamilyState.waiting_gender, F.data.startswith("gender:"))
async def fam_gender(call: CallbackQuery, state: FSMContext) -> None:
    gender = call.data.split(":")[1]
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "gender", gender)
    await state.update_data(gender=gender)
    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FamilyState.waiting_age)
    await call.message.answer("Возраст:", reply_markup=age_keyboard())
    await call.answer()


@router.callback_query(FamilyState.waiting_age, F.data.startswith("age:"))
async def fam_age(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "age_range", call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FamilyState.waiting_chronic)
    await call.message.answer(
        "Есть ли хронические заболевания?\n<i>Например: диабет, гипертония, астма</i>",
        parse_mode="HTML",
        reply_markup=skip_keyboard("fam:skip:chronic"),
    )
    await call.answer()


@router.message(FamilyState.waiting_chronic)
async def fam_chronic_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "chronic_diseases", message.text.strip())
    await _ask_allergies(message, state)


@router.callback_query(FamilyState.waiting_chronic, F.data == "fam:skip:chronic")
async def fam_chronic_skip(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "chronic_diseases", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_allergies(call.message, state)
    await call.answer()


async def _ask_allergies(msg: Message, state: FSMContext) -> None:
    await state.set_state(FamilyState.waiting_allergies)
    await msg.answer(
        "Есть ли аллергии?\n<i>На лекарства, еду, пыльцу и т.д.</i>",
        parse_mode="HTML",
        reply_markup=skip_keyboard("fam:skip:allergies"),
    )


@router.message(FamilyState.waiting_allergies)
async def fam_allergies_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "allergies", message.text.strip())
    await _ask_medications(message, state)


@router.callback_query(FamilyState.waiting_allergies, F.data == "fam:skip:allergies")
async def fam_allergies_skip(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "allergies", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_medications(call.message, state)
    await call.answer()


async def _ask_medications(msg: Message, state: FSMContext) -> None:
    await state.set_state(FamilyState.waiting_medications)
    await msg.answer(
        "Принимает ли постоянные лекарства?\n<i>Название и дозировка, если знаете</i>",
        parse_mode="HTML",
        reply_markup=skip_keyboard("fam:skip:medications"),
    )


@router.message(FamilyState.waiting_medications)
async def fam_medications_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "medications", message.text.strip())
    await _after_medications(message, state)


@router.callback_query(FamilyState.waiting_medications, F.data == "fam:skip:medications")
async def fam_medications_skip(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "medications", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _after_medications(call.message, state)
    await call.answer()


async def _after_medications(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("gender") == "female":
        await state.set_state(FamilyState.waiting_pregnancy)
        await msg.answer("Беременность или лактация?", reply_markup=pregnancy_keyboard())
    else:
        await set_family_member_field(data["member_id"], "pregnancy", "нет")
        await _ask_surgeries(msg, state)


@router.callback_query(FamilyState.waiting_pregnancy, F.data.startswith("pregnancy:"))
async def fam_pregnancy(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "pregnancy", call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_surgeries(call.message, state)
    await call.answer()


async def _ask_surgeries(msg: Message, state: FSMContext) -> None:
    await state.set_state(FamilyState.waiting_surgeries)
    await msg.answer(
        "Были ли операции или серьёзные травмы?",
        reply_markup=skip_keyboard("fam:skip:surgeries"),
    )


@router.message(FamilyState.waiting_surgeries)
async def fam_surgeries_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "past_surgeries", message.text.strip())
    await _ask_hereditary(message, state)


@router.callback_query(FamilyState.waiting_surgeries, F.data == "fam:skip:surgeries")
async def fam_surgeries_skip(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "past_surgeries", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_hereditary(call.message, state)
    await call.answer()


async def _ask_hereditary(msg: Message, state: FSMContext) -> None:
    await state.set_state(FamilyState.waiting_hereditary)
    await msg.answer(
        "Есть ли наследственные заболевания в семье?\n"
        "<i>Диабет, онкология, сердечно-сосудистые и т.д.</i>",
        parse_mode="HTML",
        reply_markup=skip_keyboard("fam:skip:hereditary"),
    )


@router.message(FamilyState.waiting_hereditary)
async def fam_hereditary_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "hereditary_diseases", message.text.strip())
    await _ask_smoking(message, state)


@router.callback_query(FamilyState.waiting_hereditary, F.data == "fam:skip:hereditary")
async def fam_hereditary_skip(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "hereditary_diseases", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_smoking(call.message, state)
    await call.answer()


async def _ask_smoking(msg: Message, state: FSMContext) -> None:
    await state.set_state(FamilyState.waiting_smoking)
    await msg.answer("Курение:", reply_markup=smoking_keyboard())


@router.callback_query(FamilyState.waiting_smoking, F.data.startswith("smoking:"))
async def fam_smoking(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "smoking", call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FamilyState.waiting_alcohol)
    await call.message.answer("Алкоголь:", reply_markup=alcohol_keyboard())
    await call.answer()


@router.callback_query(FamilyState.waiting_alcohol, F.data.startswith("alcohol:"))
async def fam_alcohol(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "alcohol", call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FamilyState.waiting_activity)
    await call.message.answer("Физическая активность:", reply_markup=activity_keyboard())
    await call.answer()


@router.callback_query(FamilyState.waiting_activity, F.data.startswith("activity:"))
async def fam_activity(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "physical_activity", call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(FamilyState.waiting_height)
    await call.message.answer(
        "Рост и вес?\n<i>Например: 175 см / 70 кг</i>",
        parse_mode="HTML",
        reply_markup=skip_keyboard("fam:skip:height"),
    )
    await call.answer()


@router.message(FamilyState.waiting_height)
async def fam_height_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "height_weight", message.text.strip())
    await _finish_member(message, state)


@router.callback_query(FamilyState.waiting_height, F.data == "fam:skip:height")
async def fam_height_skip(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await set_family_member_field(data["member_id"], "height_weight", "не указано")
    await call.message.edit_reply_markup(reply_markup=None)
    await _finish_member(call.message, state)
    await call.answer()


async def _finish_member(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    member_id = data["member_id"]
    name = data["member_name"]
    await set_family_member_field(member_id, "onboarding_done", "1")

    member = await get_family_member(member_id)
    summary = _member_summary(member)
    await state.clear()

    await msg.answer(
        f"✅ Профиль <b>{name}</b> сохранён!\n\n{summary}\n\n"
        "Теперь при нажатии «🩺 Анализ симптомов» бот спросит, "
        "для кого консультация — для вас или для кого-то из семьи.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
