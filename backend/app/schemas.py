from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LLMConfigBase(BaseModel):
    name: str = "Default"
    base_url: str
    api_key: str | None = None
    model: str
    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = 4096
    timeout: int = 120
    llm_concurrency: int = Field(default=1, ge=1, le=16)
    stream: bool = False
    is_default: bool = False


class LLMConfigCreate(LLMConfigBase):
    pass


class LLMConfigUpdate(LLMConfigBase):
    pass


class LLMConfigOut(LLMConfigBase):
    id: int
    api_key_masked: str | None = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    name: str = Field(min_length=1)
    llm_config_id: int | None = None


class TaskOut(BaseModel):
    id: str
    name: str
    status: str
    main_tex_path: str | None
    original_pdf_path: str | None
    translated_pdf_path: str | None
    total_blocks: int
    translated_blocks: int
    failed_blocks: int
    llm_config_id: int | None
    error_message: str | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class GlossaryTermBase(BaseModel):
    source_term: str
    target_term: str
    term_type: str = "custom"
    frequency: int = 1
    context: str | None = None
    is_locked: bool = False


class GlossaryTermCreate(GlossaryTermBase):
    pass


class GlossaryTermUpdate(GlossaryTermBase):
    pass


class GlossaryTermOut(GlossaryTermBase):
    id: int
    task_id: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TranslationBlockOut(BaseModel):
    id: str
    task_id: str
    file_path: str
    block_index: int
    block_type: str
    source_text: str
    protected_text: str | None
    translated_text: str | None
    status: str
    error_message: str | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class TranslationBlockUpdate(BaseModel):
    translated_text: str
    status: str = "completed"


class LogOut(BaseModel):
    id: int
    task_id: str
    level: str
    module: str
    message: str
    created_at: str

    class Config:
        from_attributes = True
