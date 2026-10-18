"""Assistant CarbonLedger Copilot (option IA + mode démonstration)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from ..config import settings
from ..db import get_db
from ..deps import require_api_context, require_context
from ..models import CarbonRecord, DecisionProject, Expense
from ..services import audit
from ..services.copilot import SUGGESTED_QUESTIONS, ask
from ..web import page_context, render

router = APIRouter()


@router.get("/copilot")
def copilot_page(request: Request, db: OrmSession = Depends(get_db)):
    context = require_context(request, db)
    counts = {
        "expenses": db.execute(
            select(func.count(Expense.id)).where(Expense.organization_id == context.organization.id)
        ).scalar_one(),
        "carbon_records": db.execute(
            select(func.count(CarbonRecord.id)).where(CarbonRecord.organization_id == context.organization.id)
        ).scalar_one(),
        "projects": db.execute(
            select(func.count(DecisionProject.id)).where(DecisionProject.organization_id == context.organization.id)
        ).scalar_one(),
    }
    return render(
        request,
        "copilot/index.html",
        page_context(
            request,
            db,
            context,
            "copilot",
            {
                "suggested_questions": SUGGESTED_QUESTIONS,
                "counts": counts,
                "ai_configured": settings.ai_configured,
                "ai_model": settings.ai_model if settings.ai_configured else "",
            },
        ),
    )


@router.post("/api/copilot/ask")
async def copilot_ask(request: Request, db: OrmSession = Depends(get_db)):
    context = require_api_context(request, db)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Corps JSON invalide."}, status_code=400)
    question = str(payload.get("question") or "")[:2000]
    history = payload.get("history") or []
    if not isinstance(history, list):
        history = []
    answer = ask(db, context.organization, question, history)
    audit.log(
        db,
        action="copilot_question",
        organization_id=context.organization.id,
        user_id=context.user.id,
        details={"mode": answer.mode, "question": question[:140]},
        request=request,
        commit=True,
    )
    return {"ok": True, **answer.to_dict()}
