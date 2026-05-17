# Heat Pump DHW — Slimme warmtepomp boiler integratie voor Home Assistant

Intelligente sturing van je warmtepomp boiler (warm tapwater) op basis van zonne-energie, dynamische stroomprijzen en douche-schema's.

## Functies

| Functie | Beschrijving |
|---------|-------------|
| ☀️ Zonne-energie modus | Verwarmt automatisch als er voldoende PV-overschot is |
| 🚀 Boost modus | Verhoogt doeltemperatuur tijdelijk bij groot overschot |
| 💶 Dynamische prijsmodus | Verwarmt als de stroomprijs onder een drempel valt (Zonneplan, etc.) |
| 🚿 Douche schema | Pre-heat zodat er altijd genoeg warm water is op het geplande tijdstip |
| 🦠 Legionella preventie | Wekelijkse run naar 65°C (configureerbaar dag/uur) |
| 🏖️ Vakantie modus | Houdt een minimale temperatuur aan bij afwezigheid |
| 📬 Push notificaties | Melding bij sessie start/einde, legionella run en storingen |
| 📊 Energie tracking | kWh en kosten per sessie + maandelijkse besparing |
| 🧠 Slim herstel | Leert hoe lang opwarmen duurt en start op het juiste moment |

## Installatie

### Via HACS (aanbevolen)

1. Voeg deze repository toe als aangepaste repository in HACS
2. Installeer "Heat Pump DHW"
3. Herstart Home Assistant
4. Ga naar **Instellingen → Integraties → Voeg toe → Heat Pump DHW**

### Handmatig

1. Kopieer de map `custom_components/heatpump_dhw/` naar je HA `custom_components/` map
2. Kopieer `www/heatpump-dhw-card/` naar je HA `www/` map
3. Herstart Home Assistant

## Verwachte sensor formaten

Hieronder staat per sensor welke eenheid en welk formaat verwacht wordt. Verkeerde eenheden zorgen ervoor dat de sturing niet werkt.

### Hardware sensoren

| Sensor | Eenheid | Formaat | Voorbeeld |
|--------|---------|---------|-----------|
| Boiler watertemperatuur | `°C` | Decimaal getal | `54.3` |
| Vermogen / verbruik | `W` | Geheel of decimaal getal | `850` |

### Hardware bediening

| Entiteit | Type | Waardebereik | Voorbeeld |
|----------|------|-------------|-----------|
| Gewenste temperatuur | `number` of `input_number` | `35` – `80` °C | `55` |
| Warmtepomp schakelaar | `switch` of `input_boolean` | `on` / `off` | — |
| E-heater schakelaar | `switch` of `input_boolean` | `on` / `off` | — |
| E-heater boost temperatuur | `number` of `input_number` | °C | `65` |

### Zon & dynamische prijzen

| Sensor | Eenheid | Formaat | Voorbeeld | Veelgebruikte integratie |
|--------|---------|---------|-----------|--------------------------|
| PV opwekking | `W` | Geheel getal, **positief** | `2400` | Omvormer / SolarEdge / Growatt |
| PV overschot | `W` | Geheel getal, **positief** = overschot naar net | `1100` | Omvormer / DSMR / P1 |
| Huidige stroomprijs | `€/kWh` | Decimaal getal, **inclusief BTW en belasting** | `0.087` | Zonneplan, Tibber, ENTSO-E |
| Prijsvoorspelling | `€/kWh` | Decimaal getal | `0.065` | Zonneplan, Tibber |

> **Belangrijk voor de prijssensor:** De waarde moet in **€/kWh** zijn, inclusief alle belastingen en BTW. Bij Zonneplan is dit de sensor `sensor.zonneplan_current_electricity_price` (staat al in de juiste eenheid). Bij Tibber gebruik je `sensor.tibber_..._current_price`. Controleer altijd of de eenheid `€/kWh` toont in de HA entiteit — als het `ct/kWh` of een andere eenheid is, werkt de drempelwaarde niet correct.

#### Prijsvoorspelling sensor — ondersteunde formaten

De prijsvoorspelling sensor (`price_forecast_sensor`) wordt gebruikt voor de "goedkoopste X uur" modus. De integratie herkent automatisch welk formaat de sensor gebruikt:

**Zonneplan app** — attribuut `forecast` met `datetime` en `electricity_price` (in miljoensten van een euro):
```json
[{"datetime": "2024-01-15T14:00:00+01:00", "electricity_price": 87500}, ...]
```
Gebruik hiervoor `sensor.zonneplan_current_electricity_tariff`.

**Zonneplan template** — attributen `prices_today` en `prices_tomorrow` met `time` en `price`:
```json
[{"time": "2024-01-15T14:00:00+01:00", "price": 0.087}, ...]
```

**Nordpool / ENTSO-E** — attributen `raw_today` en `raw_tomorrow` met `start` en `value`:
```json
[{"start": "2024-01-15T14:00:00+01:00", "value": 0.087}, ...]
```

**Tibber** — attributen `prices` of `price_info` met `startsAt` en `total`:
```json
[{"startsAt": "2024-01-15T14:00:00+01:00", "total": 0.087}, ...]
```

**Generieke fallback** — als geen van de bovenstaande formaten herkend wordt, scant de integratie automatisch alle list-attributen op bekende veld-namen (`start`, `time`, `datetime`, `startsAt`, `hour` voor tijd; `price`, `value`, `total`, `amount` voor prijs). Werkt met vrijwel elke energieprijs-sensor.

Als er geen voorspelling beschikbaar is, valt de prijsmodus terug op de gewone drempelwaarde (huidige prijs ≤ maximum prijs).

### Optionele sensoren

| Sensor | Type | Verwachte waarde | Voorbeeld |
|--------|------|-----------------|-----------|
| Weersverwachting | `weather` entiteit | HA standaard weather | `weather.thuis` |
| Buitentemperatuur | `°C` | Decimaal getal | `12.5` |
| Aanwezigheid | `binary_sensor`, `person`, `device_tracker` of `input_boolean` | `on` / `home` = thuis | `binary_sensor.iemand_thuis` |

> **Aanwezigheid:** De integratie beschouwt de volgende states als "thuis": `on`, `home`, `true`. Alles anders (bijv. `off`, `not_home`) activeert de vakantie modus als die ingeschakeld staat.

---

## Configuratie

De integratie wordt ingesteld via een UI wizard met 5 stappen:

1. **Hardware sensoren** — boiler temperatuur, verbruiksmeter
2. **Hardware bediening** — doeltemperatuur, warmtepomp schakelaar, elektrisch element
3. **Zon & prijzen** — PV overschot sensor, prijsvoorspelling sensor, huidige prijs sensor
4. **Optionele sensoren** — weer, aanwezigheid, notificatie service
5. **Drempelwaarden** — overschot drempel, prijsdrempel, temperaturen

Na installatie zijn alle instellingen aanpasbaar via **Instellingen → Integraties → Heat Pump DHW → Configureren**:
- **Drempelwaarden & temperaturen** — alle drempelwaarden, temperaturen én sensoren (prijsvoorspelling, huidige prijs)
- **Douche schema's** — tot 3 douche-momenten met tijd, dagen en temperatuur

## Dashboard card

Voeg de Lovelace card toe als resource:

```yaml
# configuration.yaml of via UI
lovelace:
  resources:
    - url: /local/heatpump-dhw-card/heatpump-dhw-card.js
      type: module
```

Gebruik in Lovelace:

```yaml
type: custom:heatpump-dhw-card
title: Warmtepomp Boiler
temp_sensor: sensor.dhw_boiler_temp
mode_sensor: sensor.dhw_active_mode
status_sensor: sensor.dhw_status_text
power_sensor: sensor.dhw_power_w
session_kwh_sensor: sensor.dhw_session_kwh
session_cost_sensor: sensor.dhw_session_cost
session_savings_sensor: sensor.dhw_session_savings
monthly_savings_sensor: sensor.dhw_monthly_savings
next_heating_sensor: sensor.dhw_next_heating
heat_up_sensor: sensor.dhw_heat_up_duration_min
solar_switch: switch.dhw_solar_mode
price_switch: switch.dhw_price_mode
boost_switch: switch.dhw_boost_mode
vacation_switch: switch.dhw_vacation_mode
legionella_switch: switch.dhw_legionella_mode
```

## Douche schema instellen

Ga naar **Instellingen → Integraties → Heat Pump DHW → Configureren** en voeg douche-tijden toe.
Per schema stel je in:
- Tijdstip (bijv. 07:30)
- Dagen van de week
- Vereiste temperatuur

De integratie berekent automatisch wanneer het voorverwarmen moet starten op basis van de geleerde opwarmtijd.

## Vakantie modus

De vakantie modus houdt de boiler op een minimale temperatuur (standaard 40°C) bij afwezigheid.

**Automatische activering** — als je een aanwezigheid-sensor hebt ingesteld en deze geeft langer dan de ingestelde drempel (standaard 24 uur) `off`/`not_home` aan, activeert de vakantie modus automatisch.

**Handmatige schakelaar** — zet `switch.dhw_vacation_mode` aan voor een geplande vakantie.

**Op afstand uitzetten** — zet de schakelaar uit via de HA app. De auto-detectie reset direct en de integratie valt terug op de normale schema's (douche-schema's, prijsmodus).

**Douche schema's tijdens vakantie** — schema's worden automatisch overgeslagen zolang vakantie modus actief is. Na het uitzetten van de modus worden schema's weer normaal uitgevoerd.

**Status** — de status-sensor toont `Vakantie — minimum 40°C` zolang de modus actief is, ook als de boiler al op temperatuur is en niet actief verwarmt.

## Prioriteitsvolgorde

Als meerdere modi tegelijk van toepassing zijn, geldt:

1. Anti-blokkeer run (pompe te lang stil geweest)
2. Legionella preventie (veiligheid, ook tijdens vakantie)
3. Boost modus (groot zonne-overschot)
4. Zonne-energie modus
5. Dynamische prijsmodus
6. Vakantie modus (minimum temperatuur)
7. Douche schema (overgeslagen tijdens vakantie)
8. Standby

## Vereiste entiteiten (minimaal)

- Boiler watertemperatuur sensor
- Warmtepomp aan/uit schakelaar
- Gewenste temperatuur instelling (number/input_number)

Alle andere sensoren en schakelaars zijn optioneel — hoe meer je koppelt, hoe slimmer de sturing.
