from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_current_user
from app.models import LLMConfig
from app.schemas import LLMConfigCreate, LLMConfigOut, LLMConfigUpdate
from app.services.llm_client import LLMClient


router = APIRouter(prefix="/llm-configs", tags=["llm-configs"], dependencies=[Depends(get_current_user)])


def _mask_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def _out(config: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=config.id,
        name=config.name,
        base_url=config.base_url,
        api_key=None,
        api_key_masked=_mask_key(config.api_key),
        model=config.model,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
        llm_concurrency=config.llm_concurrency,
        stream=config.stream,
        is_default=config.is_default,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("", response_model=list[LLMConfigOut])
def list_configs(db: Session = Depends(db_session)) -> list[LLMConfigOut]:
    return [_out(config) for config in db.query(LLMConfig).order_by(LLMConfig.id.desc()).all()]


@router.post("", response_model=LLMConfigOut)
def create_config(payload: LLMConfigCreate, db: Session = Depends(db_session)) -> LLMConfigOut:
    if payload.is_default:
        db.query(LLMConfig).update({LLMConfig.is_default: False})
    config = LLMConfig(**payload.model_dump())
    db.add(config)
    db.commit()
    db.refresh(config)
    return _out(config)


@router.put("/{config_id}", response_model=LLMConfigOut)
def update_config(config_id: int, payload: LLMConfigUpdate, db: Session = Depends(db_session)) -> LLMConfigOut:
    config = db.get(LLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")
    if payload.is_default:
        db.query(LLMConfig).filter(LLMConfig.id != config_id).update({LLMConfig.is_default: False})
    for key, value in payload.model_dump().items():
        if key == "api_key" and value in (None, "") and config.api_key:
            continue
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return _out(config)


@router.delete("/{config_id}")
def delete_config(config_id: int, db: Session = Depends(db_session)) -> dict[str, bool]:
    config = db.get(LLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")
    db.delete(config)
    db.commit()
    return {"ok": True}


@router.post("/{config_id}/test")
async def test_config(config_id: int, db: Session = Depends(db_session)) -> dict:
    config = db.get(LLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="LLM config not found")
    client = LLMClient(config.base_url, config.api_key, config.model, config.timeout)
    return await client.test()
