# 职场招聘

LinkedIn。

## LinkedIn

```bash
# 获取个人资料
mcporter call 'linkedin.get_person_profile(linkedin_url: "https://linkedin.com/in/username")'

# 搜索人才
mcporter call 'linkedin.search_people(keyword: "AI engineer", limit: 10)'

# 获取公司资料
mcporter call 'linkedin.get_company_profile(linkedin_url: "https://linkedin.com/company/xxx")'

# 搜索职位
mcporter call 'linkedin.search_jobs(keyword: "software engineer", limit: 10)'
```

> **需要登录**: `mcp-server-linkedin` 需要有效的登录态。若尚未配置：
>
> ```bash
> mcporter config add linkedin --command uvx --arg mcp-server-linkedin@latest --env UV_HTTP_TIMEOUT=300 --scope home
> uvx mcp-server-linkedin@latest --login
> ```

### Fallback 方案

如果 MCP 不可用，可以用 Jina Reader：

```bash
curl -s "https://r.jina.ai/https://linkedin.com/in/username"
```
