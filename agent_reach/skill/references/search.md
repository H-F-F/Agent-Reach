# 搜索工具

Exa AI 搜索引擎。

## Exa AI 搜索

高质量 AI 搜索引擎，擅长技术和代码搜索。

```bash
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'
mcporter call 'exa.web_search_exa(query: "site:github.com code question", numResults: 5)'
```

### 使用场景

| 场景 | 参数 |
|-----|------|
| 网页搜索 | `web_search_exa(query: "...", numResults: 5)` |
| 技术资料搜索 | `web_search_exa(query: "技术问题", numResults: 5)` |
| GitHub 精确代码搜索 | 使用 `dev.md` 里的 `gh search code` |

### 特点

- 擅长英文内容和技术文档
- 可用 `site:github.com` 等限定词搜索公开技术资料
- 结果质量高

## 与其他搜索工具对比

| 工具 | 来源 | 适用场景 |
|-----|------|---------|
| Exa | agent-reach | 英文/技术/代码搜索 |
| 智谱搜索 | my-mcp-tools | 中文搜索 |
| GitHub 搜索 | agent-reach (dev.md) | 仓库/代码搜索 |
