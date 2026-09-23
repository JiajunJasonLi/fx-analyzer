from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.application.ingestion.orchestrator import PipelineBinding
from app.config.reference import ReferenceConfiguration
from app.database.models import Currency, FxPair, FxSeries, IngestionRun, IngestionScope, InterestRateSeries
from app.domain.provider import DateRange, ReferenceSnapshot
from app.domain.validation import validate_fx_candidate, validate_policy_rate_candidate
from app.providers.bank_of_canada import ValetClient, ValetMapper, ValetParser, ValetSeriesMapping
from app.providers.bis import BISClient, BISMapper, BISParser, BISSeriesMapping
from app.providers.http import HttpPolicy, RetryingHttpFetcher, create_async_client


class ClosingFetcher:
    """Close the scope-owned HTTP connection after its one bounded request."""

    def __init__(self, client: httpx.AsyncClient, fetcher: RetryingHttpFetcher) -> None:
        self.client, self.fetcher = client, fetcher

    async def fetch(self, request: Any) -> Any:
        try:
            return await self.fetcher.fetch(request)
        finally:
            await self.client.aclose()


class RuntimeBindingFactory:
    def __init__(self, sessions: sessionmaker[Session], config: ReferenceConfiguration) -> None:
        self.sessions, self.config = sessions, config

    def __call__(self, run: IngestionRun, scope: IngestionScope) -> PipelineBinding:
        del run
        return self._fx(scope) if scope.scope_type == "fx" else self._bis(scope)

    def _transport(self, dataset_key: str, *, accept: str | None = None) -> ClosingFetcher:
        settings = next(item.settings for item in self.config.provider_datasets if item.key == dataset_key)
        assert settings is not None
        policy = HttpPolicy(read_timeout=settings.timeout_seconds, max_attempts=settings.max_attempts)
        client = create_async_client(
            settings.base_url,
            policy,
            headers={"Accept": accept} if accept is not None else None,
        )
        return ClosingFetcher(client, RetryingHttpFetcher(client, policy))

    def _fx(self, scope: IngestionScope) -> PipelineBinding:
        dataset_key = "bank_of_canada:valet_daily_fx"
        settings = next(item.settings for item in self.config.provider_datasets if item.key == dataset_key)
        assert settings is not None
        with self.sessions() as session:
            series = session.get(FxSeries, scope.series_id)
            if series is None:
                raise ValueError("FX scope references missing series")
            pair = session.get(FxPair, series.fx_pair_id)
            assert pair is not None
            base, quote = session.get(Currency, pair.base_currency_id), session.get(Currency, pair.quote_currency_id)
            assert base is not None and quote is not None
        configured = next(item for item in self.config.fx_series if item.provider_symbol == series.provider_symbol)
        mapping = ValetSeriesMapping(series.id, series.provider_symbol, configured.pair, base.code, quote.code)
        provider = ValetClient(settings, self._transport(dataset_key))  # type: ignore[arg-type]
        request = provider.build_requests((series.provider_symbol,), DateRange(scope.start_date, scope.end_date))[0]
        return PipelineBinding(
            request, provider, ValetParser(), ValetMapper(),
            ReferenceSnapshot({series.provider_symbol: mapping}), {series.id: configured.stable_key},
            lambda candidate: validate_fx_candidate(candidate, base_currency=base.code,
                quote_currency=quote.code, known_series_ids=(series.id,)),
        )

    def _bis(self, scope: IngestionScope) -> PipelineBinding:
        dataset_key = "bis:bis_policy_rates_daily"
        settings = next(item.settings for item in self.config.provider_datasets if item.key == dataset_key)
        assert settings is not None
        with self.sessions() as session:
            series = session.get(InterestRateSeries, scope.series_id)
            if series is None:
                raise ValueError("policy scope references missing series")
        configured = next(item for item in self.config.interest_rate_series
                          if item.dataflow_key == series.dataflow_key and item.series_key == series.series_key)
        mapping = BISSeriesMapping(series.id, series.dataflow_key, series.series_key,
            configured.economy, configured.currency, date(1900, 1, 1))
        media_type = "application/vnd.sdmx.data+json;version=1.0.0"
        provider = BISClient(self._transport(dataset_key, accept=media_type), dataset=dataset_key,
            dataflow=series.dataflow_key, endpoint_template=settings.endpoint_template,
            max_range_days=settings.max_range_days, media_type=media_type)  # type: ignore[arg-type]
        request = provider.requests((series.series_key,), DateRange(scope.start_date, scope.end_date))[0]
        return PipelineBinding(
            request, provider, BISParser(
                dataflow=series.dataflow_key,
                configured_dimension_order=("FREQ", "REF_AREA"),
                configured_currency=configured.currency,
                configured_collection_indicator=configured.collection_indicator,
                configured_unit="percent",
            ), BISMapper(),
            ReferenceSnapshot({"bis_series": (mapping,), "retrieved_at": datetime.now(timezone.utc)}),
            {series.id: configured.stable_key},
            lambda candidate: validate_policy_rate_candidate(candidate, known_series_ids=(series.id,)),
        )
