from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from app.config import settings
from app.db import Session, Student, Payment
from app.access import access_until, new_code

router = APIRouter(prefix="/api")

class PaymentIn(BaseModel):
    external_payment_id: str
    customer_name: str
    package: str
    paid_at: datetime
    telegram_id: int | None = None
    amount: int | None = None

def auth(key):
    if not settings.admin_api_key or key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.post("/payments/confirm")
async def confirm_payment(data: PaymentIn, x_api_key: str = Header(default="")):
    auth(x_api_key)
    if data.package not in {"self", "curator", "valeria"}:
        raise HTTPException(400, "Unknown package")

    async with Session() as s:
        existing = await s.execute(select(Payment).where(Payment.external_id == data.external_payment_id))
        if existing.scalar_one_or_none():
            return {"ok": True, "duplicate": True}

        student = None
        if data.telegram_id:
            r = await s.execute(select(Student).where(Student.telegram_id == data.telegram_id))
            student = r.scalar_one_or_none()

        if not student:
            student = Student(
                telegram_id=data.telegram_id,
                name=data.customer_name,
                package=data.package,
                access_code=new_code(),
                status="навчається",
                active=bool(data.telegram_id),
            )
            s.add(student)
            await s.flush()
        else:
            student.name = data.customer_name
            student.package = data.package
            student.active = True
            student.status = "навчається"

        student.paid_at = data.paid_at
        student.access_until = access_until(data.paid_at)

        payment = Payment(
            external_id=data.external_payment_id,
            telegram_id=data.telegram_id,
            name=data.customer_name,
            package=data.package,
            amount=data.amount,
            paid_at=data.paid_at,
        )
        s.add(payment)
        await s.commit()

        return {
            "ok": True,
            "telegram_id": student.telegram_id,
            "package": student.package,
            "access_code": student.access_code,
            "deep_link": f"https://t.me/{{BOT_USERNAME}}?start={student.access_code}",
            "access_until": student.access_until.isoformat(),
        }

@router.get("/students/{telegram_id}")
async def student(telegram_id: int, x_api_key: str = Header(default="")):
    auth(x_api_key)
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == telegram_id))
        st = r.scalar_one_or_none()
        if not st:
            raise HTTPException(404, "Student not found")
        return {
            "telegram_id": st.telegram_id,
            "name": st.name,
            "package": st.package,
            "paid_at": st.paid_at,
            "access_until": st.access_until,
            "active": st.active,
            "status": st.status,
        }
