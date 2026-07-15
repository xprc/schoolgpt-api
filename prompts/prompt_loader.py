from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from ipaddress import ip_address

import requests

from utils.config_handler import prompts_conf
from utils.path_tools import get_abs_path
from utils.logger_handler import logger


CN_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")
GEOIP_URL = "https://api.projectoms.com/geoip"
GEOIP_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class GeoIpInfo:
    ip: str
    nation: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    operator: str = ""


def _current_datetime_text():
    return datetime.now(CN_TIMEZONE).strftime("%Y年%m月%d日 %H:%M:%S")


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _normalize_ip(value: str | None) -> str | None:
    candidate = _clean_text(value)
    if not candidate:
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.rsplit(":", maxsplit=1)[0]

    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def resolve_client_ip(
    headers: Mapping[str, str],
    client_host: str | None,
) -> str | None:
    forwarded_for = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded_for:
        for raw_value in forwarded_for.split(","):
            normalized_ip = _normalize_ip(raw_value)
            if normalized_ip:
                return normalized_ip

    for header_name in ("x-real-ip", "X-Real-IP", "cf-connecting-ip", "CF-Connecting-IP"):
        normalized_ip = _normalize_ip(headers.get(header_name))
        if normalized_ip:
            return normalized_ip

    forwarded = headers.get("forwarded") or headers.get("Forwarded")
    if forwarded:
        for part in forwarded.split(";"):
            key, _, raw_value = part.partition("=")
            if key.strip().lower() != "for":
                continue

            normalized_ip = _normalize_ip(raw_value.strip().strip('"'))
            if normalized_ip:
                return normalized_ip

    return _normalize_ip(client_host)


@lru_cache(maxsize=1024)
def _lookup_geoip(ip: str) -> GeoIpInfo | None:
    try:
        response = requests.get(
            GEOIP_URL,
            params={"ip": ip},
            timeout=GEOIP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("[geoip]查询 IP 归属地失败: %s | %s", ip, exc)
        return None

    if not isinstance(payload, dict):
        return None

    return GeoIpInfo(
        ip=_clean_text(payload.get("ip")) or ip,
        nation=_clean_text(payload.get("nation")),
        province=_clean_text(payload.get("province")),
        city=_clean_text(payload.get("city")),
        district=_clean_text(payload.get("district")),
        operator=_clean_text(payload.get("operator")),
    )


def _get_geoip(ip: str | None) -> GeoIpInfo | None:
    if not ip:
        return None

    try:
        parsed_ip = ip_address(ip)
    except ValueError:
        return None

    if not parsed_ip.is_global:
        return GeoIpInfo(ip=ip)

    return _lookup_geoip(ip) or GeoIpInfo(ip=ip)


def _geo_location_text(geo_info: GeoIpInfo) -> str:
    location_parts = [
        geo_info.nation,
        geo_info.province,
        geo_info.city,
        geo_info.district,
    ]
    return " / ".join(part for part in location_parts if part)


def build_user_runtime_context(user: object | None, client_ip: str | None) -> str:
    geo_info = _get_geoip(client_ip)

    lines = ["### 当前用户上下文"]
    if user is not None:
        lines.extend(
            [
                f"- 姓名：{_clean_text(getattr(user, 'display_name', '')) or '未知'}",
                f"- 用户名：{_clean_text(getattr(user, 'username', '')) or '未知'}",
                f"- 用户身份：{_clean_text(getattr(user, 'user_type', '')) or '未知'}",
                f"- 偏好语言：{_clean_text(getattr(user, 'preferred_language', '')) or '未知'}",
            ]
        )
    else:
        lines.append("- 用户：当前登录用户信息未查询到。")

    if geo_info is not None:
        lines.append(f"- IP：{geo_info.ip}")
        location_text = _geo_location_text(geo_info)
        if location_text:
            lines.append(f"- IP 归属地：{location_text}")
        if geo_info.operator:
            lines.append(f"- 网络运营商：{geo_info.operator}")
    elif client_ip:
        lines.append(f"- IP：{client_ip}")

    lines.append(
        "- 以上信息来自登录态和请求环境，仅用于称呼、身份判断、位置相关问题和校园服务个性化；"
        "不要声称这些信息来自用户主动输入。"
    )
    return "\n".join(lines)


def _with_runtime_context(prompt_text: str, user_runtime_context: str | None = None) -> str:
    runtime_context_parts = [
        "### 运行时上下文",
        f"- 当前日期时间：{_current_datetime_text()}（Asia/Shanghai，UTC+08:00）。",
        "- 当前日期时间用于判断政策时效、截止日期、办理时间和回答中的时间表达；"
        "不得声称该时间来自用户消息。",
    ]
    normalized_user_context = str(user_runtime_context or "").strip()
    if normalized_user_context:
        runtime_context_parts.append(normalized_user_context)

    return (
        "\n".join(runtime_context_parts)
        + "\n\n"
        f"{prompt_text}"
    )


def load_system_prompt(user_runtime_context: str | None = None):
    try:
        system_prompt_path = get_abs_path(prompts_conf["main_prompt_path"])
    except KeyError as e:
        logger.error(f"[load_system_prompt]解析系统提示词文件路径失败。")
        raise e

    try:
        return _with_runtime_context(
            open(system_prompt_path, "r", encoding="utf-8").read(),
            user_runtime_context,
        )
    except FileNotFoundError as e:
        logger.error(f"[load_system_prompt]系统提示词文件{system_prompt_path}不存在. {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"[load_system_prompt]解析系统提示词{system_prompt_path}失败. {str(e)}")
        raise e


def load_report_prompt(user_runtime_context: str | None = None):
    try:
        report_prompt_path = get_abs_path(prompts_conf["report_prompt_path"])
    except KeyError as e:
        logger.error(f"[report_prompt_path]解析系统提示词文件路径失败。")
        raise e

    try:
        return _with_runtime_context(
            open(report_prompt_path, "r", encoding="utf-8").read(),
            user_runtime_context,
        )
    except FileNotFoundError as e:
        logger.error(f"[report_prompt_path]报告提示词文件{report_prompt_path}不存在. {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"[report_prompt_path]解析报告提示词{report_prompt_path}失败. {str(e)}")
        raise e


def load_policy_rag_search_prompt():
    try:
        rag_prompt_path = get_abs_path(prompts_conf["policy_rag_search_prompt_path"])
    except KeyError as e:
        logger.error(f"[policy_rag_search_prompt_path]解析系统提示词文件路径失败。")
        raise e

    try:
        return open(rag_prompt_path, "r", encoding="utf-8").read()
    except FileNotFoundError as e:
        logger.error(f"[policy_rag_search_prompt_path]报告提示词文件{rag_prompt_path}不存在. {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"[policy_rag_search_prompt_path]解析报告提示词{rag_prompt_path}失败. {str(e)}")
        raise e
