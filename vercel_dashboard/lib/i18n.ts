export type Lang = "fr" | "en";

const translations = {
  fr: {
    // App header
    appTitle: "Jumeau Numérique HVAC",
    appSubtitle: "Green Energy Park · Supervision temps réel & prévision LSTM",
    updatedAt: "Actualisé à",

    // Toolbar
    exportCsv: "Exporter CSV",
    autoRefresh: "Actualisation automatique · 60s",
    refreshing: "Actualisation…",

    // Error banner
    loadError: "Impossible de charger les données :",

    // KPI card labels
    temperature: "Température",
    humidity: "Humidité",
    co2: "CO₂",
    lastReading: "Dernière mesure",
    forecast: "Prévision",
    pmvComfort: "Confort PMV",

    // KPI card values
    forecastAvailable: "Disponible",
    forecastPending: "En attente",

    // KPI notes
    noCo2Sensor: "Pas de capteur CO₂ en Zone 2",

    // PMV comfort labels
    pmvCold: "Froid",
    pmvCool: "Frais",
    pmvSlightlyCool: "Légèrement frais",
    pmvNeutral: "Neutre",
    pmvSlightlyWarm: "Légèrement chaud",
    pmvWarm: "Chaud",
    pmvHot: "Très chaud",

    // Section headings
    sectionRealtime: "Mesures temps réel & Prévisions LSTM",
    sectionComfort: "Confort thermique",
    sectionHistory: "Historique",

    // CO₂ chart notes
    co2NoteZone2: "La Zone 2 ne dispose pas de capteur de gaz/CO₂.",
    co2NoteZone1: "CO₂ en temps réel (capteur MQ-135) — pas de prévision pour le CO₂.",

    // PMV note
    pmvNote:
      "PMV (Predicted Mean Vote, ISO 7730) : −3 froid → 0 neutre → +3 chaud. Zone de confort : −0,5 ≤ PMV ≤ +0,5. Calculé sur les prévisions temp./humidité.",

    // History section
    histStart: "Début",
    histEnd: "Fin",
    histMeasure: "Mesure",
    histLoad: "Charger",
    histLoading: "Chargement…",
    histDateError: "Veuillez sélectionner une plage de dates.",
    histLoadError: "Erreur lors du chargement.",
    histNoData: "Aucune donnée pour cette période.",
    histPoints: (n: number) =>
      `${n} point${n > 1 ? "s" : ""} · agrégation 5 min`,

    // History field labels
    fieldTemp: "Température (°C)",
    fieldHum: "Humidité (%)",
    fieldCo2: "CO₂ / Gaz (ppm)",
    fieldPmv: "PMV",

    // Footer
    footerCopy: "© 2026 Green Energy Park — Jumeau Numérique HVAC",
    footerTagline: "Supervision temps réel · Prévision 4h · Mise à jour 10 min",
  },
  en: {
    // App header
    appTitle: "HVAC Digital Twin",
    appSubtitle: "Green Energy Park · Real-time monitoring & LSTM forecast",
    updatedAt: "Updated at",

    // Toolbar
    exportCsv: "Export CSV",
    autoRefresh: "Auto-refresh · 60s",
    refreshing: "Refreshing…",

    // Error banner
    loadError: "Failed to load data:",

    // KPI card labels
    temperature: "Temperature",
    humidity: "Humidity",
    co2: "CO₂",
    lastReading: "Last reading",
    forecast: "Forecast",
    pmvComfort: "PMV Comfort",

    // KPI card values
    forecastAvailable: "Available",
    forecastPending: "Pending",

    // KPI notes
    noCo2Sensor: "No CO₂ sensor in Zone 2",

    // PMV comfort labels
    pmvCold: "Cold",
    pmvCool: "Cool",
    pmvSlightlyCool: "Slightly cool",
    pmvNeutral: "Neutral",
    pmvSlightlyWarm: "Slightly warm",
    pmvWarm: "Warm",
    pmvHot: "Hot",

    // Section headings
    sectionRealtime: "Real-time Readings & LSTM Forecasts",
    sectionComfort: "Thermal comfort",
    sectionHistory: "History",

    // CO₂ chart notes
    co2NoteZone2: "Zone 2 has no gas/CO₂ sensor.",
    co2NoteZone1:
      "Real-time CO₂ (MQ-135 sensor) — no forecast available for CO₂.",

    // PMV note
    pmvNote:
      "PMV (Predicted Mean Vote, ISO 7730): −3 cold → 0 neutral → +3 hot. Comfort zone: −0.5 ≤ PMV ≤ +0.5. Computed from temperature/humidity forecasts.",

    // History section
    histStart: "Start",
    histEnd: "End",
    histMeasure: "Measure",
    histLoad: "Load",
    histLoading: "Loading…",
    histDateError: "Please select a date range.",
    histLoadError: "Error loading data.",
    histNoData: "No data for this period.",
    histPoints: (n: number) =>
      `${n} point${n > 1 ? "s" : ""} · 5-min aggregation`,

    // History field labels
    fieldTemp: "Temperature (°C)",
    fieldHum: "Humidity (%)",
    fieldCo2: "CO₂ / Gas (ppm)",
    fieldPmv: "PMV",

    // Footer
    footerCopy: "© 2026 Green Energy Park — HVAC Digital Twin",
    footerTagline: "Real-time monitoring · 4h forecast · 10-min update",
  },
} as const;

export const t = translations;
