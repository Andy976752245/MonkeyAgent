from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BAILIAN_BASE_URLS = {
    "beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "cn-beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "mainland": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "us": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "virginia": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "hongkong": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
    "cn-hongkong": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
}


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        env_path = Path.cwd() / ".env"
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if not item or item.startswith("#") or "=" not in item:
                continue
            key, value = item.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    else:
        load_dotenv()


@dataclass(frozen=True)
class Settings:
    model_provider: str
    bailian_region: str
    bailian_base_url: str
    dashscope_api_key: str
    chat_model: str
    classifier_model: str
    reasoning_model: str
    tool_builder_model: str
    evaluator_model: str
    model_temperature: float
    classifier_temperature: float
    reasoning_temperature: float
    tool_builder_temperature: float
    evaluator_temperature: float
    rules_dir: Path
    skills_dir: Path
    memory_dir: Path
    counterexamples_dir: Path
    pending_review_dir: Path
    generated_tools_dir: Path
    generated_tools_registry: Path
    runtime_dir: Path
    learning_repeat_threshold: int
    feishu_app_id: str
    feishu_app_secret: str
    feishu_verification_token: str
    feishu_encrypt_key: str
    feishu_base_url: str
    feishu_allowed_users: list[str]
    feishu_allowed_chats: list[str]
    feishu_default_user_prefix: str
    telegram_bot_token: str
    telegram_allowed_chat_ids: list[str]
    telegram_poll_timeout: int
    telegram_poll_interval: float
    telegram_request_timeout: int
    default_location: str
    agent_skill_script_timeout: int


def load_settings() -> Settings:
    _load_dotenv()
    root = package_root()
    runtime_dir = Path(os.getenv("MONKEY_AGENT_RUNTIME_DIR") or Path.cwd() / ".monkey_agent")
    region = os.getenv("BAILIAN_REGION", "beijing").lower()
    base_url = os.getenv("BAILIAN_BASE_URL") or BAILIAN_BASE_URLS.get(
        region,
        BAILIAN_BASE_URLS["beijing"],
    )
    return Settings(
        model_provider=os.getenv("MODEL_PROVIDER", "bailian").lower(),
        bailian_region=region,
        bailian_base_url=base_url,
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("BAILIAN_API_KEY", ""),
        chat_model=os.getenv("CHAT_MODEL", "qwen-plus"),
        classifier_model=os.getenv("CLASSIFIER_MODEL")
        or os.getenv("CHAT_MODEL", "qwen-plus"),
        reasoning_model=os.getenv("REASONING_MODEL")
        or os.getenv("CHAT_MODEL", "qwen-plus"),
        tool_builder_model=os.getenv("TOOL_BUILDER_MODEL")
        or os.getenv("CHAT_MODEL", "qwen-plus"),
        evaluator_model=os.getenv("EVALUATOR_MODEL")
        or os.getenv("CHAT_MODEL", "qwen-plus"),
        model_temperature=float(os.getenv("MODEL_TEMPERATURE", "0.2")),
        classifier_temperature=float(os.getenv("CLASSIFIER_TEMPERATURE", "0.0")),
        reasoning_temperature=float(os.getenv("REASONING_TEMPERATURE", "0.2")),
        tool_builder_temperature=float(os.getenv("TOOL_BUILDER_TEMPERATURE", "0.1")),
        evaluator_temperature=float(os.getenv("EVALUATOR_TEMPERATURE", "0.0")),
        rules_dir=Path(os.getenv("MONKEY_AGENT_RULES_DIR") or root / "data" / "global" / "rules"),
        skills_dir=Path(
            os.getenv("MONKEY_AGENT_SKILLS_DIR") or root / "data" / "global" / "skills"
        ),
        memory_dir=Path(
            os.getenv("MONKEY_AGENT_MEMORY_DIR") or root / "data" / "global" / "memory"
        ),
        counterexamples_dir=Path(
            os.getenv("MONKEY_AGENT_COUNTEREXAMPLES_DIR")
            or root / "data" / "global" / "counterexamples"
        ),
        pending_review_dir=Path(
            os.getenv("MONKEY_AGENT_PENDING_REVIEW_DIR")
            or runtime_dir / "personal" / "pending_review"
        ),
        generated_tools_dir=Path(
            os.getenv("MONKEY_AGENT_GENERATED_TOOLS_DIR")
            or runtime_dir / "global" / "generated_tools"
        ),
        generated_tools_registry=Path(
            os.getenv("MONKEY_AGENT_GENERATED_TOOLS_REGISTRY")
            or runtime_dir / "global" / "generated_tools.yaml"
        ),
        runtime_dir=runtime_dir,
        learning_repeat_threshold=int(os.getenv("MONKEY_AGENT_LEARNING_REPEAT_THRESHOLD", "2")),
        feishu_app_id=os.getenv("FEISHU_APP_ID", ""),
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        feishu_verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
        feishu_encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", ""),
        feishu_base_url=os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/"),
        feishu_allowed_users=_csv(os.getenv("FEISHU_ALLOWED_USERS", "")),
        feishu_allowed_chats=_csv(os.getenv("FEISHU_ALLOWED_CHATS", "")),
        feishu_default_user_prefix=os.getenv("FEISHU_DEFAULT_USER_PREFIX", "feishu"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_allowed_chat_ids=_csv(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),
        telegram_poll_timeout=int(os.getenv("TELEGRAM_POLL_TIMEOUT", "25")),
        telegram_poll_interval=float(os.getenv("TELEGRAM_POLL_INTERVAL", "1")),
        telegram_request_timeout=int(os.getenv("TELEGRAM_REQUEST_TIMEOUT", "30")),
        default_location=os.getenv("MONKEY_AGENT_DEFAULT_LOCATION", ""),
        agent_skill_script_timeout=int(os.getenv("AGENT_SKILL_SCRIPT_TIMEOUT", "30")),
    )


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
