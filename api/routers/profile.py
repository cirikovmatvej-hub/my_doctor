from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.schemas import OkOut, ProfileIn, ProfileOut, ProfilePatch, UtcOffsetIn
from database.db import (
    delete_user_account, get_user_profile_by_id, get_utc_offset_by_id,
    set_health_field_by_id, set_utc_offset_by_id,
    update_user_health_profile_by_id,
)

router = APIRouter(tags=["profile"])

_PATCHABLE_FIELDS = {
    "gender", "age_range",
    "chronic_diseases", "allergies", "medications", "pregnancy",
    "past_surgeries", "hereditary_diseases", "smoking", "alcohol",
    "physical_activity", "height_weight",
}


def _to_profile_out(profile: dict) -> ProfileOut:
    return ProfileOut(**{**profile, "onboarding_done": bool(profile["onboarding_done"])})


@router.get("/me", response_model=ProfileOut)
async def get_me(user_id: int = Depends(get_current_user)) -> ProfileOut:
    profile = await get_user_profile_by_id(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _to_profile_out(profile)


@router.put("/me/profile", response_model=ProfileOut)
async def put_profile(body: ProfileIn, user_id: int = Depends(get_current_user)) -> ProfileOut:
    await set_health_field_by_id(user_id, "gender", body.gender)
    await set_health_field_by_id(user_id, "age_range", body.age_range)
    await update_user_health_profile_by_id(
        user_id,
        chronic_diseases=body.chronic_diseases,
        allergies=body.allergies,
        medications=body.medications,
        pregnancy=body.pregnancy,
        past_surgeries=body.past_surgeries,
        hereditary_diseases=body.hereditary_diseases,
        smoking=body.smoking,
        alcohol=body.alcohol,
        physical_activity=body.physical_activity,
        height_weight=body.height_weight,
    )
    profile = await get_user_profile_by_id(user_id)
    return _to_profile_out(profile)


@router.patch("/me/profile", response_model=ProfileOut)
async def patch_profile(body: ProfilePatch, user_id: int = Depends(get_current_user)) -> ProfileOut:
    if body.field not in _PATCHABLE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unknown field: {body.field}")
    await set_health_field_by_id(user_id, body.field, body.value)
    profile = await get_user_profile_by_id(user_id)
    return _to_profile_out(profile)


@router.get("/me/utc-offset")
async def get_my_utc_offset(user_id: int = Depends(get_current_user)) -> dict:
    offset = await get_utc_offset_by_id(user_id)
    return {"offset": offset}


@router.put("/me/utc-offset")
async def put_my_utc_offset(body: UtcOffsetIn, user_id: int = Depends(get_current_user)) -> dict:
    await set_utc_offset_by_id(user_id, body.offset)
    return {"offset": body.offset}


@router.delete("/me", response_model=OkOut)
async def delete_me(user_id: int = Depends(get_current_user)) -> OkOut:
    """Permanently delete the account and everything stored for it — profile,
    consultations, courses and intake history, diary, family profiles.
    Required by App Store review for any app that lets people create an account."""
    await delete_user_account(user_id)
    return OkOut()
