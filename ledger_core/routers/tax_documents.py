from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ledger_core.auth import get_current_customer
from ledger_core.database import get_session
from ledger_core.models import Account, Customer, TaxDocument
from ledger_core.schemas import TaxDocumentPublic

router = APIRouter(prefix="/me/tax-documents", tags=["tax documents"])


# Full path: GET /me/tax-documents, optionally ?year=2025
@router.get("", response_model=list[TaxDocumentPublic])
def my_tax_documents(
    # A query parameter. "int | None = None" means optional: leave it out to get every year.
    year: int | None = None,
    customer: Customer = Depends(get_current_customer),
    session: Session = Depends(get_session),
):
    query = (
        select(TaxDocument, Account)
        .select_from(TaxDocument)
        # A document has no customer_id, so we reach the owner through its account
        .join(Account, TaxDocument.account_id == Account.id)
        # The ownership filter: only this customer's accounts
        .where(Account.customer_id == customer.id)
        # Newest year first
        .order_by(TaxDocument.tax_year.desc(), TaxDocument.form)
    )
    # Only narrow by year when the caller asked for one
    if year is not None:
        query = query.where(TaxDocument.tax_year == year)
    # Run the query and build the answer for EVERY case (outside the "if" above)
    rows = session.exec(query).all()
    return [
        TaxDocumentPublic(
            id=d.id,
            account_type=a.type,
            number_last4=a.number_last4,
            form=d.form,
            tax_year=d.tax_year,
            status=d.status,
            available_on=d.available_on,
            download_path=d.download_path,
        )
        for d, a in rows
    ]
