
import requests
import pandas as pd

from io import StringIO


class GlobalClimateService:

    NASA_URL = (
        "https://data.giss.nasa.gov/gistemp/tabledata_v4/"
        "GLB.Ts+dSST.csv"
    )

    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    MONTHS = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ]

    # --------------------------------------------------
    # 1. DATOS HISTÓRICOS DE TEMPERATURA GLOBAL
    # --------------------------------------------------

    @staticmethod
    def get_temperature_data():

        try:
            response = requests.get(
                GlobalClimateService.NASA_URL,
                timeout=30
            )

            response.raise_for_status()

            lines = response.text.splitlines()

            header_index = next(
                index
                for index, line in enumerate(lines)
                if line.strip().startswith("Year,")
            )

            data = pd.read_csv(
                StringIO("\n".join(lines[header_index:])),
                na_values=["***", "****", "*****"]
            )

            data["Year"] = pd.to_numeric(
                data["Year"],
                errors="coerce"
            )

            data = data.dropna(subset=["Year"])
            data["Year"] = data["Year"].astype(int)

            return data

        except requests.RequestException as error:

            raise RuntimeError(
                "No se pudieron obtener los datos de NASA."
            ) from error

        except Exception as error:

            raise RuntimeError(
                "No se pudieron procesar los registros climáticos globales."
            ) from error

    # --------------------------------------------------
    # 2. RESUMEN CLIMÁTICO GLOBAL
    # --------------------------------------------------

    @staticmethod
    def get_global_summary():

        data = GlobalClimateService.get_temperature_data()

        annual_data = data.dropna(subset=["J-D"])

        if annual_data.empty:

            raise RuntimeError(
                "No hay registros anuales disponibles."
            )

        latest_annual = annual_data.iloc[-1]

        monthly_records = []

        for _, row in data.iterrows():

            for month in GlobalClimateService.MONTHS:

                value = row.get(month)

                if pd.notna(value):

                    monthly_records.append({
                        "year": int(row["Year"]),
                        "month": month,
                        "anomaly": round(float(value), 2)
                    })

        if not monthly_records:

            raise RuntimeError(
                "No hay registros mensuales disponibles."
            )

        latest_month = monthly_records[-1]

        historical = []

        for _, row in annual_data.iterrows():

            historical.append({
                "year": int(row["Year"]),
                "anomaly": round(float(row["J-D"]), 2)
            })

        return {
            "latest_annual": {
                "year": int(latest_annual["Year"]),
                "anomaly": round(
                    float(latest_annual["J-D"]),
                    2
                )
            },

            "latest_month": latest_month,

            "historical": historical[-30:],

            "source": "NASA GISTEMP v4",

            "reference_period": "1951-1980"
        }

    # --------------------------------------------------
    # 3. CONDICIONES METEOROLÓGICAS ACTUALES DEL MUNDO
    # --------------------------------------------------

    @staticmethod
    def get_global_conditions():

        regions = [

            {
                "region": "América del Norte",
                "city": "Nueva York",
                "country": "Estados Unidos",
                "latitude": 40.7128,
                "longitude": -74.0060
            },

            {
                "region": "América del Sur",
                "city": "São Paulo",
                "country": "Brasil",
                "latitude": -23.5505,
                "longitude": -46.6333
            },

            {
                "region": "Europa",
                "city": "Londres",
                "country": "Reino Unido",
                "latitude": 51.5072,
                "longitude": -0.1276
            },

            {
                "region": "África",
                "city": "Nairobi",
                "country": "Kenia",
                "latitude": -1.2921,
                "longitude": 36.8219
            },

            {
                "region": "Asia",
                "city": "Tokio",
                "country": "Japón",
                "latitude": 35.6762,
                "longitude": 139.6503
            },

            {
                "region": "Oceanía",
                "city": "Sídney",
                "country": "Australia",
                "latitude": -33.8688,
                "longitude": 151.2093
            }

        ]

        results = []
        errors = []

        for region in regions:

            try:

                response = requests.get(
                    GlobalClimateService.FORECAST_URL,

                    params={
                        "latitude": region["latitude"],
                        "longitude": region["longitude"],

                        "current": (
                            "temperature_2m,"
                            "relative_humidity_2m,"
                            "apparent_temperature,"
                            "precipitation,"
                            "wind_speed_10m"
                        ),

                        "timezone": "auto"
                    },

                    timeout=20
                )

                response.raise_for_status()

                data = response.json()

                current = data.get("current", {})

                results.append({

                    "region": region["region"],

                    "city": region["city"],
                    "country": region["country"],
                    "latitude": region["latitude"],
                    "longitude": region["longitude"],

                    "temperature": current.get(
                        "temperature_2m"
                    ),

                    "humidity": current.get(
                        "relative_humidity_2m"
                    ),

                    "feels_like": current.get(
                        "apparent_temperature"
                    ),

                    "precipitation": current.get(
                        "precipitation"
                    ),

                    "wind_speed": current.get(
                        "wind_speed_10m"
                    ),

                    "time": current.get("time")

                })

            except requests.RequestException:

                errors.append(region["city"])

        if not results:

            raise RuntimeError(
                "No se pudieron obtener las condiciones globales."
            )

        return {

            "regions": results,

            "errors": errors,

            "source": "Open-Meteo"

        }
