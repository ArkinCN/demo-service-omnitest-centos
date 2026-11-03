"""Generate proposals through the existing model gateway; never apply them."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.api.deps import get_current_user, get_db
from app.api.v1.agent_stream import list_agent_models
from app.models.user import User
from app.services.agent_chat_service import run_agent_chat
from app.services.config_suggestions import SuggestionRequest, model_prompt, parse_proposal, validate_context

router = APIRouter(prefix="/agent", tags=["Configuration suggestions"])


@router.post("/config-suggestions")
async def suggest_configuration(
    body: SuggestionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    try:
        validate_context(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Reuse the exact model visibility / activity / chat policy of the UI list.
    available = await list_agent_models(current_user=current_user, session=session)
    if body.model not in {m["id"] for m in available["data"]}:
        raise HTTPException(403, "This model is not available to the current user")

    async def collect():
        parts = []
        size = 0
        async for event in run_agent_chat(
            client=request.app.state.ai_http_client,
            user_id=current_user.id,
            user_message=model_prompt(body),
            history=None,
            model=body.model,
            ip=request.client.host if request.client else None,
            enabled_tools=[], permission="readonly", locale=body.locale,
        ):
            if event.get("type") == "error":
                raise ValueError("Model call failed")
            if event.get("type") == "content_delta":
                chunk = event.get("text", "")
                if not isinstance(chunk, str):
                    raise ValueError("Invalid model event")
                size += len(chunk)
                if size > 64000:
                    raise ValueError("Model response too large")
                parts.append(chunk)
        return parse_proposal("".join(parts), body)

    try:
        proposal = await asyncio.wait_for(collect(), timeout=180)
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "Model suggestion timed out; no configuration was changed") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(502, "The model did not return a valid, supported proposal; no configuration was changed") from exc
    return {"model": body.model, "proposal": proposal.model_dump()}
