from __future__ import annotations

from collections.abc import Iterable

from app.config.reference import ProviderSettingsConfig
from app.domain.provider import DateRange, FetchRequest, FetchResult
from app.providers.base import ProviderContractError
from app.providers.http import RetryingHttpFetcher


DATASET_KEY = "bank_of_canada:valet_daily_fx"
ENDPOINT_NAME = "valet-observations"


class ValetClient:
    """Build bounded Valet observation requests from declarative settings."""

    def __init__(
        self,
        settings: ProviderSettingsConfig,
        fetcher: RetryingHttpFetcher,
        *,
        supports_grouped_series: bool = True,
    ) -> None:
        self._settings = settings
        self._fetcher = fetcher
        self._supports_grouped_series = supports_grouped_series

    def build_requests(
        self, series: Iterable[str], date_range: DateRange
    ) -> tuple[FetchRequest, ...]:
        symbols = tuple(dict.fromkeys(symbol.strip() for symbol in series if symbol.strip()))
        if not symbols:
            raise ProviderContractError("Valet request requires at least one series")
        if (date_range.end - date_range.start).days + 1 > self._settings.max_range_days:
            raise ProviderContractError(
                "Valet request exceeds configured date range",
                context={"dataset": DATASET_KEY},
            )
        groups = (symbols,) if self._supports_grouped_series else tuple((item,) for item in symbols)
        return tuple(self._request(group, date_range) for group in groups)

    async def fetch(self, request: FetchRequest) -> FetchResult:
        return await self._fetcher.fetch(request)

    def _request(self, symbols: tuple[str, ...], date_range: DateRange) -> FetchRequest:
        joined = ",".join(symbols)
        template = self._settings.endpoint_template
        try:
            path = template.format(series=joined, format="json")
        except (KeyError, ValueError) as exc:
            raise ProviderContractError("invalid Valet endpoint template") from exc
        # Valet's JSON representation is a path suffix. Keeping it here makes the
        # format explicit without requiring business services to know URL syntax.
        if "{format}" not in template and not path.rstrip("/").endswith("/json"):
            path = f"{path.rstrip('/')}/json"
        if not path.startswith("/"):
            path = f"/{path}"
        return FetchRequest(
            dataset=DATASET_KEY,
            instruments=symbols,
            date_range=date_range,
            endpoint_name=ENDPOINT_NAME,
            path=path,
            parameters={
                "start_date": date_range.start.isoformat(),
                "end_date": date_range.end.isoformat(),
            },
        )
