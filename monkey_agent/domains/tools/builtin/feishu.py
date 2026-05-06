from __future__ import annotations

import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from typing import Any

from monkey_agent.domains.tools.capability import ToolResult
from monkey_agent.domains.tools import Permission, ToolRisk, ToolSchema


FEISHU_MESSAGE_CREATE_DOC = (
    "https://open.feishu.cn/document/server-docs/im-v1/message/create"
)


class FeishuSendMessageTool:
    id = "feishu_send_message"
    name = "飞书发送消息"
    description = "通过飞书开放平台 IM v1 message/create 给用户或群聊发送消息。"
    input_schema = ToolSchema(
        required=["message"],
        properties={
            "message": "待发送文本",
            "receive_id": "飞书用户或群聊 ID，可由环境变量提供",
            "receive_id_type": "chat_id/user_id/open_id/union_id/email",
        },
    )
    output_schema = ToolSchema(
        required=["content"],
        properties={"content": "发送结果摘要", "data": "飞书 API 响应"},
    )
    permission = Permission.CONFIRM
    risk = ToolRisk.MEDIUM
    read_only = False
    learn_policy = "rule"

    def can_handle(self, question: str, context: dict[str, Any]) -> bool:
        text = question.lower()
        return (
            "飞书" in question
            and any(word in question for word in ["消息", "发一条", "发送", "对接"])
        ) or context.get("capability") in {"feishu", "lark_send_message"}

    def execute(self, question: str, context: dict[str, Any]) -> ToolResult:
        config = _load_config(context)
        message = context.get("message") or _extract_message(question)
        missing = [
            name
            for name, value in [
                ("FEISHU_APP_ID", config["app_id"]),
                ("FEISHU_APP_SECRET", config["app_secret"]),
                ("receive_id", config["receive_id"]),
                ("message", message),
            ]
            if not value
        ]
        if missing:
            return ToolResult(
                tool_id=self.id,
                tool_name=self.name,
                success=False,
                stable_rule_candidate=True,
                content="飞书发送消息能力已识别，但缺少必要配置或入参。",
                data={
                    "public_support": True,
                    "docs_url": FEISHU_MESSAGE_CREATE_DOC,
                    "endpoint": "/im/v1/messages",
                    "required_scopes": [
                        "发送消息",
                        "以应用身份发送消息",
                    ],
                    "missing_fields": missing,
                    "receive_id_type": config["receive_id_type"],
                },
                error="missing_fields:" + ",".join(missing),
                handler_name="feishu_send_message",
                handler_code_proposal=_handler_code(),
                permission=self.permission,
                risk=self.risk,
                read_only=self.read_only,
            )

        try:
            token = self._tenant_access_token(config)
            response = self._send_message(config, token, str(message))
        except Exception as exc:  # noqa: BLE001 - integration boundary
            return ToolResult(
                tool_id=self.id,
                tool_name=self.name,
                success=False,
                stable_rule_candidate=True,
                content=f"飞书发送消息能力已识别，但调用失败：{exc}",
                data={
                    "public_support": True,
                    "docs_url": FEISHU_MESSAGE_CREATE_DOC,
                    "endpoint": "/im/v1/messages",
                    "receive_id_type": config["receive_id_type"],
                },
                error=str(exc),
                handler_name="feishu_send_message",
                handler_code_proposal=_handler_code(),
                permission=self.permission,
                risk=self.risk,
                read_only=self.read_only,
            )

        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=True,
            content="飞书消息已发送成功。",
            data={
                "public_support": True,
                "docs_url": FEISHU_MESSAGE_CREATE_DOC,
                "endpoint": "/im/v1/messages",
                "response": response,
                "receive_id_type": config["receive_id_type"],
            },
            handler_name="feishu_send_message",
            handler_code_proposal=_handler_code(),
            permission=self.permission,
            risk=self.risk,
            read_only=self.read_only,
        )

    def _tenant_access_token(self, config: dict[str, str]) -> str:
        payload = {
            "app_id": config["app_id"],
            "app_secret": config["app_secret"],
        }
        data = _post_json(
            f"{config['base_url']}/auth/v3/tenant_access_token/internal",
            payload,
            headers={},
        )
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"missing tenant_access_token: {data}")
        return str(token)

    def _send_message(
        self,
        config: dict[str, str],
        token: str,
        message: str,
    ) -> dict[str, Any]:
        receive_id_type = config["receive_id_type"] or "chat_id"
        query = urllib.parse.urlencode({"receive_id_type": receive_id_type})
        payload = {
            "receive_id": config["receive_id"],
            "msg_type": "text",
            "content": json.dumps({"text": message}, ensure_ascii=False),
        }
        return _post_json(
            f"{config['base_url']}/im/v1/messages?{query}",
            payload,
            headers={"Authorization": f"Bearer {token}"},
        )


def _load_config(context: dict[str, Any]) -> dict[str, str]:
    return {
        "app_id": str(context.get("feishu_app_id") or os.getenv("FEISHU_APP_ID", "")),
        "app_secret": str(
            context.get("feishu_app_secret") or os.getenv("FEISHU_APP_SECRET", "")
        ),
        "receive_id": str(
            context.get("receive_id") or os.getenv("FEISHU_RECEIVE_ID", "")
        ),
        "receive_id_type": str(
            context.get("receive_id_type")
            or os.getenv("FEISHU_RECEIVE_ID_TYPE", "chat_id")
        ),
        "base_url": str(
            context.get("feishu_base_url")
            or os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn/open-apis")
        ).rstrip("/"),
    }


def _extract_message(question: str) -> str | None:
    patterns = [
        r"(?:内容|消息内容|发送内容)[：:]\s*(.+)$",
        r"发一条(?:飞书)?消息[：:]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            return match.group(1).strip()
    return None


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "MonkeyAgent/0.1",
            **headers,
        },
    )
    with urllib.request.urlopen(request, timeout=10, context=_ssl_context()) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("code") not in (None, 0):
        raise RuntimeError(data)
    return data


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _handler_code() -> str:
    return '''def feishu_send_message(rule, question, context):
    """Reviewed handler for Feishu/Lark message sending.

    Public support:
    - Feishu Open Platform IM v1 message/create
    - POST /open-apis/im/v1/messages?receive_id_type=chat_id

    Required review before production:
    - confirm app permissions/scopes
    - configure FEISHU_APP_ID and FEISHU_APP_SECRET securely
    - confirm receive_id and receive_id_type
    - add tests with mocked Feishu responses
    """
    receive_id = context.get("receive_id")
    message = context.get("message")
    if not receive_id or not message:
        return {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "type": "api_tool",
            "requires_more_info": True,
            "missing_fields": [
                field
                for field, value in {"receive_id": receive_id, "message": message}.items()
                if not value
            ],
        }
    # Production implementation should call the approved Feishu capability.
    raise NotImplementedError("Bind this rule to the approved Feishu capability")
'''
