from __future__ import annotations

TOOL_LABELS: dict[str, dict[str, str]] = {
    "query_participant_metrics": {
        "en": "Querying your energy metrics",
        "it": "Recupero dei dati energetici",
        "es": "Consultando tus datos de energía",
    },
    "query_community_metrics": {
        "en": "Querying community metrics",
        "it": "Recupero dei dati della comunità",
        "es": "Consultando datos de la comunidad",
    },
    "query_participant_profile": {
        "en": "Loading your profile",
        "it": "Caricamento del profilo",
        "es": "Cargando tu perfil",
    },
    "query_participant_assets": {
        "en": "Looking up your assets",
        "it": "Ricerca dei dispositivi",
        "es": "Buscando tus dispositivos",
    },
    "search_documents": {
        "en": "Searching documents",
        "it": "Ricerca nei documenti",
        "es": "Buscando en documentos",
    },
    "get_attachment_info": {
        "en": "Loading attachment details",
        "it": "Caricamento dettagli allegato",
        "es": "Cargando detalles del adjunto",
    },
    "list_datasets": {
        "en": "Listing available datasets",
        "it": "Elenco dataset disponibili",
        "es": "Listando datasets disponibles",
    },
    "query_dataset": {
        "en": "Querying dataset",
        "it": "Interrogazione dataset",
        "es": "Consultando dataset",
    },
    "get_my_rec_profile": {
        "en": "Loading your REC profile",
        "it": "Caricamento profilo CER",
        "es": "Cargando tu perfil CER",
    },
    "get_my_community_details": {
        "en": "Loading community details",
        "it": "Caricamento dettagli comunità",
        "es": "Cargando detalles de la comunidad",
    },
    "get_my_assets": {
        "en": "Listing your assets",
        "it": "Elenco dei tuoi impianti",
        "es": "Listando tus activos",
    },
    "get_my_asset_detail": {
        "en": "Loading asset details",
        "it": "Caricamento dettagli impianto",
        "es": "Cargando detalles del activo",
    },
    "get_my_delivery_points": {
        "en": "Loading your delivery points",
        "it": "Caricamento punti di consegna",
        "es": "Cargando puntos de entrega",
    },
    "get_weather_current": {
        "en": "Checking current weather",
        "it": "Controllo meteo attuale",
        "es": "Consultando el clima actual",
    },
    "get_weather_forecast": {
        "en": "Loading weather forecast",
        "it": "Caricamento previsioni meteo",
        "es": "Cargando pronóstico del tiempo",
    },
    "get_weather_alerts": {
        "en": "Checking weather alerts",
        "it": "Controllo allerte meteo",
        "es": "Verificando alertas meteorológicas",
    },
    "get_energy_forecast": {
        "en": "Loading energy forecast",
        "it": "Caricamento previsioni energetiche",
        "es": "Cargando pronóstico energético",
    },
    "get_flexibility_suggestions": {
        "en": "Checking flexibility opportunities",
        "it": "Controllo opportunità di flessibilità",
        "es": "Verificando oportunidades de flexibilidad",
    },
    "get_gamification_status": {
        "en": "Loading your points and level",
        "it": "Caricamento punti e livello",
        "es": "Cargando tus puntos y nivel",
    },
    "get_commitment_history": {
        "en": "Loading commitment history",
        "it": "Caricamento storico impegni",
        "es": "Cargando historial de compromisos",
    },
}


def get_tool_labels(lang: str = "en") -> dict[str, str]:
    result = {}
    for tool_name, labels in TOOL_LABELS.items():
        result[tool_name] = labels.get(lang, labels.get("en", tool_name))
    return result


SUGGESTIONS: list[dict[str, dict[str, str]]] = [
    {
        "text": {
            "en": "How much energy did I produce today?",
            "it": "Quanta energia ho prodotto oggi?",
            "es": "¿Cuánta energía he producido hoy?",
        },
        "icon": {"en": "zap", "it": "zap", "es": "zap"},
        "skill": {"en": "digital_twin", "it": "digital_twin", "es": "digital_twin"},
    },
    {
        "text": {
            "en": "How is my community performing?",
            "it": "Come sta andando la mia comunità energetica?",
            "es": "¿Cómo va mi comunidad energética?",
        },
        "icon": {"en": "users", "it": "users", "es": "users"},
        "skill": {"en": "digital_twin", "it": "digital_twin", "es": "digital_twin"},
    },
    {
        "text": {
            "en": "What assets do I have registered?",
            "it": "Quali impianti ho registrato?",
            "es": "¿Qué activos tengo registrados?",
        },
        "icon": {"en": "cpu", "it": "cpu", "es": "cpu"},
        "skill": {"en": "rec_registry", "it": "rec_registry", "es": "rec_registry"},
    },
    {
        "text": {
            "en": "What is my self-consumption rate?",
            "it": "Qual è il mio tasso di autoconsumo?",
            "es": "¿Cuál es mi tasa de autoconsumo?",
        },
        "icon": {"en": "trending-up", "it": "trending-up", "es": "trending-up"},
        "skill": {"en": "digital_twin", "it": "digital_twin", "es": "digital_twin"},
    },
    {
        "text": {
            "en": "Tell me about my REC membership",
            "it": "Parlami della mia iscrizione alla CER",
            "es": "Cuéntame sobre mi membresía en la CER",
        },
        "icon": {"en": "user-check", "it": "user-check", "es": "user-check"},
        "skill": {"en": "rec_registry", "it": "rec_registry", "es": "rec_registry"},
    },
    {
        "text": {
            "en": "What are my delivery points?",
            "it": "Quali sono i miei punti di consegna?",
            "es": "¿Cuáles son mis puntos de entrega?",
        },
        "icon": {"en": "map-pin", "it": "map-pin", "es": "map-pin"},
        "skill": {"en": "rec_registry", "it": "rec_registry", "es": "rec_registry"},
    },
    {
        "text": {
            "en": "What's the weather like today?",
            "it": "Com'è il meteo oggi?",
            "es": "¿Qué tiempo hace hoy?",
        },
        "icon": {"en": "cloud-sun", "it": "cloud-sun", "es": "cloud-sun"},
        "skill": {"en": "weather", "it": "weather", "es": "weather"},
    },
    {
        "text": {
            "en": "Weather forecast for tomorrow?",
            "it": "Previsioni meteo per domani?",
            "es": "¿Pronóstico del tiempo para mañana?",
        },
        "icon": {"en": "calendar", "it": "calendar", "es": "calendar"},
        "skill": {"en": "weather", "it": "weather", "es": "weather"},
    },
    {
        "text": {
            "en": "Any weather alerts?",
            "it": "Ci sono allerte meteo?",
            "es": "¿Hay alertas meteorológicas?",
        },
        "icon": {"en": "alert-triangle", "it": "alert-triangle", "es": "alert-triangle"},
        "skill": {"en": "weather", "it": "weather", "es": "weather"},
    },
    {
        "text": {
            "en": "When should I run my appliances today?",
            "it": "Quando dovrei usare gli elettrodomestici oggi?",
            "es": "¿Cuándo debería usar mis electrodomésticos hoy?",
        },
        "icon": {"en": "clock", "it": "clock", "es": "clock"},
        "skill": {"en": "weather", "it": "weather", "es": "weather"},
    },
    {
        "text": {
            "en": "How can I earn more points?",
            "it": "Come posso guadagnare più punti?",
            "es": "¿Cómo puedo ganar más puntos?",
        },
        "icon": {"en": "star", "it": "star", "es": "star"},
        "skill": {"en": "flexibility", "it": "flexibility", "es": "flexibility"},
    },
    {
        "text": {
            "en": "What's my level and ranking?",
            "it": "Qual è il mio livello e la mia classifica?",
            "es": "¿Cuál es mi nivel y clasificación?",
        },
        "icon": {"en": "trophy", "it": "trophy", "es": "trophy"},
        "skill": {"en": "flexibility", "it": "flexibility", "es": "flexibility"},
    },
]


def get_suggestions(
    lang: str = "en",
    available_skills: set[str] | None = None,
) -> list[dict[str, str]]:
    result = []
    for s in SUGGESTIONS:
        skill = s["skill"].get(lang, s["skill"]["en"])
        if available_skills and skill not in available_skills:
            continue
        result.append({
            "text": s["text"].get(lang, s["text"]["en"]),
            "icon": s["icon"].get(lang, s["icon"]["en"]),
        })
    return result
