from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "stock_recommender"
    db_user: str = "postgres"
    db_password: str = "stockpass"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # DART API
    dart_api_key: str = ""

    # Slack
    slack_webhook_url: str = ""

    # 스케줄링
    schedule_hour: int = 16
    schedule_minute: int = 30

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.db_host} "
            f"port={self.db_port} "
            f"dbname={self.db_name} "
            f"user={self.db_user} "
            f"password={self.db_password}"
        )


settings = Settings()