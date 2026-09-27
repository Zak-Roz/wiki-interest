"""Labels for charts and the PDF. The narrative (recommendation, caveats) is
written by the agent in the user's language; these are only the fixed strings.
Unknown languages fall back to English."""

LABELS = {
    "en": {
        "title": "Wikipedia interest: {topic}",
        "subtitle": "{langs} · {start} – {end} · human pageviews (agent=user), Wikimedia Pageviews API",
        "monthly_views": "Monthly views",
        "share_title": "Views per 1M views of the whole edition",
        "index_title": "Indexed monthly views (first 3 months = 100)",
        "daily_title": "Daily views ({lang}): {title}",
        "spike": "spike",
        "views": "views",
        "kpi_header": ["Lang", "Article", "Views/day", "YoY", "YoY w/o spikes",
                       "Per 1M edition views", "Trend/yr", "Trust"],
        "recommendation": "Recommendation",
        "trust": "How much to trust this",
        "caveats": "Assumptions & limits",
        "generated": "Generated {date} · wiki-interest skill · Wikipedia interest is a proxy for curiosity, not for willingness to pay.",
        "high": "high", "medium": "medium", "low": "low",
        "na": "n/a",
        "default_caveats": [
            "Pageviews measure curiosity about a Wikipedia article, not purchase intent.",
            "Only human traffic is counted; spikes are flagged, not removed from raw totals.",
            "One article per language stands in for the topic; related articles are not summed.",
        ],
    },
    "uk": {
        "title": "Інтерес у Wikipedia: {topic}",
        "subtitle": "{langs} · {start} – {end} · перегляди людьми (agent=user), Wikimedia Pageviews API",
        "monthly_views": "Перегляди за місяць",
        "share_title": "Переглядів на 1 млн переглядів усього розділу",
        "index_title": "Індекс місячних переглядів (перші 3 місяці = 100)",
        "daily_title": "Щоденні перегляди ({lang}): {title}",
        "spike": "сплеск",
        "views": "перегляди",
        "kpi_header": ["Мова", "Стаття", "Перегл./день", "Рік/рік", "Р/р без сплесків",
                       "На 1 млн розділу", "Тренд/рік", "Довіра"],
        "recommendation": "Рекомендація",
        "trust": "Наскільки цьому можна довіряти",
        "caveats": "Припущення та обмеження",
        "generated": "Згенеровано {date} · навичка wiki-interest · Інтерес у Wikipedia — це індикатор цікавості, а не готовності платити.",
        "high": "висока", "medium": "середня", "low": "низька",
        "na": "н/д",
        "default_caveats": [
            "Перегляди вимірюють цікавість до статті у Wikipedia, а не намір купувати.",
            "Враховано лише людський трафік; сплески позначено, але не вилучено з сирих сум.",
            "Тему представляє одна стаття на мову; суміжні статті не підсумовано.",
        ],
    },
    "pl": {
        "title": "Zainteresowanie w Wikipedii: {topic}",
        "subtitle": "{langs} · {start} – {end} · odsłony przez ludzi (agent=user), Wikimedia Pageviews API",
        "monthly_views": "Odsłony miesięcznie",
        "share_title": "Odsłony na 1 mln odsłon całej edycji",
        "index_title": "Indeks odsłon miesięcznych (pierwsze 3 miesiące = 100)",
        "daily_title": "Odsłony dzienne ({lang}): {title}",
        "spike": "skok",
        "views": "odsłony",
        "kpi_header": ["Język", "Artykuł", "Odsłon/dzień", "Rok/rok", "R/r bez skoków",
                       "Na 1 mln edycji", "Trend/rok", "Zaufanie"],
        "recommendation": "Rekomendacja",
        "trust": "Na ile można temu ufać",
        "caveats": "Założenia i ograniczenia",
        "generated": "Wygenerowano {date} · skill wiki-interest · Zainteresowanie w Wikipedii to wskaźnik ciekawości, nie gotowości do zapłaty.",
        "high": "wysokie", "medium": "średnie", "low": "niskie",
        "na": "b/d",
        "default_caveats": [
            "Odsłony mierzą ciekawość wobec artykułu, nie zamiar zakupu.",
            "Liczony jest tylko ruch ludzki; skoki są oznaczone, ale nie usunięte z surowych sum.",
            "Temat reprezentuje jeden artykuł na język; artykuły pokrewne nie są sumowane.",
        ],
    },
}


def labels(lang: str) -> dict:
    base = dict(LABELS["en"])
    base.update(LABELS.get(lang, {}))
    return base
