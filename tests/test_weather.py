
from app.services.weather_service import WeatherService

try:
    result = WeatherService.get_weather_by_city("Arroyito")

    print("\nCLIMAIA - PRUEBA METEOROLÓGICA")
    print("--------------------------------")

    print("Ciudad:", result["location"]["name"])
    print("País:", result["location"]["country"])

    current = result["weather"]["current"]

    print("Temperatura:", current["temperature"], "°C")
    print("Humedad:", current["humidity"], "%")
    print("Precipitación:", current["precipitation"], "mm")
    print("Viento:", current["wind_speed"], "km/h")

    print("\nPRONÓSTICO DE 7 DÍAS")

    for day in result["weather"]["forecast"]:
        print(
            day["date"],
            "| Máxima:", day["temperature_max"],
            "| Mínima:", day["temperature_min"],
            "| Lluvia:", day["precipitation"]
        )

except Exception as error:
    print("Error:", error)
