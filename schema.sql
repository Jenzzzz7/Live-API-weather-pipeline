-- Table that load.py writes into: one row per city per hour.
-- Safe to run more than once: IF NOT EXISTS skips anything already created.

CREATE TABLE IF NOT EXISTS weather_hourly (
    city                  TEXT        NOT NULL,
    observed_at           TIMESTAMPTZ NOT NULL,   -- the hour the reading is for (UTC)
    temperature_2m        REAL,                   -- °C, 2 m above ground
    apparent_temperature  REAL,                   -- °C, "feels like"
    relative_humidity_2m  REAL,                   -- %
    precipitation         REAL,                   -- mm in that hour
    wind_speed_10m        REAL,                   -- km/h, 10 m above ground
    wind_gusts_10m        REAL,                   -- km/h
    surface_pressure      REAL,                   -- hPa
    cloud_cover           REAL,                   -- %
    loaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when we last wrote this row

    -- One row per (city, hour). This is what ON CONFLICT in load.py relies on.
    PRIMARY KEY (city, observed_at)
);

-- Speeds up "latest readings" queries for the dashboard.
CREATE INDEX IF NOT EXISTS weather_hourly_observed_at_idx
    ON weather_hourly (observed_at DESC);
