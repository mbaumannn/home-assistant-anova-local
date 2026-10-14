# Anova Bluetooth — Home Assistant

Lokale Home Assistant-integratie voor BLE **Anova**-sous-vide-toestellen.
Geen app, geen cloud, geen account. Gebruikt HA's eigen `bluetooth`-component,
dus het werkt met **elke connectable Bluetooth-adapter of ESPHome Bluetooth-proxy**.

Vereist Home Assistant **2026.5.0** of nieuwer.

## Installeren (HACS)
1. HACS → Integrations → ⋮ → Custom repositories → deze repo, categorie *Integration*.
2. Installeer "Anova Bluetooth", herstart HA.
3. Zet de Anova aan. HA vindt hem automatisch → **Koppelen** (of handmatig MAC-adres).

## Entiteiten
- `climate.anova` — uit/warm, doeltemperatuur, huidige watertemperatuur
- `number.anova_kookduur` — **bewaarde duur-preset** in minuten (blijft staan tijdens koken)
- `switch.anova_timer` — timer start/stop
- `sensor.anova_status` — idle / koken / laag water
- `sensor.anova_timer_resterend` — **live** resterende minuten
- `button.anova_start_koken` — start verwarmen + timer in één tik

De timer start bij `start time` en loopt op de klok: **de opwarmtijd telt mee**.

## Auto-connect
Zet de Anova aan → de entiteiten komen vanzelf online. Uit → `unavailable`.
De Anova ondersteunt **één** BLE-verbinding tegelijk: laat de Anova-app dicht.

## Notificaties
Importeer de blueprints (Instellingen → Automatiseringen → Blueprints):
- `anova_klaar.yaml` — meldt "klaar" wanneer de **timer afloopt** (niet bij een
  handmatige stop). Werkt met `switch.anova_timer` (on→off) + `sensor.anova_timer_resterend`.
- `anova_op_temperatuur.yaml` — meldt wanneer het water op temperatuur is,
  alleen tijdens een actieve kooksessie en als het toestel beschikbaar is.

## Getest met
Anova Precision Cooker (2018, Bluetooth + WiFi, EU), firmware `ver 6.1.1`.
