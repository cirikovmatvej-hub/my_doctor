import aiosqlite
from datetime import datetime, timedelta
from config import DATABASE_PATH, FOLLOW_UP_HOURS

# ── Init ───────────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id          INTEGER UNIQUE NOT NULL,
                username             TEXT,
                gender               TEXT,
                age_range            TEXT,
                chronic_diseases     TEXT,
                allergies            TEXT,
                medications          TEXT,
                pregnancy            TEXT,
                past_surgeries       TEXT,
                hereditary_diseases  TEXT,
                smoking              TEXT,
                alcohol              TEXT,
                physical_activity    TEXT,
                height_weight        TEXT,
                onboarding_done      INTEGER DEFAULT 0,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL,
                complaint        TEXT,
                summary          TEXT,
                status           TEXT DEFAULT 'active',
                follow_up_at     TIMESTAMP,
                follow_up_sent   INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS product_tracking (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL,
                product_key          TEXT NOT NULL,
                start_date           TEXT NOT NULL,
                course_days          INTEGER DEFAULT 30,
                morning_reminder     INTEGER DEFAULT 0,
                evening_reminder     INTEGER DEFAULT 0,
                last_morning_date    TEXT,
                last_evening_date    TEXT,
                reminder_time_1      TEXT,
                reminder_time_2      TEXT,
                last_reminder_1_date TEXT,
                last_reminder_2_date TEXT,
                end_reminder_sent    INTEGER DEFAULT 0,
                status               TEXT DEFAULT 'active',
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS intake_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id INTEGER NOT NULL,
                log_date    TEXT NOT NULL,
                time_of_day TEXT NOT NULL,
                status      TEXT NOT NULL,
                logged_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tracking_id) REFERENCES product_tracking(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appointment_followups (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER NOT NULL,
                doctor_specialty  TEXT NOT NULL,
                status            TEXT DEFAULT 'pending',
                ask_at            TIMESTAMP NOT NULL,
                ask_sent          INTEGER DEFAULT 0,
                not_booked_reason TEXT,
                reminder_at       TIMESTAMP,
                reminder_sent     INTEGER DEFAULT 0,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS family_members (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id        INTEGER NOT NULL,
                name                 TEXT NOT NULL,
                relation             TEXT,
                gender               TEXT,
                age_range            TEXT,
                chronic_diseases     TEXT,
                allergies            TEXT,
                medications          TEXT,
                pregnancy            TEXT,
                past_surgeries       TEXT,
                hereditary_diseases  TEXT,
                smoking              TEXT,
                alcohol              TEXT,
                physical_activity    TEXT,
                height_weight        TEXT,
                onboarding_done      INTEGER DEFAULT 0,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_user_id) REFERENCES users(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS diary_entries (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                entry_date    TEXT NOT NULL,
                sleep_quality INTEGER,
                energy_level  INTEGER,
                stress_level  INTEGER,
                bads_taken    INTEGER,
                notes         TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Migrations for existing DBs
        _migrations = [
            ("users",            "chronic_diseases",    "TEXT"),
            ("users",            "allergies",           "TEXT"),
            ("users",            "medications",         "TEXT"),
            ("users",            "pregnancy",           "TEXT"),
            ("users",            "past_surgeries",      "TEXT"),
            ("users",            "hereditary_diseases", "TEXT"),
            ("users",            "smoking",             "TEXT"),
            ("users",            "alcohol",             "TEXT"),
            ("users",            "physical_activity",   "TEXT"),
            ("users",            "height_weight",       "TEXT"),
            ("users",            "onboarding_done",     "INTEGER DEFAULT 0"),
            ("users",            "utc_offset",          "INTEGER DEFAULT 3"),
            ("sessions",         "follow_up_at",        "TIMESTAMP"),
            ("sessions",         "follow_up_sent",      "INTEGER DEFAULT 0"),
            ("product_tracking", "reminder_time_1",      "TEXT"),
            ("product_tracking", "reminder_time_2",      "TEXT"),
            ("product_tracking", "last_reminder_1_date", "TEXT"),
            ("product_tracking", "last_reminder_2_date", "TEXT"),
        ]
        for table, col, coltype in _migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except Exception:
                pass

        await db.commit()


# ── Users ──────────────────────────────────────────────────────────────────

async def get_or_create_user(telegram_id: int, username: str | None = None) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
        if row:
            return row[0]
        await db.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
        await db.commit()
        async with db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
        return row[0]


async def get_user_profile(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id, gender, age_range, chronic_diseases, allergies, medications, pregnancy, "
            "past_surgeries, hereditary_diseases, smoking, alcohol, physical_activity, "
            "height_weight, onboarding_done "
            "FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0], "gender": row[1], "age_range": row[2],
        "chronic_diseases": row[3], "allergies": row[4],
        "medications": row[5], "pregnancy": row[6],
        "past_surgeries": row[7], "hereditary_diseases": row[8],
        "smoking": row[9], "alcohol": row[10],
        "physical_activity": row[11], "height_weight": row[12],
        "onboarding_done": row[13],
    }


async def is_profile_complete(telegram_id: int) -> bool:
    profile = await get_user_profile(telegram_id)
    if not profile:
        return False
    return bool(profile.get("onboarding_done"))


async def set_health_field(telegram_id: int, field: str, value: str) -> None:
    """Save a single health profile field — used for incremental questionnaire saving."""
    allowed = {
        "chronic_diseases", "allergies", "medications", "pregnancy",
        "past_surgeries", "hereditary_diseases", "smoking", "alcohol",
        "physical_activity", "height_weight", "onboarding_done",
    }
    if field not in allowed:
        raise ValueError(f"Unknown health field: {field}")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id)
        )
        await db.commit()


async def update_user_profile(telegram_id: int, gender: str, age_range: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET gender = ?, age_range = ? WHERE telegram_id = ?",
            (gender, age_range, telegram_id),
        )
        await db.commit()


async def update_user_health_profile(
    telegram_id: int,
    chronic_diseases: str,
    allergies: str,
    medications: str,
    pregnancy: str,
    past_surgeries: str = "нет",
    hereditary_diseases: str = "нет",
    smoking: str = "не курю",
    alcohol: str = "не пью",
    physical_activity: str = "умеренная",
    height_weight: str = "не указано",
) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET chronic_diseases=?, allergies=?, medications=?, pregnancy=?, "
            "past_surgeries=?, hereditary_diseases=?, smoking=?, alcohol=?, "
            "physical_activity=?, height_weight=?, onboarding_done=1 "
            "WHERE telegram_id=?",
            (chronic_diseases, allergies, medications, pregnancy,
             past_surgeries, hereditary_diseases, smoking, alcohol,
             physical_activity, height_weight, telegram_id),
        )
        await db.commit()


# ── Sessions ───────────────────────────────────────────────────────────────

async def create_session(user_id: int, complaint: str) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("INSERT INTO sessions (user_id, complaint) VALUES (?, ?)", (user_id, complaint))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            row = await cur.fetchone()
        return row[0]


async def update_session_summary(session_id: int, summary: str) -> None:
    follow_up_at = datetime.now() + timedelta(hours=FOLLOW_UP_HOURS)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE sessions SET summary=?, status='completed', follow_up_at=? WHERE id=?",
            (summary, follow_up_at.isoformat(), session_id),
        )
        await db.commit()


async def add_message(session_id: int, role: str, content: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        await db.commit()


async def get_user_sessions(user_id: int, limit: int = 5) -> list:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id, complaint, summary, created_at FROM sessions "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)
        ) as cur:
            return await cur.fetchall()


# ── Follow-up ──────────────────────────────────────────────────────────────

async def get_pending_followups() -> list:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT s.id, u.telegram_id, s.complaint, s.created_at "
            "FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.status='completed' AND s.follow_up_sent=0 "
            "AND s.follow_up_at IS NOT NULL AND s.follow_up_at<=?", (now,)
        ) as cur:
            return await cur.fetchall()


async def mark_followup_sent(session_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE sessions SET follow_up_sent=1 WHERE id=?", (session_id,))
        await db.commit()


# ── Timezone ───────────────────────────────────────────────────────────────

async def set_utc_offset(telegram_id: int, offset: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET utc_offset=? WHERE telegram_id=?", (offset, telegram_id))
        await db.commit()


async def get_utc_offset(telegram_id: int) -> int | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT utc_offset FROM users WHERE telegram_id=?", (telegram_id,)) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


# ── Product tracking ───────────────────────────────────────────────────────

async def create_tracking(
    user_id: int, product_key: str, course_days: int,
    reminder_time_1: str | None = None,
    reminder_time_2: str | None = None,
) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE product_tracking SET status='paused' "
            "WHERE user_id=? AND product_key=? AND status='active'",
            (user_id, product_key),
        )
        await db.execute(
            "INSERT INTO product_tracking "
            "(user_id, product_key, start_date, course_days, reminder_time_1, reminder_time_2) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, product_key, today, course_days, reminder_time_1, reminder_time_2),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            row = await cur.fetchone()
        return row[0]


async def get_active_trackings(user_id: int) -> list:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id, product_key, start_date, course_days, reminder_time_1, reminder_time_2 "
            "FROM product_tracking WHERE user_id=? AND status='active' ORDER BY created_at DESC",
            (user_id,)
        ) as cur:
            return await cur.fetchall()


async def get_days_taken(tracking_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT log_date) FROM intake_logs "
            "WHERE tracking_id=? AND status='taken'", (tracking_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


async def log_intake(tracking_id: int, log_date: str, time_of_day: str, status: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO intake_logs (tracking_id, log_date, time_of_day, status) "
            "VALUES (?, ?, ?, ?)",
            (tracking_id, log_date, time_of_day, status),
        )
        await db.commit()


async def get_due_reminders(now_utc: datetime) -> list:
    """Return list of (tracking_id, telegram_id, product_key, course_days, slot) due right now."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT pt.id, u.telegram_id, u.utc_offset, pt.product_key, pt.course_days, "
            "pt.reminder_time_1, pt.reminder_time_2, pt.last_reminder_1_date, pt.last_reminder_2_date "
            "FROM product_tracking pt JOIN users u ON u.id=pt.user_id "
            "WHERE pt.status='active'"
        ) as cur:
            rows = await cur.fetchall()

    due = []
    for row in rows:
        (tracking_id, telegram_id, utc_offset, product_key, course_days,
         rt1, rt2, last1, last2) = row

        offset = utc_offset if utc_offset is not None else 3
        user_local = now_utc + timedelta(hours=offset)
        user_date  = user_local.strftime("%Y-%m-%d")
        user_min   = user_local.hour * 60 + user_local.minute

        def _is_due(rt: str | None, last_date: str | None) -> bool:
            if not rt:
                return False
            if last_date == user_date:
                return False
            try:
                hh, mm = map(int, rt.split(":"))
            except ValueError:
                return False
            return abs(user_min - (hh * 60 + mm)) < 5

        if _is_due(rt1, last1):
            due.append((tracking_id, telegram_id, product_key, course_days, "1", user_date))
        if _is_due(rt2, last2):
            due.append((tracking_id, telegram_id, product_key, course_days, "2", user_date))

    return due


async def mark_reminder_sent(tracking_id: int, slot: str, user_date: str) -> None:
    """slot: '1' or '2'; user_date is the user's local date (YYYY-MM-DD)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        col = f"last_reminder_{slot}_date"
        await db.execute(f"UPDATE product_tracking SET {col}=? WHERE id=?", (user_date, tracking_id))
        await db.commit()


async def get_near_end_courses() -> list:
    """Return active courses where days_taken >= course_days-5 and end reminder not yet sent."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT pt.id, u.telegram_id, pt.product_key, pt.course_days "
            "FROM product_tracking pt JOIN users u ON u.id=pt.user_id "
            "WHERE pt.status='active' AND pt.end_reminder_sent=0"
        ) as cur:
            rows = await cur.fetchall()

    result = []
    for tracking_id, telegram_id, product_key, course_days in rows:
        days = await get_days_taken(tracking_id)
        if days >= course_days - 5:
            result.append((tracking_id, telegram_id, product_key, days, course_days))
    return result


async def mark_end_reminder_sent(tracking_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE product_tracking SET end_reminder_sent=1 WHERE id=?", (tracking_id,))
        await db.commit()


# ── Appointment follow-ups ──────────────────────────────────────────────────

async def create_appointment_followup(user_id: int, doctor_specialty: str, ask_at: datetime) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO appointment_followups (user_id, doctor_specialty, ask_at) VALUES (?, ?, ?)",
            (user_id, doctor_specialty, ask_at.isoformat()),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            row = await cur.fetchone()
        return row[0]


async def get_due_appointment_asks(now: datetime) -> list:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT af.id, u.telegram_id, af.doctor_specialty "
            "FROM appointment_followups af JOIN users u ON u.id=af.user_id "
            "WHERE af.ask_sent=0 AND af.ask_at<=?",
            (now.isoformat(),),
        ) as cur:
            return await cur.fetchall()


async def mark_appointment_ask_sent(followup_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appointment_followups SET ask_sent=1 WHERE id=?", (followup_id,))
        await db.commit()


async def set_appointment_status(followup_id: int, status: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appointment_followups SET status=? WHERE id=?", (status, followup_id))
        await db.commit()


async def set_appointment_reason(followup_id: int, reason: str) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE appointment_followups SET not_booked_reason=? WHERE id=?", (reason, followup_id)
        )
        await db.commit()


async def set_appointment_reminder(followup_id: int, reminder_at: datetime | None) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE appointment_followups SET reminder_at=? WHERE id=?",
            (reminder_at.isoformat() if reminder_at else None, followup_id),
        )
        await db.commit()


async def get_due_appointment_reminders(now: datetime) -> list:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT af.id, u.telegram_id, af.doctor_specialty "
            "FROM appointment_followups af JOIN users u ON u.id=af.user_id "
            "WHERE af.reminder_sent=0 AND af.reminder_at IS NOT NULL AND af.reminder_at<=?",
            (now.isoformat(),),
        ) as cur:
            return await cur.fetchall()


async def mark_appointment_reminder_sent(followup_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE appointment_followups SET reminder_sent=1 WHERE id=?", (followup_id,))
        await db.commit()


# ── Family members ────────────────────────────────────────────────────────

async def create_family_member(owner_user_id: int, name: str, relation: str) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO family_members (owner_user_id, name, relation) VALUES (?, ?, ?)",
            (owner_user_id, name, relation),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            row = await cur.fetchone()
        return row[0]


async def get_family_members(owner_user_id: int) -> list:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id, name, relation FROM family_members WHERE owner_user_id=? ORDER BY created_at",
            (owner_user_id,),
        ) as cur:
            return await cur.fetchall()


async def get_family_member(member_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT id, owner_user_id, name, relation, gender, age_range, "
            "chronic_diseases, allergies, medications, pregnancy, past_surgeries, "
            "hereditary_diseases, smoking, alcohol, physical_activity, height_weight, onboarding_done "
            "FROM family_members WHERE id=?",
            (member_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "owner_user_id": row[1], "name": row[2], "relation": row[3],
        "gender": row[4], "age_range": row[5], "chronic_diseases": row[6],
        "allergies": row[7], "medications": row[8], "pregnancy": row[9],
        "past_surgeries": row[10], "hereditary_diseases": row[11],
        "smoking": row[12], "alcohol": row[13], "physical_activity": row[14],
        "height_weight": row[15], "onboarding_done": row[16],
    }


async def set_family_member_field(member_id: int, field: str, value: str) -> None:
    allowed = {
        "gender", "age_range", "chronic_diseases", "allergies", "medications",
        "pregnancy", "past_surgeries", "hereditary_diseases", "smoking",
        "alcohol", "physical_activity", "height_weight", "onboarding_done",
    }
    if field not in allowed:
        raise ValueError(f"Unknown family member field: {field}")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            f"UPDATE family_members SET {field}=? WHERE id=?", (value, member_id)
        )
        await db.commit()


async def delete_family_member(member_id: int) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM family_members WHERE id=?", (member_id,))
        await db.commit()


# ── Diary ──────────────────────────────────────────────────────────────────

async def save_diary_entry(
    user_id: int, entry_date: str,
    sleep_quality: int, energy_level: int, stress_level: int,
    bads_taken: int, notes: str | None,
) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO diary_entries "
            "(user_id, entry_date, sleep_quality, energy_level, stress_level, bads_taken, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, entry_date, sleep_quality, energy_level, stress_level, bads_taken, notes),
        )
        await db.commit()


async def get_diary_entries(user_id: int, limit: int = 7) -> list:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT entry_date, sleep_quality, energy_level, stress_level, bads_taken, notes "
            "FROM diary_entries WHERE user_id=? ORDER BY entry_date DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            return await cur.fetchall()
