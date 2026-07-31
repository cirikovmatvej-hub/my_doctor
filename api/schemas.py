from pydantic import BaseModel


# ── Auth ─────────────────────────────────────────────────────────────────────

class AppleAuthRequest(BaseModel):
    identity_token: str
    email: str | None = None
    full_name: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    onboarding_done: bool


# ── Profile ──────────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    user_id: int
    gender: str | None = None
    age_range: str | None = None
    chronic_diseases: str | None = None
    allergies: str | None = None
    medications: str | None = None
    pregnancy: str | None = None
    past_surgeries: str | None = None
    hereditary_diseases: str | None = None
    smoking: str | None = None
    alcohol: str | None = None
    physical_activity: str | None = None
    height_weight: str | None = None
    onboarding_done: bool


class ProfileIn(BaseModel):
    gender: str
    age_range: str
    chronic_diseases: str = "нет"
    allergies: str = "нет"
    medications: str = "нет"
    pregnancy: str = "нет"  # only meaningful when gender == "female"
    past_surgeries: str = "нет"
    hereditary_diseases: str = "нет"
    smoking: str = "не курю"
    alcohol: str = "не пью"
    physical_activity: str = "умеренная"
    height_weight: str = "не указано"


class ProfilePatch(BaseModel):
    field: str
    value: str


class UtcOffsetIn(BaseModel):
    offset: int


# ── Consultation ─────────────────────────────────────────────────────────────

class ConsultationCreate(BaseModel):
    family_member_id: int | None = None


class ConsultationOut(BaseModel):
    session_id: int
    opening_prompt: str


class MessageIn(BaseModel):
    text: str


class DoctorOut(BaseModel):
    specialty: str
    name: str
    url: str


class BadOut(BaseModel):
    key: str
    name: str
    url: str
    description: str


class MessageOut(BaseModel):
    type: str  # "question" | "recommendation" | "emergency"
    text: str
    doctor: DoctorOut | None = None
    bad: BadOut | None = None
    is_lifestyle: bool = False
    session_status: str  # "active" | "completed"


class TranscriptTurn(BaseModel):
    role: str
    text: str


class ConsultationTranscriptOut(BaseModel):
    session_id: int
    status: str
    turns: list[TranscriptTurn]


# ── BAD advisor ──────────────────────────────────────────────────────────────

class BadGoalOut(BaseModel):
    key: str
    label: str
    description: str


class GoalCheckRequest(BaseModel):
    goal_key: str


class BadCardOut(BaseModel):
    key: str
    emoji: str
    full_name: str
    goal: str
    course_days: int
    dosage: str
    daily_doses: int
    default_times: list[str]
    best_time: str
    with_food: bool
    notes: str
    url: str


class GoalCheckResponse(BaseModel):
    goal_label: str
    warnings: list[str]
    lifestyle_tips: str
    bads: list[BadCardOut]


# ── Tracker ──────────────────────────────────────────────────────────────────

class TrackerCreateRequest(BaseModel):
    product_key: str
    reminder_time_1: str | None = None
    reminder_time_2: str | None = None


class TrackerOut(BaseModel):
    id: int
    product_key: str
    emoji: str
    full_name: str
    start_date: str
    course_days: int
    days_taken: int
    reminder_time_1: str | None = None
    reminder_time_2: str | None = None


class IntakeRequest(BaseModel):
    status: str  # "taken" | "skip"
    slot: str    # "1" | "2"


# ── Diary ────────────────────────────────────────────────────────────────────

class DiaryEntryOut(BaseModel):
    entry_date: str
    sleep_quality: int
    energy_level: int
    stress_level: int
    bads_taken: bool
    notes: str | None = None


class DiaryEntryIn(BaseModel):
    sleep_quality: int
    energy_level: int
    stress_level: int
    bads_taken: bool
    notes: str | None = None


# ── Family ───────────────────────────────────────────────────────────────────

class FamilyMemberSummary(BaseModel):
    id: int
    name: str
    relation: str


class FamilyMemberCreate(BaseModel):
    name: str
    relation: str


class FamilyMemberProfileIn(BaseModel):
    gender: str
    age_range: str
    chronic_diseases: str = "нет"
    allergies: str = "нет"
    medications: str = "нет"
    pregnancy: str = "нет"
    past_surgeries: str = "нет"
    hereditary_diseases: str = "нет"
    smoking: str = "не курю"
    alcohol: str = "не пью"
    physical_activity: str = "умеренная"
    height_weight: str = "не указано"


class AppointmentCreate(BaseModel):
    doctor_specialty: str


class AppointmentOut(BaseModel):
    id: int
    doctor_specialty: str
    doctor_name: str
    status: str


class AppointmentStatusUpdate(BaseModel):
    status: str  # "booked" | "not_booked"
    reason: str | None = None


class HistoryEntryOut(BaseModel):
    session_id: int
    complaint: str | None = None
    summary: str | None = None
    created_at: str
    family_member_name: str | None = None


class FamilyMemberOut(BaseModel):
    id: int
    name: str
    relation: str
    gender: str | None = None
    age_range: str | None = None
    chronic_diseases: str | None = None
    allergies: str | None = None
    medications: str | None = None
    pregnancy: str | None = None
    past_surgeries: str | None = None
    hereditary_diseases: str | None = None
    smoking: str | None = None
    alcohol: str | None = None
    physical_activity: str | None = None
    height_weight: str | None = None
    onboarding_done: bool
