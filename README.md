# jgrants-util-mcp-server

An MCP server for the public API of [Jグランツ (jGrants)](https://www.jgrants-portal.go.jp/),
Japan's government subsidy portal: search subsidies, read their details, and read the text
of their application guidelines.

Jグランツの公開APIを使って、補助金の検索・詳細の確認・公募要領の閲覧ができる MCP サーバーです。

> **Unofficial.** This project is not affiliated with or endorsed by the Digital Agency
> (デジタル庁), which operates Jグランツ. It is written from scratch against the
> [published API specification](https://developers.digital.go.jp/documents/jgrants/api/);
> it is not a fork of the Digital Agency's
> [jgrants-mcp-server](https://github.com/digital-go-jp/jgrants-mcp-server).

## Tools

| Tool | What it does |
|---|---|
| `load_guideline` | The usage guideline for the whole tool set: search strategy, details, attachments, what Jグランツ covers, and the conditions of use. It takes no arguments and always returns the whole guideline. |
| `search_subsidies` | Search by one keyword plus filters (area, industry, purpose, employee count); paged. |
| `get_subsidy_detail` | One subsidy's overview, eligibility, rate, amounts, dates, portal URL and attachment list. |
| `read_attachment` | The text of a PDF attachment, in pieces, with `next_offset` to continue. |

The server follows a *skill-style* layout. Its MCP `instructions` are one sentence
saying what the tools are for and to call `load_guideline` first. Everything that
concerns the tool set as a whole — including the conditions of use — lives in the
guideline, and each tool's description covers only that tool. Agents that load many MCP
servers keep only a short entry per server in their prompt, and read the guideline when
they need it.

## Run

Python 3.11 or later.

```bash
pip install -e .
jgrants-util-mcp-server --host 127.0.0.1 --port 8000      # Streamable HTTP at /mcp
jgrants-util-mcp-server --transport stdio                # for clients that start it themselves
```

Behind a reverse proxy, accept the public host name as well; otherwise the server's DNS
rebinding protection rejects requests whose `Host` is not localhost:

```bash
jgrants-util-mcp-server --host 127.0.0.1 --port 8000 --allowed-host demo.mcp.gotoai.com
```

When bound to a non-loopback address (for example `--host 0.0.0.0` on a LAN), that
protection is off; restrict access with a firewall or a proxy.

### In Kari

Add a custom extension of type **Streamable HTTP** with the URL `http://<host>:<port>/mcp`.
Give it an ASCII name such as `jgrants` — the name becomes part of every tool name the
agent sees.

## Conditions of use

These are in the guideline the agent reads; they apply to anyone presenting the results:

- Credit the source as 「出典：Jグランツ（jGrants）」.
- Treat the information as a reference; confirm the latest details on the subsidy's
  official page (`portal_url`) before applying.
- Avoid excessive repeated access to the API.

The Jグランツ API's own terms are published by the Digital Agency at
<https://www.jgrants-portal.go.jp/open-api>; they apply to whoever runs this server.

## Development

```bash
pip install -e ".[dev]"
pytest                    # offline tests
JGRANTS_LIVE=1 pytest     # also the live test against the real API
ruff check src tests
```

## License

MIT — see [LICENSE](LICENSE).
