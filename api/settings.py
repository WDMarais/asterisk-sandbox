from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ami_host: str = "127.0.0.1"
    ami_port: int = 5038
    ami_user: str = "asterisk-sandbox"
    ami_secret: str

    sip_pass_01: str = ""
    sip_pass_02: str = ""

    domain: str = ""
    email: str = ""
    repo_url: str = ""
