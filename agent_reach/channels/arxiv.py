# -*- coding: utf-8 -*-
"""ArXiv — public API channel for academic paper search and metadata."""

import urllib.request
from typing import List
from urllib.parse import quote

from agent_reach.channels.base import Channel

_UA = "agent-reach/1.0"
_TIMEOUT = 15
_MAX_RESPONSE_BYTES = 1024 * 1024
_API_BASE = "https://export.arxiv.org/api/query"


def _quote_query(query: str) -> str:
    """URL-encode a search query, preserving spaces as + for ArXiv API."""
    return quote(query, safe="")


def _fetch(params: str) -> str:
    """Fetch from ArXiv API with bounded response size."""
    url = f"{_API_BASE}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        raw = resp.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("ArXiv API response exceeds the 1 MiB safety limit")
    return raw.decode("utf-8")


def _parse_entries(xml_text: str) -> List[dict]:
    """Parse Atom XML entries into structured dicts.

    Returns a list of dicts with keys:
      title, authors, summary, arxiv_id, link, published, categories
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    results = []
    for entry in root.findall("atom:entry", ns):
        title_elem = entry.find("atom:title", ns)
        summary_elem = entry.find("atom:summary", ns)
        id_elem = entry.find("atom:id", ns)
        published_elem = entry.find("atom:published", ns)
        link_elem = entry.find("atom:link[@rel='alternate']", ns)
        authors_elem = entry.findall("atom:author", ns)

        title = (title_elem.text or "").strip().replace("\n", " ")
        summary = (summary_elem.text or "").strip().replace("\n", " ")
        arxiv_id = (id_elem.text or "").strip()
        published = (published_elem.text or "").strip()
        link = link_elem.get("href", "") if link_elem is not None else ""

        # Extract categories
        categories = [
            cat.get("term", "")
            for cat in entry.findall("atom:category", ns)
        ]

        # Extract authors
        author_names = []
        for author in authors_elem:
            name_elem = author.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                author_names.append(name_elem.text.strip())

        results.append(
            {
                "title": title,
                "authors": author_names,
                "summary": summary[:500],  # Truncate long summaries
                "arxiv_id": arxiv_id.split("/")[-1] if "/" in arxiv_id else arxiv_id,
                "link": link or f"https://arxiv.org/abs/{arxiv_id.split('/')[-1]}",
                "published": published,
                "categories": categories,
            }
        )
    return results


class ArxivChannel(Channel):
    name = "arxiv"
    description = "ArXiv 学术论文搜索"
    backends = ["ArXiv API (public)"]
    tier = 0

    def can_handle(self, url: str) -> bool:
        from agent_reach.utils.url import host_matches

        return host_matches(url, "arxiv.org")

    def check(self, config=None):
        """Probe ArXiv API connectivity with a lightweight search."""
        self.active_backend = None
        try:
            xml_text = _fetch("search_query=all:test&start=0&max_results=1")
            entries = _parse_entries(xml_text)
            if entries:
                self.active_backend = self.backends[0]
                return "ok", "公开 API 可用（论文搜索、摘要读取）"
            return "warn", "API 连通但无响应结果"
        except Exception as e:
            self.active_backend = None
            from agent_reach.utils.text import scrub_url_credentials

            return (
                "warn",
                f"ArXiv API 连接失败（可能需要代理）：{scrub_url_credentials(e)}",
            )

    def search(self, query: str, limit: int = 10) -> List[dict]:
        """搜索论文，返回结构化摘要列表。

        Args:
            query: 搜索关键词，如 "transformer"、"LLM"、"cs.CV"
            limit: 最多返回条数（上限 100）

        Returns:
            list of dicts with keys: title, authors, summary, arxiv_id, link, published, categories
        """
        if limit < 0:
            raise ValueError("limit must be non-negative")
        limit = min(limit, 100)
        if limit == 0:
            return []

        encoded_query = _quote_query(query)
        xml_text = _fetch(f"search_query=all:{encoded_query}&start=0&max_results={limit}")
        return _parse_entries(xml_text)

    def get_paper(self, arxiv_id: str) -> dict:
        """获取单篇论文详情。

        Args:
            arxiv_id: 论文 ID，如 "2301.00001" 或完整 URL "https://arxiv.org/abs/2301.00001"

        Returns:
            dict with keys: title, authors, summary, arxiv_id, link, published, categories
        """
        # Extract ID from URL if needed
        if "arxiv.org/abs/" in arxiv_id:
            arxiv_id = arxiv_id.split("/abs/")[-1].split("v")[0]
        elif "arxiv.org/pdf/" in arxiv_id:
            arxiv_id = arxiv_id.split("/pdf/")[-1].replace(".pdf", "").split("v")[0]

        # Use id_list parameter for precise lookup
        xml_text = _fetch(f"id_list={quote(arxiv_id)}")
        entries = _parse_entries(xml_text)
        if not entries:
            raise ValueError(f"Paper not found: {arxiv_id}")
        return entries[0]
