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

## Configuratie

De integratie wordt ingesteld via een UI wizard met 5 stappen:

1. **Hardware sensoren** — boiler temperatuur, verbruiksmeter
2. **Hardware bediening** — doeltemperatuur, warmtepomp schakelaar, elektrisch element
3. **Zon & prijzen** — PV overschot sensor, Zonneplan prijs sensor
4. **Optionele sensoren** — weer, aanwezigheid, notificatie service
5. **Drempelwaarden** — overschot drempel, prijsdrempel, temperaturen

Na installatie zijn alle drempelwaarden ook aanpasbaar via number-entiteiten in HA.

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

## Prioriteitsvolgorde

Als meerdere modi tegelijk van toepassing zijn, geldt:

1. Legionella preventie (veiligheid)
2. Boost modus
3. Zonne-energie modus
4. Dynamische prijsmodus
5. Douche schema
6. Vakantie modus
7. Standby

## Vereiste entiteiten (minimaal)

- Boiler watertemperatuur sensor
- Warmtepomp aan/uit schakelaar
- Gewenste temperatuur instelling (number/input_number)

Alle andere sensoren en schakelaars zijn optioneel — hoe meer je koppelt, hoe slimmer de sturing.
