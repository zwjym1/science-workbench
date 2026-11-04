"""Collector boundary: adapters normalize input; they never control a browser."""
from typing import Protocol
from .schemas import StandardData
from .csv_adapter import CsvAdapter

class CollectorAdapter(Protocol):
    def normalize(self, payload: dict) -> StandardData: ...

class StandardJsonAdapter:
    def normalize(self, payload: dict) -> StandardData:
        return StandardData.model_validate(payload)

ADAPTERS: dict[str, CollectorAdapter] = {'standard-json': StandardJsonAdapter(), 'standard-csv': CsvAdapter()}
