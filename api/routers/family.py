"""
Family profiles — health profiles for relatives, so consultations can be run
on their behalf instead of the account owner's own profile.

Unlike the bot's step-by-step questionnaire, the profile is submitted as one
PUT (same pattern as api/routers/profile.py's /me/profile).
"""
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.schemas import (
    FamilyMemberCreate, FamilyMemberOut, FamilyMemberProfileIn, FamilyMemberSummary,
)
from database.db import (
    create_family_member, delete_family_member, get_family_member,
    get_family_members, set_family_member_field,
)

router = APIRouter(prefix="/family", tags=["family"])


async def _own_member(member_id: int, user_id: int) -> dict:
    member = await get_family_member(member_id)
    if not member or member["owner_user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Family member not found")
    return member


def _to_out(member: dict) -> FamilyMemberOut:
    return FamilyMemberOut(**{**member, "onboarding_done": bool(member["onboarding_done"])})


@router.get("", response_model=list[FamilyMemberSummary])
async def list_family(user_id: int = Depends(get_current_user)) -> list[FamilyMemberSummary]:
    rows = await get_family_members(user_id)
    return [FamilyMemberSummary(id=r[0], name=r[1], relation=r[2]) for r in rows]


@router.post("", response_model=FamilyMemberSummary)
async def add_family_member(
    body: FamilyMemberCreate, user_id: int = Depends(get_current_user)
) -> FamilyMemberSummary:
    member_id = await create_family_member(user_id, body.name, body.relation)
    return FamilyMemberSummary(id=member_id, name=body.name, relation=body.relation)


@router.get("/{member_id}", response_model=FamilyMemberOut)
async def get_family_member_profile(
    member_id: int, user_id: int = Depends(get_current_user)
) -> FamilyMemberOut:
    member = await _own_member(member_id, user_id)
    return _to_out(member)


@router.put("/{member_id}/profile", response_model=FamilyMemberOut)
async def put_family_member_profile(
    member_id: int, body: FamilyMemberProfileIn, user_id: int = Depends(get_current_user)
) -> FamilyMemberOut:
    await _own_member(member_id, user_id)

    for field, value in [
        ("gender", body.gender), ("age_range", body.age_range),
        ("chronic_diseases", body.chronic_diseases), ("allergies", body.allergies),
        ("medications", body.medications), ("pregnancy", body.pregnancy),
        ("past_surgeries", body.past_surgeries), ("hereditary_diseases", body.hereditary_diseases),
        ("smoking", body.smoking), ("alcohol", body.alcohol),
        ("physical_activity", body.physical_activity), ("height_weight", body.height_weight),
        ("onboarding_done", "1"),
    ]:
        await set_family_member_field(member_id, field, value)

    member = await get_family_member(member_id)
    return _to_out(member)


@router.delete("/{member_id}")
async def remove_family_member(
    member_id: int, user_id: int = Depends(get_current_user)
) -> dict:
    await _own_member(member_id, user_id)
    await delete_family_member(member_id)
    return {"status": "ok"}
