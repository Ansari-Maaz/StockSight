"""Service layer for MarketMind.

Everything that touches market data, news, or the forecasting model lives here so
the Django views stay thin and the pieces can be used from management commands,
tests, or a future REST/async worker without change.
"""
