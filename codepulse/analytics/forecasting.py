"""Transparent least-squares forecasts; avoids a heavy ML dependency."""
from __future__ import annotations

import numpy as np
import pandas as pd


def growth_forecast(history: pd.DataFrame, horizon_days: int = 30) -> pd.DataFrame:
    if history.empty or len(history) < 2:
        return pd.DataFrame(columns=["period", "stars", "forecast"])
    data = history.sort_values("period").copy()
    x = (data["period"] - data["period"].min()).dt.days.to_numpy()
    slope, intercept = np.polyfit(x, data["stars"].to_numpy(), 1)
    future_x = np.arange(x[-1] + 1, x[-1] + horizon_days + 1)
    future_dates = data["period"].min() + pd.to_timedelta(future_x, unit="D")
    forecast = pd.DataFrame({"period": future_dates, "stars": np.nan, "forecast": np.maximum(0, slope * future_x + intercept)})
    observed = data[["period", "stars"]].assign(forecast=np.nan)
    return pd.concat([observed, forecast], ignore_index=True)
