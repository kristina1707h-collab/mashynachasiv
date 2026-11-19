from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    admin_ids: str = ""
    public_base_url: str = ""
    admin_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    timezone: str = "Europe/Kyiv"
    polling: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def admins(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

settings = Settings()
