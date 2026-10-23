"""Tymczasowa próba W12: woła percentile z proportion pozycyjnie, jak przed zmianą sygnatury."""

from rozliczenia.telemetry import percentile

MEDIANA = percentile([1.0, 2.0, 3.0], 0.5)
