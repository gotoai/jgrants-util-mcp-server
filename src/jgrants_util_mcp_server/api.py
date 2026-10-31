"""The Jグランツ public API, as this server uses it.

Two endpoints, both unauthenticated GETs:
- `GET /v1/public/subsidies` searches subsidies.
- `GET /v1/public/subsidies/id/{id}` returns one subsidy, with its attachments
  inline as base64 — a detail with a few PDFs runs to hundreds of kilobytes, so
  details are cached briefly and attachments are never passed to the model whole.

Search has no server-side paging: every call returns the whole result set. It is
cached briefly too, so paging through one search costs one request and its pages
come from the same snapshot.

Allowed parameter values are taken from the official OpenAPI document,
https://developers.digital.go.jp/documents/jgrants/api/ (jgrants-api.yaml).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Literal, get_args

import httpx

BASE_URL = "https://api.jgrants-portal.go.jp/exp/v1/public"
PORTAL_URL = "https://www.jgrants-portal.go.jp/subsidy/{id}"

UsePurpose = Literal[
    "新たな事業を行いたい",
    "販路拡大・海外展開をしたい",
    "イベント・事業運営支援がほしい",
    "事業を引き継ぎたい",
    "研究開発・実証事業を行いたい",
    "人材育成を行いたい",
    "資金繰りを改善したい",
    "設備整備・IT導入をしたい",
    "雇用・職場環境を改善したい",
    "エコ・SDGs活動支援がほしい",
    "災害（自然災害、感染症等）支援がほしい",
    "教育・子育て・少子化支援がほしい",
    "スポーツ・文化支援がほしい",
    "安全・防災対策支援がほしい",
    "まちづくり・地域振興支援がほしい",
]

Industry = Literal[
    "農業、林業",
    "漁業",
    "鉱業、採石業、砂利採取業",
    "建設業",
    "製造業",
    "電気・ガス・熱供給・水道業",
    "情報通信業",
    "運輸業、郵便業",
    "卸売業、小売業",
    "金融業、保険業",
    "不動産業、物品賃貸業",
    "学術研究、専門・技術サービス業",
    "宿泊業、飲食サービス業",
    "生活関連サービス業、娯楽業",
    "教育、学習支援業",
    "医療、福祉",
    "複合サービス事業",
    "サービス業（他に分類されないもの）",
    "公務（他に分類されるものを除く）",
    "分類不能の産業",
]

Employees = Literal[
    "従業員数の制約なし",
    "5名以下",
    "20名以下",
    "50名以下",
    "100名以下",
    "300名以下",
    "900名以下",
    "901名以上",
]

Area = Literal[
    "全国",
    "北海道地方", "東北地方", "関東・甲信越地方", "東海・北陸地方", "近畿地方",
    "中国地方", "四国地方", "九州・沖縄地方",
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
    "海外",
]

SortField = Literal["acceptance_end_datetime", "acceptance_start_datetime", "created_date"]
SortOrder = Literal["ASC", "DESC"]
AttachmentKind = Literal["application_guidelines", "outline_of_grant", "application_form"]

ATTACHMENT_KINDS: tuple[str, ...] = get_args(AttachmentKind)

# The API joins several values of one filter with " / " (space, slash, space).
MULTI_VALUE_SEPARATOR = " / "

DETAIL_CACHE_SIZE = 16
DETAIL_CACHE_SECONDS = 600
SEARCH_CACHE_SIZE = 16
SEARCH_CACHE_SECONDS = 300


class JGrantsError(Exception):
    """A failure worth telling the model about in plain words."""


class _ExpiringCache:
    """A small LRU whose entries also expire, so a long-running server sees updates."""

    def __init__(self, size: int, seconds: float) -> None:
        self._size = size
        self._seconds = seconds
        self._entries: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    def get(self, key: Any) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry[0] >= self._seconds:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def put(self, key: Any, value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._size:
            self._entries.popitem(last=False)


class JGrantsClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 60.0) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._details = _ExpiringCache(DETAIL_CACHE_SIZE, DETAIL_CACHE_SECONDS)
        self._searches = _ExpiringCache(SEARCH_CACHE_SIZE, SEARCH_CACHE_SECONDS)

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "jgrants-util-mcp-server"},
            )
        return self._http

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = await self._client().get(f"{self._base_url}{path}", params=params)
        except httpx.TimeoutException as error:
            raise JGrantsError("The Jグランツ API did not answer in time.") from error
        except httpx.HTTPError as error:
            raise JGrantsError(f"Could not reach the Jグランツ API: {error}") from error
        if response.status_code == 404:
            raise JGrantsError("No subsidy with that id exists in Jグランツ.")
        if response.status_code >= 400:
            raise JGrantsError(f"The Jグランツ API answered HTTP {response.status_code}.")
        return response.json()

    async def search(self, params: dict[str, str]) -> list[dict[str, Any]]:
        key = tuple(sorted(params.items()))
        cached = self._searches.get(key)
        if cached is not None:
            return cached
        results = (await self._get("/subsidies", params)).get("result") or []
        self._searches.put(key, results)
        return results

    async def detail(self, subsidy_id: str) -> dict[str, Any]:
        cached = self._details.get(subsidy_id)
        if cached is not None:
            return cached
        result = (await self._get(f"/subsidies/id/{subsidy_id}")).get("result") or []
        if not result:
            raise JGrantsError("No subsidy with that id exists in Jグランツ.")
        detail = result[0]
        self._details.put(subsidy_id, detail)
        return detail
