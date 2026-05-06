from __future__ import annotations

from datetime import date, timedelta
import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import Any

from monkey_agent.domains.tools.capability import ToolResult
from monkey_agent.domains.tools import Permission, ToolRisk, ToolSchema


WEATHER_CODES = {
    0: "晴朗",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴天",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    95: "雷暴",
}

CITY_ALIASES = {
    "北京": ["北京", "北京市", "Beijing"],
    "上海": ["上海", "上海市", "Shanghai"],
    "广州": ["广州", "广州市", "Guangzhou"],
    "深圳": ["深圳", "深圳市", "Shenzhen"],
    "杭州": ["杭州", "杭州市", "Hangzhou"],
    "南京": ["南京", "南京市", "Nanjing"],
    "苏州": ["苏州", "苏州市", "Suzhou"],
    "合肥": ["合肥", "合肥市", "安徽省合肥市", "Hefei"],
    "成都": ["成都", "成都市", "Chengdu"],
    "重庆": ["重庆", "重庆市", "Chongqing"],
    "武汉": ["武汉", "武汉市", "Wuhan"],
    "西安": ["西安", "西安市", "Xi'an", "Xian"],
    "天津": ["天津", "天津市", "Tianjin"],
}


class OpenMeteoWeatherTool:
    id = "open_meteo_weather"
    name = "Open-Meteo 实时天气查询"
    description = "通过 Open-Meteo Geocoding 和 Forecast API 查询城市当前天气。"
    input_schema = ToolSchema(
        required=[],
        properties={"location": "可选；缺省时从问题抽取地点", "date": "today/tomorrow/day_after_tomorrow"},
    )
    output_schema = ToolSchema(
        required=["content"],
        properties={"content": "天气摘要", "data": "Open-Meteo 原始结构化数据"},
    )
    permission = Permission.AUTO
    risk = ToolRisk.LOW
    read_only = True
    learn_policy = "rule"

    def can_handle(self, question: str, context: dict[str, Any]) -> bool:
        return "天气" in question or context.get("capability") == "weather"

    def execute(self, question: str, context: dict[str, Any]) -> ToolResult:
        location = context.get("location") or _extract_location(question)
        requested_day = str(context.get("date") or _extract_date(question))
        if not location:
            return ToolResult(
                tool_id=self.id,
                tool_name=self.name,
                success=False,
                stable_rule_candidate=True,
                content="缺少天气查询地点。",
                error="missing_location",
                handler_name="weather_query",
                handler_code_proposal=_weather_handler_code(),
                permission=self.permission,
                risk=self.risk,
                read_only=self.read_only,
            )
        try:
            geo = self._geocode(str(location))
            weather = self._forecast(geo, requested_day)
        except Exception as exc:  # noqa: BLE001 - user-facing tool boundary
            return ToolResult(
                tool_id=self.id,
                tool_name=self.name,
                success=False,
                stable_rule_candidate=True,
                content=f"天气工具调用失败：{exc}",
                error=str(exc),
                handler_name="weather_query",
                handler_code_proposal=_weather_handler_code(),
                permission=self.permission,
                risk=self.risk,
                read_only=self.read_only,
            )

        current = _weather_for_day(weather, requested_day)
        code = int(current.get("weather_code", current.get("weathercode", -1)))
        description = WEATHER_CODES.get(code, f"天气代码 {code}")
        date_label = _date_label(requested_day)
        content = (
            f"{geo['name']}{date_label}天气：{description}，"
            f"气温 {current.get('temperature_2m', current.get('temperature_2m_max'))}°C"
        )
        if current.get("temperature_2m_min") is not None:
            content += f" 至 {current.get('temperature_2m_min')}°C"
        if current.get("relative_humidity_2m") is not None:
            content += f"，相对湿度 {current.get('relative_humidity_2m')}%"
        if current.get("precipitation") is not None:
            content += f"，降水 {current.get('precipitation')} mm"
        elif current.get("precipitation_sum") is not None:
            content += f"，降水 {current.get('precipitation_sum')} mm"
        if current.get("wind_speed_10m") is not None:
            content += f"，风速 {current.get('wind_speed_10m')} km/h"
        elif current.get("wind_speed_10m_max") is not None:
            content += f"，最大风速 {current.get('wind_speed_10m_max')} km/h"
        content += "。"
        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=True,
            content=content,
            data={
                "provider": "Open-Meteo",
                "location": geo,
                "current": current,
                "requested_day": requested_day,
                "timezone": weather.get("timezone"),
            },
            handler_name="weather_query",
            handler_code_proposal=_weather_handler_code(),
            permission=self.permission,
            risk=self.risk,
            read_only=self.read_only,
        )

    def _geocode(self, location: str) -> dict[str, Any]:
        errors: list[str] = []
        for candidate in _location_candidates(location):
            try:
                return self._geocode_one(candidate)
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(f"未找到地点：{location}; tried={_location_candidates(location)}; errors={errors}")

    def _geocode_one(self, location: str) -> dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "name": location,
                "count": 1,
                "language": "zh",
                "format": "json",
            }
        )
        data = _get_json(f"https://geocoding-api.open-meteo.com/v1/search?{params}")
        results = data.get("results") or []
        if not results:
            raise ValueError(f"未找到地点：{location}")
        item = results[0]
        return {
            "name": item.get("name", location),
            "country": item.get("country"),
            "admin1": item.get("admin1"),
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "timezone": item.get("timezone", "auto"),
        }

    def _forecast(self, geo: dict[str, Any], requested_day: str) -> dict[str, Any]:
        payload = {
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "timezone": geo.get("timezone") or "auto",
        }
        if requested_day == "today":
            payload["current"] = (
                "temperature_2m,relative_humidity_2m,precipitation,"
                "weather_code,wind_speed_10m"
            )
            payload["daily"] = (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,wind_speed_10m_max"
            )
        else:
            payload["daily"] = (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,wind_speed_10m_max"
            )
            payload["forecast_days"] = 3
        params = urllib.parse.urlencode(payload)
        return _get_json(f"https://api.open-meteo.com/v1/forecast?{params}")


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MonkeyAgent/0.1"},
    )
    context = _ssl_context()
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _extract_location(question: str) -> str | None:
    for pattern in [
        r"(?:今天|今日|当日|明天|明日|后天)?(.+?)(?:天气|气温|降水)",
        r"(?:查一下|查询)(?:今天|今日|当日|明天|明日|后天)?(.+?)(?:天气|气温|降水)",
    ]:
        match = re.search(pattern, question)
        if match:
            location = match.group(1).strip(" ，,。？?的")
            location = _normalize_location(location)
            if location:
                return location
    return None


def _normalize_location(location: str) -> str:
    value = location.strip()
    value = re.sub(r"^(?:请问|帮我查一下|帮我查|查一下|查询|看看)", "", value)
    value = re.sub(r"(?:省|市|区|县)$", lambda m: m.group(0), value)
    return value.strip(" ，,。？?的")


def _location_candidates(location: str) -> list[str]:
    normalized = _normalize_location(location)
    candidates: list[str] = []
    if normalized in CITY_ALIASES:
        candidates.extend(CITY_ALIASES[normalized])
    else:
        short = normalized
        for suffix in ["市", "省"]:
            short = short.removesuffix(suffix)
        if short in CITY_ALIASES:
            candidates.extend(CITY_ALIASES[short])
        candidates.extend([normalized, short])
        if not normalized.endswith("市") and re.search(r"[\u4e00-\u9fff]", normalized):
            candidates.append(f"{normalized}市")
    deduped: list[str] = []
    for item in candidates:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _extract_date(question: str) -> str:
    if "后天" in question:
        return "day_after_tomorrow"
    if "明天" in question or "明日" in question:
        return "tomorrow"
    return "today"


def _date_label(requested_day: str) -> str:
    return {
        "today": "当前",
        "tomorrow": "明天",
        "day_after_tomorrow": "后天",
    }.get(requested_day, requested_day)


def _weather_for_day(weather: dict[str, Any], requested_day: str) -> dict[str, Any]:
    if requested_day == "today" and weather.get("current"):
        return weather["current"]
    daily = weather.get("daily") or {}
    dates = daily.get("time") or []
    target = {
        "today": date.today(),
        "tomorrow": date.today() + timedelta(days=1),
        "day_after_tomorrow": date.today() + timedelta(days=2),
    }.get(requested_day, date.today())
    target_text = target.isoformat()
    index = dates.index(target_text) if target_text in dates else 0
    return {
        "time": dates[index] if index < len(dates) else target_text,
        "weather_code": _daily_value(daily, "weather_code", index),
        "temperature_2m_max": _daily_value(daily, "temperature_2m_max", index),
        "temperature_2m_min": _daily_value(daily, "temperature_2m_min", index),
        "precipitation_sum": _daily_value(daily, "precipitation_sum", index),
        "wind_speed_10m_max": _daily_value(daily, "wind_speed_10m_max", index),
    }


def _daily_value(daily: dict[str, Any], key: str, index: int) -> Any:
    values = daily.get(key) or []
    if index >= len(values):
        return None
    return values[index]


def _weather_handler_code() -> str:
    return '''def weather_query(rule, question, context):
    """Reviewed handler for weather queries.

    Uses the configured weather capability/tool to fetch live data.
    Do not let the LLM invent weather when this tool is unavailable.
    """
    location = context.get("location")
    if not location:
        return {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "type": "api_tool",
            "requires_more_info": True,
            "missing_fields": ["location"],
        }
    # Production implementation should call the approved weather capability.
    raise NotImplementedError("Bind this rule to the approved weather capability")
'''
