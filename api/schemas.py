from typing import Literal

from pydantic import BaseModel, Field

# HH:MM, 24h — the format the iOS app sends and the bot's reminder loop parses.
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
# YYYY-MM-DD shape only; resolve_client_date() does the real parsing/skew check.
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


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
    text: str = Field(min_length=1, max_length=4000)


class DoctorOut(BaseModel):
    specialty: str
    name: str
    url: str


class BadOut(BaseModel):
    key: str
    name: str
    url: str
    description: str
    # What the app needs to offer "start a course" right from the recommendation.
    course_days: int
    daily_doses: int
    default_times: list[str]


class MessageOut(BaseModel):
    type: str  # "question" | "recommendation" | "emergency"
    text: str
    doctor: DoctorOut | None = None
    bad: BadOut | None = None
    is_lifestyle: bool = False
    session_status: str  # "active" | "completed"
    # Mirrors what handlers/consultation.py's build_recommendation_message()
    # appends in the bot: a non-catalog supplement suggestion, the grounded
    # safety warnings for it/the catalog BAD, and the mandatory disclaimer.
    general_supplement: str | None = None
    safety_warnings: list[str] = []
    disclaimer: str | None = None


class TranscriptTurn(BaseModel):
    role: str
    text: str


class ConsultationTranscriptOut(BaseModel):
    session_id: int
    status: str
    turns: list[TranscriptTurn]


# ── BAD advisor ──────────────────────────────────────────────────────────────

class ClarifyOptionOut(BaseModel):
    key: str
    label: str


class ClarifyOut(BaseModel):
    question: str
    options: list[ClarifyOptionOut]


class BadGoalOut(BaseModel):
    key: str
    label: str
    description: str
    suggested: bool = False          # matches the user's profile — listed first, shown with a ⭐
    clarify: ClarifyOut | None = None


class GoalCheckRequest(BaseModel):
    goal_key: str
    clarify_option: str | None = None   # answer to the goal's ClarifyOut question, if it has one


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
    synergies: list[str] = []


class GeneralCardOut(BaseModel):
    """A supplement from the knowledge base that we don't sell: no dosage,
    course or buy link — just honest info and the option to track intake."""
    key: str
    label: str
    goal: str
    notes: str | None = None


class GoalCheckResponse(BaseModel):
    goal_label: str
    warnings: list[str]              # non-blocking cautions — the card is still shown
    blocked_notes: list[str] = []    # contraindications — those products are NOT in bads/general_supplements
    extra_note: str | None = None
    lifestyle_tips: str
    bads: list[BadCardOut]
    general_supplements: list[GeneralCardOut] = []


# ── Tracker ──────────────────────────────────────────────────────────────────

class TrackerCreateRequest(BaseModel):
    # A catalog key (course length comes from the catalog), or — for a
    # supplement we don't sell — the user's own name for it, in which case
    # course_days is required.
    product_key: str = Field(min_length=1, max_length=100)
    course_days: int | None = Field(default=None, ge=1, le=365)
    reminder_time_1: str | None = Field(default=None, pattern=TIME_PATTERN)
    reminder_time_2: str | None = Field(default=None, pattern=TIME_PATTERN)
    date: str | None = Field(default=None, pattern=DATE_PATTERN)  # the user's local start day; server date if omitted


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


class TrackerHistoryOut(BaseModel):
    id: int
    product_key: str
    emoji: str
    full_name: str
    start_date: str
    course_days: int
    days_taken: int
    status: str  # "completed" | "stopped"


class IntakeRequest(BaseModel):
    status: Literal["taken", "skip"]
    slot: Literal["1", "2"]
    date: str | None = Field(default=None, pattern=DATE_PATTERN)  # the user's local day; server date if omitted


class OkOut(BaseModel):
    status: Literal["ok"] = "ok"


class IntakeOut(BaseModel):
    status: str
    days_taken: int
    course_days: int
    course_completed: bool  # this intake was the one that finished the course


# ── Diary ────────────────────────────────────────────────────────────────────

class DiaryEntryOut(BaseModel):
    entry_date: str
    sleep_quality: int
    energy_level: int
    stress_level: int
    bads_taken: bool
    notes: str | None = None


class DiaryEntryIn(BaseModel):
    sleep_quality: int = Field(ge=1, le=5)
    energy_level: int = Field(ge=1, le=5)
    stress_level: int = Field(ge=1, le=5)
    bads_taken: bool
    notes: str | None = Field(default=None, max_length=2000)
    date: str | None = Field(default=None, pattern=DATE_PATTERN)  # the user's local day; server date if omitted


class DiaryCourseOut(BaseModel):
    product_key: str
    full_name: str
    start_date: str
    status: str
    ended_at: str | None = None


class DiaryChangeOut(BaseModel):
    metric: str  # "sleep" | "energy" | "stress"
    before: float
    after: float


class DiaryCorrelationOut(BaseModel):
    product_key: str
    full_name: str
    changes: list[DiaryChangeOut]


class DiaryInsightsOut(BaseModel):
    courses: list[DiaryCourseOut]
    correlations: list[DiaryCorrelationOut]


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


# ── Sources ──────────────────────────────────────────────────────────────────

class SourceOut(BaseModel):
    title: str
    url: str | None = None


class SourceGroupOut(BaseModel):
    names: list[str]          # the products/supplements these citations back
    sources: list[SourceOut]


class SourcesOut(BaseModel):
    catalog: list[SourceGroupOut]   # products we sell
    other: list[SourceGroupOut]     # supplements we only give information about
