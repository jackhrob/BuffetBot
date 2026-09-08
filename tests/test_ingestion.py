"""Provider transport, pagination, source capture and normalization failure invariants."""

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from email.utils import format_datetime

import pytest
from pydantic import SecretStr, ValidationError

from buffetbot.alpaca_history import json_object
from buffetbot.config import AlpacaCredentials
from buffetbot.fixtures.alpaca import CAPTURE_TIME, SyntheticAlpaca, history_request
from buffetbot.ingestion import cache_key, ingest_history, member, publish_capture, read_capture
from buffetbot.ingestion_models import HistoricalRequest
from buffetbot.market_http import HOST, AlpacaHTTP, IngestionError, Response
from buffetbot.snapshots import inspect_snapshot, read_snapshot, research_view


def ingest(root, transport=None, request=None, **options):
    return ingest_history(
        root,
        request or history_request(),
        transport=transport if transport is not None else SyntheticAlpaca(),
        now=lambda: CAPTURE_TIME,
        **options,
    )


def test_paginated_regular_minutes_publish_with_exact_source_provenance(tmp_path):
    source = SyntheticAlpaca()
    result = ingest(tmp_path, source)
    snapshot = read_snapshot(tmp_path, result["dataset_id"])
    capture = read_capture(tmp_path, result["capture_id"])
    assert result["origin"] == capture.origin == "synthetic"
    assert len(source.calls) == len(capture.pages) == 6
    assert len(snapshot.bars) == 4 and len(snapshot.actions) == 2
    assert [
        (b.symbol, str(b.session), b.open, b.high, b.low, b.close, b.volume) for b in snapshot.bars
    ] == [
        ("BBTEST", "2024-07-02", 100, 110, 90, 105, 3900),
        ("BBTEST", "2024-07-03", 52, 56, 51, 55, 4200),
        ("ZZTEST", "2024-07-02", 200, 212, 198, 210, 11700),
        ("ZZTEST", "2024-07-03", 211, 215, 209, 213, 8400),
    ]
    assert all(b.first_ingested_at == CAPTURE_TIME for b in snapshot.bars)
    assert snapshot.bars[1].available_at.hour == 17 and snapshot.bars[1].available_at.minute == 15
    action_request = source.calls[-1][1]
    assert action_request["start"] == "1970-01-01" and action_request["data_quality"] == "all"
    assert "types" not in action_request
    dividend = next(a for a in snapshot.actions if a.kind == "cash_dividend")
    assert str(dividend.pay_date) == "2024-07-09"  # Pay date beyond bar coverage.
    # Both process dates fall outside the bar range; date filtering must use ex/effective dates.
    assert {a.action_id for a in snapshot.actions} == {"synthetic-split", "synthetic-dividend"}
    assert capture.pages[0].params["adjustment"] == "raw"
    assert capture.pages[0].params["feed"] == "sip"
    assert capture.pages[0].params["asof"] == "-"
    assert result["capture_id"] in snapshot.manifest.plan.retrieval_convention
    assert snapshot.reference().revision_policy == "unknown"
    assert {"unknown_revision_timing", "historical_action_timing_assumed"} <= set(
        snapshot.reference().limitations
    )
    report = inspect_snapshot(tmp_path, snapshot.dataset_id)
    assert report["quality"]["usable"] and report["origin"] == "synthetic"
    view = research_view(snapshot, cutoff=snapshot.bars[1].available_at)
    assert view["bars"][0]["close"] == "52.5"


def test_cache_is_network_free_and_refresh_preserves_previous_version(tmp_path):
    source = SyntheticAlpaca()
    first = ingest(tmp_path, source)
    old_files = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in (tmp_path / "snapshots" / first["dataset_id"]).iterdir()
    }

    class NoNetwork:
        origin = "synthetic"

        def get(self, *args):
            raise AssertionError("Cache hit must never reach transport")

    cached = ingest(tmp_path, NoNetwork(), cache_only=True)
    assert cached == dict(first, cache_hit=True)
    source.bars["2024-07-02"]["BBTEST"][0]["h"] = 111
    revised = ingest(tmp_path, source, refresh=True)
    assert revised["dataset_id"] != first["dataset_id"]
    assert revised["capture_id"] != first["capture_id"]
    assert read_snapshot(tmp_path, revised["dataset_id"]).bars[0].high == 111
    assert {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in (tmp_path / "snapshots" / first["dataset_id"]).iterdir()
    } == old_files
    assert publish_capture(tmp_path, first["capture_id"]).dataset_id == first["dataset_id"]


@pytest.mark.parametrize("damage", ["capture", "snapshot", "receipt", "version", "symlink"])
def test_corrupt_cached_inputs_are_rejected_without_silent_download(tmp_path, damage):
    first = ingest(tmp_path)
    index = member(tmp_path, "market-imports", first["request_id"])
    if damage == "capture":
        member(tmp_path, "market-captures", first["capture_id"]).write_text("{}")
    elif damage == "snapshot":
        (tmp_path / "snapshots" / first["dataset_id"] / "bars.parquet").unlink()
    elif damage in ("receipt", "version"):
        data = json.loads(index.read_text())
        data["request_id" if damage == "receipt" else "schema_version"] = (
            "f" * 64 if damage == "receipt" else True
        )
        index.write_text(json.dumps(data))
    else:
        original = tmp_path / "original-receipt.json"
        index.rename(original)
        index.symlink_to(original)
    source = SyntheticAlpaca()
    with pytest.raises(IngestionError):
        ingest(tmp_path, source)
    assert source.calls == []


def test_interrupted_download_and_failed_refresh_never_replace_success(tmp_path):
    first = ingest(tmp_path)
    index = member(tmp_path, "market-imports", first["request_id"])
    original = index.read_bytes()

    class Interrupted(SyntheticAlpaca):
        def get(self, path, params):
            if len(self.calls) == 1:
                raise IngestionError("retries_exhausted", "Synthetic interrupted read")
            return super().get(path, params)

    with pytest.raises(IngestionError):
        ingest(tmp_path, Interrupted(), refresh=True)
    assert index.read_bytes() == original
    assert len(list((tmp_path / "market-captures").glob("*.json"))) == 1
    assert read_snapshot(tmp_path, first["dataset_id"]).manifest.quality.usable


def test_crash_before_cache_index_leaves_replayable_capture_and_snapshot(tmp_path, monkeypatch):
    import buffetbot.ingestion as storage

    real_write = storage.atomic_write

    def stopped(path, data, *, immutable):
        if not immutable:
            raise OSError("simulated interrupted receipt write")
        return real_write(path, data, immutable=immutable)

    monkeypatch.setattr(storage, "atomic_write", stopped)
    with pytest.raises(IngestionError):
        ingest(tmp_path)
    assert not list((tmp_path / "market-imports").glob("*.json"))
    (capture_path,) = (tmp_path / "market-captures").glob("*.json")
    assert publish_capture(tmp_path, capture_path.stem).manifest.quality.usable


@pytest.mark.parametrize(
    "problem,code",
    [
        ("missing_minute", "missing_minutes"),
        ("missing_symbol", "missing_minutes"),
        ("duplicate", "duplicate_or_unordered_bar"),
        ("unordered", "duplicate_or_unordered_bar"),
        ("extended_hours", "outside_session"),
        ("negative_volume", "unsupported_records"),
        ("fractional_volume", "invalid_volume"),
        ("inconsistent_ohlc", "unsupported_records"),
    ],
)
def test_bad_minutes_retain_original_capture_but_never_publish(tmp_path, problem, code):
    source = SyntheticAlpaca()
    bars = source.bars["2024-07-02"]["BBTEST"]
    if problem == "missing_minute":
        del bars[50]
    elif problem == "missing_symbol":
        del source.bars["2024-07-02"]["ZZTEST"]
    elif problem == "duplicate":
        bars.insert(1, deepcopy(bars[0]))
    elif problem == "unordered":
        bars.reverse()
    elif problem == "extended_hours":
        bars[0]["t"] = "2024-07-02T13:29:00Z"
    elif problem == "negative_volume":
        bars[0]["v"] = -1
    elif problem == "fractional_volume":
        bars[0]["v"] = 1.5
    else:
        bars[0]["h"] = 1
    with pytest.raises(IngestionError) as error:
        ingest(tmp_path, source)
    assert error.value.code == code
    assert error.value.capture_id is not None
    assert read_capture(tmp_path, error.value.capture_id).origin == "synthetic"
    assert not (tmp_path / "snapshots").exists()
    assert not (tmp_path / "market-imports").exists()


@pytest.mark.parametrize(
    "problem,code",
    [
        ("repeat_token", "repeated_page"),
        ("repeat_body", "repeated_page"),
        ("empty_more", "empty_page"),
        ("missing_token", "incomplete_response"),
        ("empty", "missing_minutes"),
    ],
)
def test_pagination_errors_are_bounded_and_never_cache_success(tmp_path, problem, code):
    class Malformed(SyntheticAlpaca):
        def get(self, path, params):
            response = super().get(path, params)
            body = json.loads(response.body)
            if path == "/v2/stocks/bars":
                if problem == "repeat_token":
                    body["next_page_token"] = "400"
                elif problem == "repeat_body":
                    if not hasattr(self, "first_body"):
                        self.first_body = deepcopy(body["bars"])
                    body["bars"] = self.first_body
                    body["next_page_token"] = str(len(self.calls) * 400)
                elif problem == "empty_more":
                    body["bars"] = {}
                elif problem == "missing_token":
                    del body["next_page_token"]
                else:
                    body.update(bars={}, next_page_token=None)
            return Response(json.dumps(body).encode(), response.received_at)

    source = Malformed()
    with pytest.raises(IngestionError) as error:
        ingest(tmp_path, source)
    assert error.value.code == code
    assert len(source.calls) <= 6
    assert not (tmp_path / "market-imports").exists()


@pytest.mark.parametrize(
    "problem,code",
    [
        ("pay_date", "unsupported_records"),
        ("ex_date", "incomplete_actions"),
        ("special", "unsupported_dividend"),
        ("foreign", "unsupported_dividend"),
        ("fractional_split", "unsupported_split"),
        ("reverse_split", "unsupported_action"),
        ("duplicate", "duplicate_action"),
        ("due_bill", "unsupported_dividend"),
    ],
)
def test_incomplete_or_unsupported_actions_block_execution(tmp_path, problem, code):
    source = SyntheticAlpaca()
    dividend = source.actions["cash_dividends"][0]
    if problem == "pay_date":
        dividend["payable_date"] = None
    elif problem == "ex_date":
        del dividend["ex_date"]
    elif problem in ("special", "foreign"):
        dividend[problem] = True
    elif problem == "fractional_split":
        source.actions["forward_splits"][0]["new_rate"] = 1.5
    elif problem == "reverse_split":
        source.actions["reverse_splits"] = source.actions.pop("forward_splits")
    elif problem == "duplicate":
        copy = deepcopy(dividend)
        copy["rate"] = 2  # Different page payload, same native event ID.
        source.actions["cash_dividends"].append(copy)
    else:
        dividend["due_bill_on_date"] = "2024-07-03"
    with pytest.raises(IngestionError) as error:
        ingest(tmp_path, source)
    assert error.value.code == code
    assert error.value.capture_id is not None
    assert not (tmp_path / "snapshots").exists()


def test_iex_is_explicit_and_never_reuses_sip_or_historical_cache(tmp_path):
    sip = ingest(tmp_path)
    source = SyntheticAlpaca()
    request = history_request().model_copy(update={"feed": "iex"})
    iex = ingest(tmp_path, source, request)
    assert iex["dataset_id"] != sip["dataset_id"]
    assert all(params["feed"] == "iex" for path, params in source.calls if path.endswith("bars"))
    assert (
        "single_exchange_iex" in read_snapshot(tmp_path, iex["dataset_id"]).reference().limitations
    )
    with pytest.raises(IngestionError) as error:
        ingest_history(tmp_path, history_request(), cache_only=True)
    assert error.value.code == "cache_miss"  # Real transport cannot inherit synthetic cache.
    assert cache_key(request, "synthetic") != cache_key(request, "historical")


@pytest.mark.parametrize(
    "field,value",
    [
        ("feed", None),
        ("feed", "auto"),
        ("adjustment", "all"),
        ("interval", "1m"),
        ("aggregation", "daily"),
        ("schema_version", True),
    ],
)
def test_request_requires_explicit_supported_semantics(field, value):
    data = history_request().model_dump(mode="json")
    data[field] = value
    with pytest.raises(ValidationError):
        HistoricalRequest.model_validate(data)


def test_no_download_for_missing_warmup_listing_or_unfinished_sessions(tmp_path):
    for update, code in [
        ({"warmup_sessions": 2}, "insufficient_warmup"),
        (
            {
                "universe": (
                    history_request()
                    .universe[0]
                    .model_copy(update={"listed_on": history_request().first_execution_session}),
                )
            },
            "listing_coverage",
        ),
    ]:
        source = SyntheticAlpaca()
        with pytest.raises(IngestionError) as error:
            ingest(tmp_path, source, history_request().model_copy(update=update))
        assert error.value.code == code and source.calls == []
    source = SyntheticAlpaca()
    with pytest.raises(IngestionError) as error:
        ingest_history(
            tmp_path,
            history_request(),
            transport=source,
            now=lambda: CAPTURE_TIME.replace(year=2024, month=7, day=3, hour=17, minute=1),
        )
    assert error.value.code == "unfinished_range" and source.calls == []


def test_wire_decimal_parsing_is_exact_and_rejects_ambiguous_json():
    assert json_object('{"price":0.10000001}')["price"] == Decimal("0.10000001")
    for data in ('{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}', '{"bars":'):
        with pytest.raises(IngestionError):
            json_object(data)


class FakeReply:
    def __init__(self, status=200, headers=None, body=b'{"bars":{},"next_page_token":null}'):
        self.status, self.headers, self.body = status, headers or {}, body

    def getheaders(self):
        return list(self.headers.items())

    def read(self, size):
        return self.body[:size]


def http_client(replies):
    calls, waits = [], []
    clock = [0.0]

    class Connection:
        def __init__(self, host, timeout):
            assert host == HOST and timeout == 20

        def request(self, method, path, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        def close(self):
            pass

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    credentials = AlpacaCredentials(
        api_key=SecretStr("DUMMY_BB005_KEY"), api_secret=SecretStr("DUMMY_BB005_SECRET")
    )
    client = AlpacaHTTP(
        credentials,
        connection_factory=Connection,
        sleep=sleep,
        monotonic=lambda: clock[0],
        now=lambda: CAPTURE_TIME,
    )
    return client, calls, waits


def test_http_retries_honor_rate_headers_and_are_get_only(caplog):
    client, calls, waits = http_client(
        [
            FakeReply(
                429, {"Retry-After": "2", "X-RateLimit-Reset": str(CAPTURE_TIME.timestamp() + 3)}
            ),
            FakeReply(503),
            FakeReply(),
        ]
    )
    response = client.get("/v2/stocks/bars", {"feed": "sip", "page_token": "opaque+/=token"})
    assert response.received_at == CAPTURE_TIME and waits == [3.0, 2.0]
    assert all(method == "GET" and path.startswith("/v2/stocks/bars?") for method, path, _ in calls)
    assert "opaque%2B%2F%3Dtoken" in calls[0][1]
    assert "DUMMY_BB005" not in caplog.text
    with pytest.raises(IngestionError, match="fixed market-data"):
        client.get("/v2/orders", {})


@pytest.mark.parametrize("status", [301, 302, 400, 401, 402, 403, 404, 422])
def test_http_access_errors_and_redirects_never_retry_or_expose_provider_body(status, caplog):
    client, calls, waits = http_client(
        [FakeReply(status, {"Location": "https://another.invalid"}, b"DUMMY_BB005_SECRET")]
    )
    with pytest.raises(IngestionError) as error:
        client.get("/v1/corporate-actions", {})
    assert len(calls) == 1 and waits == []
    assert "DUMMY_BB005_SECRET" not in str(error.value) + caplog.text


@pytest.mark.parametrize("failure", [TimeoutError("DUMMY_BB005_SECRET"), FakeReply(500)])
def test_http_transient_failure_stops_after_three_attempts(failure):
    client, calls, waits = http_client([failure, failure, failure])
    with pytest.raises(IngestionError) as error:
        client.get("/v2/stocks/bars", {})
    assert error.value.code == "retries_exhausted"
    assert len(calls) == 3 and waits == [1.0, 2.0]
    assert "DUMMY_BB005_SECRET" not in str(error.value)


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"Retry-After": "31"}, "rate_limited"),
        ({"Retry-After": "NaN"}, "invalid_retry_hint"),
        ({"X-RateLimit-Reset": "Infinity"}, "invalid_retry_hint"),
    ],
)
def test_http_retry_hints_never_cause_early_or_unbounded_retries(headers, code):
    client, calls, waits = http_client([FakeReply(429, headers)])
    with pytest.raises(IngestionError) as error:
        client.get("/v2/stocks/bars", {})
    assert error.value.code == code and len(calls) == 1 and waits == []


def test_truncated_http_content_is_retried_and_oversized_pages_are_rejected():
    client, calls, _ = http_client(
        [FakeReply(headers={"Content-Length": "200"}, body=b"{}"), FakeReply()]
    )
    client.get("/v2/stocks/bars", {})
    assert len(calls) == 2
    client, calls, _ = http_client([FakeReply(body=b"x" * 4_000_001)])
    with pytest.raises(IngestionError) as error:
        client.get("/v2/stocks/bars", {})
    assert error.value.code == "response_too_large" and len(calls) == 1


def test_http_date_retry_after_and_pacing_are_honored():
    deadline = format_datetime(CAPTURE_TIME + timedelta(seconds=5), usegmt=True)
    client, calls, waits = http_client(
        [FakeReply(429, {"Retry-After": deadline}), FakeReply(), FakeReply()]
    )
    client.get("/v2/stocks/bars", {})
    client.get("/v1/corporate-actions", {})
    assert len(calls) == 3
    assert waits == pytest.approx([5.0, 0.35])


def test_cli_missing_credentials_and_cache_miss_are_honest_and_network_free(
    tmp_path, monkeypatch, capsys
):
    from buffetbot.cli import main

    for variable in ("BUFFETBOT_ALPACA_API_KEY", "BUFFETBOT_ALPACA_API_SECRET"):
        monkeypatch.delenv(variable, raising=False)
    config = tmp_path / "offline.toml"
    config.write_text('[paths]\ndata="data"\nstate="state"\nartifacts="artifacts"\n')
    request = tmp_path / "request.json"
    request.write_text(history_request().model_dump_json())

    def forbidden(*args):
        raise AssertionError("No HTTP GET is allowed")

    monkeypatch.setattr(AlpacaHTTP, "get", forbidden)
    arguments = ["datasets", "ingest", "--request", str(request), "--config", str(config)]
    assert main(arguments) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked" and report["code"] == "credentials_missing"
    assert main([*arguments, "--cache-only"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "cache_miss"
    assert not (tmp_path / "data").exists()


def test_cli_explicit_file_secrets_are_redacted_and_no_error_body_is_reported(
    tmp_path, monkeypatch, capsys
):
    from buffetbot.cli import main

    for variable in ("BUFFETBOT_ALPACA_API_KEY", "BUFFETBOT_ALPACA_API_SECRET"):
        monkeypatch.delenv(variable, raising=False)
    secret = "DUMMY_BB005_FILE_SECRET"
    config = tmp_path / "offline.toml"
    config.write_text('[paths]\ndata="data"\nstate="state"\nartifacts="artifacts"\n')
    secrets = tmp_path / "secrets.local.toml"
    secrets.write_text(f'[alpaca]\napi_key="DUMMY_KEY"\napi_secret="{secret}"\n')
    request = tmp_path / "request.json"
    request.write_text(history_request().model_dump_json())

    def rejected(self, path, params):
        assert self._credentials.api_secret.get_secret_value() == secret
        raise IngestionError("access_denied", f"Synthetic provider error containing {secret}")

    monkeypatch.setattr(AlpacaHTTP, "get", rejected)
    status = main(
        [
            "datasets",
            "ingest",
            "--request",
            str(request),
            "--config",
            str(config),
            "--secrets",
            str(secrets),
        ]
    )
    output = capsys.readouterr()
    assert status == 1 and secret not in output.out + output.err
    assert "[REDACTED]" in output.out and "Traceback" not in output.err


def test_cli_replays_a_capture_offline_and_preserves_synthetic_origin(
    tmp_path, monkeypatch, capsys
):
    from buffetbot.cli import main

    config = tmp_path / "offline.toml"
    config.write_text('[paths]\ndata="data"\nstate="state"\nartifacts="artifacts"\n')
    result = ingest(tmp_path / "data")

    def forbidden(*args):
        raise AssertionError("Replay must never contact a provider")

    monkeypatch.setattr(AlpacaHTTP, "get", forbidden)
    assert main(["datasets", "replay", result["capture_id"], "--config", str(config)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["replayed"] and report["origin"] == "synthetic"
    assert report["dataset_id"] == result["dataset_id"]
