from fastapi import APIRouter, Depends

from assistant.auth import customer_hash, get_current_user
from assistant.dependencies import get_action_service
from assistant.schemas import ActivityOut, ProposalOut
from assistant.services.action_service import ActionService

router = APIRouter(tags=["actions"])


# The proposals waiting for the customer's decision (the approval sheet)
@router.get("/actions", response_model=list[ProposalOut])
def open_proposals(
    user: dict = Depends(get_current_user),
    service: ActionService = Depends(get_action_service),
):
    return [ProposalOut.from_action(a) for a in service.list_open_proposals(customer_hash(user["id"]))]


# "async def" because approving waits for ledger-core. Returns 200 even when the change could not
# run: the proposal's status ("failed") and result carry the reason, so the app can show it.
@router.post("/actions/{action_id}/approve", response_model=ProposalOut)
async def approve(
    action_id: str,
    user: dict = Depends(get_current_user),
    service: ActionService = Depends(get_action_service),
):
    return ProposalOut.from_action(await service.approve_proposal(action_id, customer_hash(user["id"])))


@router.post("/actions/{action_id}/reject", response_model=ProposalOut)
def reject(
    action_id: str,
    user: dict = Depends(get_current_user),
    service: ActionService = Depends(get_action_service),
):
    return ProposalOut.from_action(service.reject_proposal(action_id, customer_hash(user["id"])))


# The audit log, newest first (the Activity screen)
@router.get("/activity", response_model=list[ActivityOut])
def activity(
    user: dict = Depends(get_current_user),
    service: ActionService = Depends(get_action_service),
):
    return [ActivityOut.from_entry(e) for e in service.list_activity(customer_hash(user["id"]))]
