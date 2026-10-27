from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Account, Customer, Transfer
from ledger_core.schemas import RetryResponse, TransferDetail, TransferPublic

router = APIRouter(prefix="/me/transfers", tags=["transfers"])


# A helper used by two endpoints below. It finds ONE transfer, but only if it
# belongs to this customer. Anything else is a 404.
def get_my_transfer(transfer_id: int, customer: Customer, session: Session) -> Transfer:
    transfer = session.exec(
        select(Transfer)
        # A transfer has no customer_id, so we reach the owner through its account
        .join(Account, Transfer.account_id == Account.id)
        # Both conditions must hold: the right id AND the right owner
        .where(Transfer.id == transfer_id, Account.customer_id == customer.id)
    ).first()
    # 404, not 403, on purpose: "forbidden" would confirm that the transfer exists.
    # Someone else's transfer looks identical to one that doesn't exist.
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return transfer


# Full path: GET /me/transfers, optionally ?status=failed
@router.get("", response_model=list[TransferPublic])
def my_transfers(
    status: Literal["requested", "in_review", "in_progress", "completed", "failed", "all"] = "all",
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    query = (
        select(Transfer)
        .join(Account, Transfer.account_id == Account.id)
        # Only this customer's transfers
        .where(Account.customer_id == customer.id)
        # Newest first
        .order_by(Transfer.created_at.desc())
    )
    if status != "all":
        query = query.where(Transfer.status == status)
    # Return the rows directly. response_model=list[TransferPublic] picks out
    # the fields we want, so no manual conversion is needed.
    return session.exec(query).all()


# Full path: GET /me/transfers/{transfer_id}.
# {transfer_id} is a "path parameter": FastAPI passes it in as an int,
# and returns a 422 if it isn't a number.
@router.get("/{transfer_id}", response_model=TransferDetail)
def my_transfer(
    transfer_id: int,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    return get_my_transfer(transfer_id, customer, session)


# POST, because it changes something on the server
@router.post("/{transfer_id}/retry", response_model=RetryResponse)
def retry_transfer(
    transfer_id: int,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    # Same ownership check, so you can't retry someone else's transfer
    transfer = get_my_transfer(transfer_id, customer, session)
    # 409 Conflict = "the request is fine, but it doesn't fit the current state"
    if transfer.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed transfers can be retried")
    # Put it back in the queue and clear the old error, so it doesn't look failed
    transfer.status = "requested"
    transfer.error_code = None
    transfer.error_message = None
    # Changes are only saved once we commit
    session.add(transfer)
    session.commit()
    # Reload the row from the database after the commit
    session.refresh(transfer)
    return transfer
