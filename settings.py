from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    OPENAI_API_KEY:        str  = Field('')
    ANTHROPIC_API_KEY:     str  = Field('')
    API_VERSION:           str  = Field('')
    ENV:                   str  = Field('')
    LOGFIRE_TOKEN:         str  = Field('')
    VERBOSE:               bool = Field(default=False)
    LIVEKIT_WEBSOCKET_URL: str  = Field('')
    LIVEKIT_URL:           str  = Field('')
    LIVEKIT_API_KEY:       str  = Field('')
    LIVEKIT_API_SECRET:    str  = Field('')
    WORKING_DIR:           str  = Field('.')
    CLAUDE_API_KEY:        str  = Field('.')

Config = Config()

