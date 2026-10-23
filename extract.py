import openmeteo_requests
import pandas as pd
import requests
from retry_requests import retry

# City name -> (latitude, longitude)
CITIES = {
    'Halifax': (44.6427, -63.5769),
    'Toronto': (43.65, -79.38),
    'Vancouver': (49.28, -123.12),
}

# The measurements we want, one value per hour
VARIABLES = [
    'temperature_2m',
    'apparent_temperature',
    'relative_humidity_2m',
    'precipitation',
    'wind_speed_10m',
    'wind_gusts_10m',
    'surface_pressure',
    'cloud_cover',
]

URL = 'https://api.open-meteo.com/v1/forecast'

# Retry failed requests automatically. No cache, so every run gets fresh data.
session = retry(requests.Session(), retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=session)


def fetch_weather(city, lat, lon):
    params = {
        'latitude': lat,
        'longitude': lon,
        'hourly': VARIABLES,
        'timezone': 'UTC',
        'past_days': 2,
        'forecast_days': 1,
    }
    response = openmeteo.weather_api(URL, params=params)[0]
    hourly = response.Hourly()

    # Build the column of hourly timestamps from start, end and interval
    data = {
        'observed_at': pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit='s', utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit='s', utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive='left',
        )
    }

    # Read each variable by its position in VARIABLES, so order cannot drift
    for i, name in enumerate(VARIABLES):
        data[name] = hourly.Variables(i).ValuesAsNumpy()

    df = pd.DataFrame(data)
    df.insert(0, 'city', city)

    # Keep only hours that have already happened (drop forecast hours)
    return df[df['observed_at'] <= pd.Timestamp.now(tz='UTC')]


if __name__ == '__main__':
    frames = [fetch_weather(city, lat, lon) for city, (lat, lon) in CITIES.items()]
    weather = pd.concat(frames, ignore_index=True)
    print(weather.head())
    print(f'\n{len(weather)} rows, {weather["city"].nunique()} cities')
    print(f'Latest hour: {weather["observed_at"].max()}')