# -*- coding: utf-8 -*-
"""LinkedIn — check whether the supported MCP server is configured."""

import shutil

from .base import Channel
from .mcporter import McporterConfigError, inspect_mcporter_config

_LINKEDIN_SERVER_NAMES = {
    "linkedin",
    "mcp-server-linkedin",
    "linkedin-scraper",
    "linkedin-scraper-mcp",
}
_LINKEDIN_SETUP = (
    "mcporter config add linkedin --command uvx "
    "--arg mcp-server-linkedin@latest "
    "--env UV_HTTP_TIMEOUT=300 --scope home"
)


class LinkedInChannel(Channel):
    name = "linkedin"
    description = "LinkedIn 职业社交"
    backends = ["mcp-server-linkedin", "Jina Reader"]
    tier = 2

    def can_handle(self, url: str) -> bool:
        from agent_reach.utils.url import host_matches

        return host_matches(url, "linkedin.com")

    def check(self, config=None):
        self.active_backend = None
        if not shutil.which("mcporter"):
            return "off", (
                "基本内容可通过 Jina Reader 读取。完整功能需要：\n"
                "  安装 uv：https://docs.astral.sh/uv/\n"
                f"  {_LINKEDIN_SETUP}\n"
                "  详见 https://github.com/stickerdaniel/linkedin-mcp-server"
            )
        try:
            inspection = inspect_mcporter_config()
        except McporterConfigError as exc:
            return "error", f"mcporter 配置检查失败：{exc}"
        if inspection.server_names & _LINKEDIN_SERVER_NAMES:
            return "warn", (
                "LinkedIn MCP 已写入 mcporter 配置，但 Doctor 未启动本地"
                "服务做连通验证，不能仅凭配置宣称完整可用。"
            )
        if inspection.imports_unchecked:
            return "warn", (
                "mcporter 本地配置未发现 LinkedIn MCP；配置还启用了 editor "
                "imports，Doctor 为避免扩大凭据读取范围没有展开，当前未验证。"
            )
        return "off", (
            "mcporter 已装但 LinkedIn MCP 未配置。运行：\n"
            f"  {_LINKEDIN_SETUP}"
        )
