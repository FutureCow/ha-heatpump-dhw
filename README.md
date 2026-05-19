# Heat Pump DHW — Slimme warmtepomp boiler integratie voor Home Assistant

Intelligente sturing van je warmtepomp boiler (warm tapwater) op basis van zonne-energie, dynamische stroomprijzen en douche-schema's.

## Functies

| Functie | Beschrijving |
|---------|-------------|
| ☀️ Zonne-energie modus | Verwarmt automatisch als er voldoende PV-overschot is |
| 🚀 Boost modus | Verhoogt doeltemperatuur tijdelijk bij groot overschot; activeer optioneel elektrisch element |
| 💶 Dynamische prijsmodus | Verwarmt in de goedkoopste uren/kwartieren (15/30/60 min prijsresolutie, automatisch herkend) |
| 🔢 Niet-aaneengesloten uren | Kies de N goedkoopste losse uren — dure tussenuren worden overgeslagen |
| 🧱 Aaneengesloten blok | Optioneel: verwarmt in het goedkoopste aaneengesloten tijdblok |
| 🚿 Douche schema | Pre-heat zodat er altijd genoeg warm water is op het geplande tijdstip |
| 🦠 Legionella preventie | Wekelijkse run naar 65°C (configureerbaar dag/uur) |
| 🏖️ Vakantie modus | Houdt een minimale temperatuur aan bij afwezigheid |
| 📬 Push notificaties | Melding bij sessie start/einde, legionella run en storingen |
| 📊 Energie tracking | kWh en kosten per sessie, maand en jaar — nauwkeuriger met energiemeter sensor |
| 🧠 Slim leren | Leert opwarmtijd, verwarmingssnelheid en warmteverlies tank uit metingen |
| ⚡ COP berekening | Berekent en logt de coefficient of performance per sessie |
| 🛡️ Anti-blokkeer | Korte verplichte run als de pomp te lang stilstond |

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
| Energiemeter (optioneel) | `kWh` | Cumulatieve teller | `1234.5` |

> **Energiemeter sensor:** Als je een kWh-meter hebt op je boiler, geef die dan op. De integratie berekent dan het verbruik per sessie nauwkeuriger dan via de vermogenssensor.

### Hardware bediening

| Entiteit | Type | Waardebereik | Voorbeeld |
|----------|------|-------------|-----------|
| Gewenste temperatuur | `number` of `input_number` | `35` – `80` °C | `55` |
| Warmtepomp schakelaar | `switch` of `input_boolean` | `on` / `off` | — |
| E-heater schakelaar (optioneel) | `switch` of `input_boolean` | `on` / `off` | — |
| E-heater setpoint entiteit (optioneel) | `number` of `input_number` | °C | `65` |

> **E-heater setpoint:** Sommige boilers activeren het elektrisch element alleen als een apart setpoint hoger wordt ingesteld dan de warmtepomp-setpoint. Geef in dat geval de bijbehorende entiteit op.

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

De integratie bevat een kant-en-klare Lovelace card met:

- 🔥 **Verwarmingsindicator** — pulserende vlam als er actief verwarmd wordt, druppel bij standby
- 🌡️ **Temperatuurbalk** — huidige boilertemperatuur met een gekleurde marker voor de doeltemperatuur
- 📊 **Prijsgrafiek** — de komende 24 uur als gekleurde staven (groen = goedkoop, rood = duur), met markering voor geplande verwarmingsblokken en het volgende verwarmingsmoment
- ⚡ **Sessiestatistieken** — kWh verbruik, kosten en huidig vermogen
- 🔘 **Modusschakelaars** — directe bediening van alle modi

### Installatie

**Stap 1 — JavaScript resource toevoegen**

Via de UI: **Instellingen → Dashboards → Drie-puntjes (⋮) → Resources → Toevoegen**

Of in `configuration.yaml`:
```yaml
lovelace:
  resources:
    - url: /local/heatpump-dhw-card/heatpump-dhw-card.js
      type: module
```

Herstart Home Assistant na het toevoegen.

**Stap 2 — Card toevoegen aan je dashboard**

```yaml
type: custom:heatpump-dhw-card
title: Warmtepomp Boiler
temp_sensor: sensor.dhw_boiler_temp
mode_sensor: sensor.dhw_active_mode
status_sensor: sensor.dhw_status_text
power_sensor: sensor.dhw_power_w              # optioneel
session_kwh_sensor: sensor.dhw_session_kwh
session_cost_sensor: sensor.dhw_session_cost
next_heating_sensor: sensor.dhw_next_heating
heat_up_sensor: sensor.dhw_heat_up_duration_min  # optioneel
price_forecast_sensor: sensor.zonneplan_current_electricity_tariff  # voor prijsgrafiek
target_temp_sensor: number.boiler_setpoint    # optioneel, doeltemperatuur in grafiek
cheap_hours: 2                                # optioneel, goedkoopste N blokken markeren
solar_switch: switch.dhw_solar_mode
price_switch: switch.dhw_price_mode
boost_switch: switch.dhw_boost_mode
vacation_switch: switch.dhw_vacation_mode
legionella_switch: switch.dhw_legionella_mode
heat_now_button: button.heat_pump_dhw_airwell_zet_aan  # optioneel, directe verwarmingsknop
```

### Configuratie-opties

| Optie | Vereist | Beschrijving |
|-------|---------|-------------|
| `temp_sensor` | ✅ | Boiler watertemperatuur sensor |
| `mode_sensor` | ✅ | Actieve modus sensor (`sensor.dhw_active_mode`) |
| `status_sensor` | aanbevolen | Status tekst sensor |
| `power_sensor` | — | Huidig vermogen in W |
| `session_kwh_sensor` | — | kWh verbruik huidige sessie |
| `session_cost_sensor` | — | Kosten huidige sessie |
| `next_heating_sensor` | aanbevolen | Timestamp volgende geplande verwarming |
| `heat_up_sensor` | — | Gemiddelde opwarmtijd in minuten |
| `price_forecast_sensor` | — | Prijsvoorspelling sensor (zelfde als in integratie-configuratie) — activeert de prijsgrafiek |
| `target_temp_sensor` | — | Setpoint-entiteit van de boiler; als niet opgegeven wordt de doeltemperatuur uit de statustekst gehaald |
| `cheap_hours` | — | Hoeveel goedkoopste blokken in de grafiek te markeren (standaard `2`) |
| `solar_switch` | — | Schakelaar zonne-energiemodus |
| `price_switch` | — | Schakelaar prijsmodus |
| `boost_switch` | — | Schakelaar boost modus |
| `vacation_switch` | — | Schakelaar vakantie modus |
| `legionella_switch` | — | Schakelaar legionella preventie |
| `heat_now_button` | — | `button` entiteit om direct te starten met verwarmen |

### Prijsgrafiek

De grafiek toont de komende uren op basis van de `price_forecast_sensor`. De slot-grootte (15/30/60 min) wordt automatisch herkend.

| Element | Betekenis |
|---------|-----------|
| Groene staaf | Goedkoop uur/kwartier |
| Rode staaf | Duur uur/kwartier |
| **▼** groen driehoekje | Goedkoopste N slots — hier plant de integratie de verwarming |
| Oranje ring | Huidig slot, boiler is actief aan het verwarmen |
| Grijze ring | Huidig slot, boiler staat op standby |
| 🔥 vlammetje | Volgende geplande verwarmingsmoment |

## Alle instellingen (drempelwaarden & opties)

Alle onderstaande opties zijn instelbaar via **Instellingen → Integraties → Heat Pump DHW → Configureren → Drempelwaarden & temperaturen**.

### Zonne-energie modus

| Instelling | Standaard | Beschrijving |
|-----------|-----------|-------------|
| Zonne-energie modus | aan | Verwarmt automatisch bij voldoende PV-overschot |
| Min. overschot voor zonne-modus (W) | `500` | Minimaal PV-overschot voordat de boiler start |
| Boost modus | aan | Activeert boost (hoger setpoint / e-heater) bij groot overschot |
| Overschot voor boost (W) | `2000` | Overschotdrempel voor boost modus |

### Dynamische prijsmodus

| Instelling | Standaard | Beschrijving |
|-----------|-----------|-------------|
| Dynamische prijs modus | aan | Verwarmt in de goedkoopste uren |
| Maximale prijs (€/kWh) | `0.10` | Bovengrens: verwarmt alleen als prijs ≤ deze waarde (fallback zonder forecast) |
| Uren prijsmodus fallback | `2` | Aantal goedkoopste uren als de verwarmingssnelheid nog niet geleerd is (`0` = automatisch op basis van geleerde snelheid) |
| Prijsvenster douche schema (uur) | `24` | Hoe ver vooruit de forecast doorzocht wordt voor douche-planning (`0` = volledige beschikbare forecast) |
| Prijsmodus: goedkoopste aaneengesloten blok | uit | Als aan: verwarmt in het goedkoopste aaneengesloten blok in plaats van losse goedkoopste uren |

> **Slot-resolutie:** De prijsmodus ondersteunt automatisch 15-, 30- en 60-minuut prijsresolutie. De resolutie wordt per forecast automatisch herkend — geen configuratie nodig.

### Temperaturen

| Instelling | Standaard | Beschrijving |
|-----------|-----------|-------------|
| Normale doeltemperatuur (°C) | `55` | Dagelijks streefdoel |
| Boost temperatuur (°C) | `65` | Hogere doeltemperatuur tijdens boost modus |
| Vakantie minimumtemperatuur (°C) | `40` | Minimumtemperatuur als vakantie modus actief is |
| Boiler activeringsdrempel (°C onder setpoint) | `0` | Als je boiler pas reageert als de temperatuur minstens X graden onder het setpoint zit, stel dit hier in (bijv. `5`). `0` = uitgeschakeld. |

> **Boiler activeringsdrempel:** Sommige warmtepompen reageren niet op een aan-commando als de boilertemperatuur al dicht bij het setpoint zit (bijv. geen actie als boiler op 47°C staat en setpoint 50°C is). Stel de drempel in op de dode zone van jouw hardware zodat de integratie niet zinloos blijft proberen.

### Legionella preventie

| Instelling | Standaard | Beschrijving |
|-----------|-----------|-------------|
| Legionella preventie | aan | Wekelijkse run naar hoge temperatuur |
| Legionella temperatuur (°C) | `65` | Doeltemperatuur voor legionella run |
| Dag van legionella run | zondag | Dag van de week |
| Uur van legionella run | `13` | Uur van de dag (0–23) |

### Slim leren & energiebeheer

| Instelling | Standaard | Beschrijving |
|-----------|-----------|-------------|
| Warmteverlies tank (°C/u) | `0.5` | Startwaarde voor warmteverlies; wordt automatisch bijgeleerd uit metingen |
| Tankvolume (L) | `200` | Gebruikt voor COP-berekening |
| Anti-blokkeer interval (dagen) | `3` | Maximaal aantal dagen zonder verwarming voordat een verplichte korte run plaatsvindt |
| Voorspellend verwarmen | aan | Slaat prijsmodus over als morgen veel zon verwacht wordt (zodat de boiler daarna op zonne-energie wordt verwarmd) |

### Vakantie modus

| Instelling | Standaard | Beschrijving |
|-----------|-----------|-------------|
| Vakantie modus na afwezigheid van (uur) | `24` | Aantal uren dat de aanwezigheidssensor `off`/`not_home` moet zijn voordat vakantie modus automatisch inschakelt |

---

## Douche schema instellen

Ga naar **Instellingen → Integraties → Heat Pump DHW → Configureren** en voeg douche-tijden toe.
Per schema stel je in:
- Tijdstip (bijv. 07:30)
- Dagen van de week
- Vereiste temperatuur

De integratie berekent automatisch wanneer het voorverwarmen moet starten op basis van de geleerde opwarmtijd.

## Vakantie modus

De vakantie modus houdt de boiler op een minimale temperatuur (standaard 40°C) bij afwezigheid. Er zijn twee schakelaars:

### Schakelaar 1 — "Vakantie modus" (`switch.dhw_vacation_mode`)
Zet de automatische afwezigheidsdetectie aan of uit. Als een aanwezigheid-sensor is ingesteld en deze geeft langer dan de ingestelde drempel (standaard 24 uur) `off`/`not_home` aan, gaat "Op vakantie" automatisch aan. Als deze schakelaar uit staat, wordt er nooit automatisch vakantie modus geactiveerd.

### Schakelaar 2 — "Op vakantie" (`switch.dhw_on_vacation`)
De werkelijke vakantie-toestand. Dit is de schakelaar die het verwarmingsgedrag bepaalt.

| Situatie | Gedrag |
|----------|--------|
| Handmatig aan | Vakantie modus actief. Presence sensor negeert deze instelling — alleen handmatig uitzetten stopt de modus. |
| Automatisch aan (via afwezigheidsdetectie) | Gaat automatisch uit zodra je thuiskomt (presence sensor). |
| Handmatig uit | Reset ook de afwezigheidsdetectie direct. |

**Op afstand uitzetten** — zet `switch.dhw_on_vacation` uit via de HA app onderweg. De boiler valt terug op de normale schema's (douche-schema's, prijsmodus).

**Douche schema's tijdens vakantie** — schema's worden automatisch overgeslagen zolang "Op vakantie" actief is. Na het uitzetten worden schema's weer normaal uitgevoerd.

**Status** — de status-sensor toont `Vakantie — minimum 40°C` zolang vakantie actief is, ook als de boiler al op temperatuur is en niet actief verwarmt.

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
