"""The API client's caches, with the Jグランツ API replaced by a mock transport."""

import httpx
import pytest

from jgrants_util_mcp_server import api


@pytest.fixture
def client_and_requests():
    requests: list[httpx.Request] = []

    def handler(request):
        requests.append(request)
        if "/id/" in request.url.path:
            return httpx.Response(200, json={"result": [{"id": request.url.path.rsplit("/", 1)[1]}]})
        return httpx.Response(200, json={"result": [{"id": request.url.params["keyword"]}]})

    client = api.JGrantsClient(base_url="https://jgrants.test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, requests


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    return now


async def test_paging_one_search_requests_it_once(client_and_requests, clock):
    client, requests = client_and_requests
    params = {"keyword": "創業", "sort": "created_date", "order": "ASC", "acceptance": "1"}
    await client.search(params)
    await client.search(dict(reversed(params.items())))
    await client.search({**params, "keyword": "起業"})
    assert len(requests) == 2


async def test_searches_and_details_expire(client_and_requests, clock):
    client, requests = client_and_requests
    params = {"keyword": "創業"}
    await client.search(params)
    await client.detail("a0W1")
    clock[0] += api.SEARCH_CACHE_SECONDS
    await client.search(params)
    await client.detail("a0W1")
    assert len(requests) == 3
    clock[0] += api.DETAIL_CACHE_SECONDS
    await client.detail("a0W1")
    assert len(requests) == 4
