# -*- coding: utf-8 -*-
"""
Скачивает страницу турнира с mahjong-europe.org и записывает всё напрямую в базу:
сам турнир (название, город, страна, даты, ema_id), игроков (создаёт недостающих)
и результаты (TournamentResult) — без единого промежуточного Excel-файла.

Использование:
    pip install requests beautifulsoup4

    # турнир новый — команда сама его найдёт по ema_id со страницы или создаст:
    python manage.py import_ema_tournament <URL турнира> --dry-run
    python manage.py import_ema_tournament <URL турнира>

    # турнир уже есть в базе под конкретным id — можно указать явно:
    python manage.py import_ema_tournament <URL турнира> --tournament-id 5

Пример:
    python manage.py import_ema_tournament \
        http://mahjong-europe.org/ranking/Tournament/TR_RCR_422.html --dry-run
"""

import re
import sys
from datetime import date

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from player.models import Player
from settings.models import City, Country
from tournament.admin import name_key
from tournament.models import Tournament, TournamentResult

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MahjongPortalImporter/1.0)"}
EMA_NUMBER_RE = re.compile(r"/Players/([A-Za-z0-9]+)\.html")
COUNTRY_CODE_RE = re.compile(r"/Country/([A-Z]{3})_Information\.html")
COUNTRY_ALIASES = {"GB": "UK", "UK": "GB"}
DATE_TOKEN_RE =re.compile(r"\d+|[^\W\d_]+")
# English, French and German spellings seen on mahjong-europe.org ("Aug.", "mars", "Okt")
MONTH_PREFIXES = [
    ("juin", 6), ("juni", 6), ("juil", 7), ("juli", 7),
    ("jan", 1), ("feb", 2), ("fév", 2), ("fev", 2), ("mar", 3), ("mär", 3), ("mrz", 3),
    ("apr", 4), ("avr", 4), ("may", 5), ("mai", 5), ("jun", 6), ("jul", 7),
    ("aug", 8), ("aoû", 8), ("aou", 8), ("sep", 9), ("oct", 10), ("okt", 10),
    ("nov", 11), ("dec", 12), ("déc", 12), ("dez", 12),
]


def month_number(word):
    word = word.lower()
    for prefix, number in MONTH_PREFIXES:
        if word.startswith(prefix):
            return number
    return None


def clean_text(value):
    if value is None:
        return ""
    return " ".join(value.split())


def parse_number(text):
    text = clean_text(text)
    if not text or text == "-":
        return None
    try:
        return int(text.replace(",", "").replace("\xa0", "").replace(" ", ""))
    except ValueError:
        return None


def parse_ema_number(cell):
    link = cell.find("a")
    if link and link.get("href"):
        match = EMA_NUMBER_RE.search(link["href"])
        if match:
            value = match.group(1)
            if value.isdigit():
                # "00000000" means "no EMA number". Return "" (not "0") so we never look a
                # player up by ema_id="0" — many players share it; "0" is written on create.
                return value.lstrip("0")
            return value

    text = clean_text(cell.get_text())
    if text.isdigit():
        return text.lstrip("0")
    return text if text and text != "-" else ""


def parse_country_code(cell):
    img = cell.find("img")
    if img and img.get("src"):
        filename = img["src"].rsplit("/", 1)[-1]
        code2 = filename.split(".")[0]
        if len(code2) == 2:
            return code2.upper()

    link = cell.find("a")
    if link and link.get("href"):
        match = COUNTRY_CODE_RE.search(link["href"])
        if match:
            return match.group(1)

    return ""


def parse_date_range(date_text):
    """
    EMA pages use many free-form date spellings, e.g.
    "15 Aug. 2008", "5-6 Sep. 2015", "2-3. May 2015", "13-14 Apr.2019", "9 Feb. 25",
    "May 23-24 2026", "Jan 31–Feb 1 2026", "31-01 Oct-Nov 2026", "17-mars-13",
    "06/06/2026", "30 Dec 2025 - 2 Jan 2026".
    So instead of matching one pattern, split the text into numbers and month words.
    Returns (start_date, end_date) or (None, None).
    """
    tokens = DATE_TOKEN_RE.findall(date_text or "")
    months = [m for m in (month_number(t) for t in tokens if not t.isdigit()) if m]
    numbers = [t for t in tokens if t.isdigit()]

    years = [int(n) for n in numbers if len(n) == 4]
    if years:
        days = [int(n) for n in numbers if len(n) <= 2]
    elif len(numbers) >= 2 and len(numbers[-1]) == 2:
        # two-digit year at the end: "9 Feb. 25", "17-mars-13"
        years = [2000 + int(numbers[-1])]
        days = [int(n) for n in numbers[:-1] if len(n) <= 2]
    else:
        return None, None

    if not months:
        # numeric "dd/mm/yyyy"
        if len(days) == 2:
            days, months = [days[0]], [days[1]]
        else:
            return None, None

    if not days:
        return None, None

    start_day, end_day = days[0], days[-1]
    start_month, end_month = months[0], months[-1]
    start_year, end_year = years[0], years[-1]
    try:
        start, end = date(start_year, start_month, start_day), date(end_year, end_month, end_day)
    except ValueError:
        return None, None

    if start > end and start_year == end_year:
        # "30 Dec - 2 Jan 2026": the year is only given once, for the end date
        try:
            start = date(start_year - 1, start_month, start_day)
        except ValueError:
            return None, None
    return start, end


def find_result_rows(soup):
    container = soup.find("div", class_="Tableau_CertifiedTournament")
    if container is None:
        raise CommandError(
            "Не нашёл блок результатов (div.Tableau_CertifiedTournament) на странице — "
            "возможно, вёрстка сайта изменилась."
        )

    row_divs = container.find_all("div", class_=["TCTT_ligne", "TCTT_ligneG"])
    data_rows = [
        row.find_all("p", class_=lambda c: c and c.startswith("contenuCellule"))
        for row in row_divs
    ]
    data_rows = [cells for cells in data_rows if len(cells) == 8]

    if not data_rows:
        raise CommandError("Блок результатов найден, но строки не распознались.")

    return data_rows


def parse_tournament_info(soup):
    h2 = soup.find("h2")
    table = h2.find_next("table") if h2 else None
    if table is None:
        raise CommandError("Не нашёл блок с информацией о турнире (Number/Name/Place/Date).")

    info = {"number": "", "name": "", "date_raw": "", "players": "", "city": "", "country_code": ""}

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = clean_text(cells[0].get_text()).rstrip(":").strip().lower()

        if label == "number":
            info["number"] = clean_text(cells[1].get_text())
        elif label == "name":
            info["name"] = clean_text(cells[1].get_text())
        elif label == "date":
            info["date_raw"] = clean_text(cells[1].get_text())
        elif label == "players":
            info["players"] = clean_text(cells[1].get_text())
        elif label == "place":
            place_cell = cells[1]
            info["country_code"] = parse_country_code(place_cell)
            place_text = clean_text(place_cell.get_text()).split("(")[0].strip()
            info["city"] = place_text.split(",")[0].strip() if "," in place_text else place_text

    return info


SUBSTITUTE_LAST_NAME = "SUBSTITUTED"


def split_guest_name(full_name):
    """ "GRANT MAHONEY" -> ("GRANT", "MAHONEY"): first word is the first name."""
    parts = full_name.split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (full_name, "-")


def is_substitute(first_name, last_name):
    """EMA marks substitute seats as e.g. "PLAYER SUBSTITUT", "PLAYER 2 SUBSTITUT",
    "SUBSTITUTED PLAYER", or leaves both names as "-"."""
    full = "{} {}".format(first_name, last_name).upper()
    if "SUBSTITU" in full:
        return True
    return first_name.strip() in ("", "-") and last_name.strip() in ("", "-")


def generate_unique_slug(name):
    base_slug = slugify(name)
    slug = base_slug
    suffix = 2
    while Tournament.objects.filter(slug=slug).exists():
        slug = "{}-{}".format(base_slug, suffix)
        suffix += 1
    return slug


class Command(BaseCommand):
    help = (
        "Scrapes a Mahjong Europe tournament page (metadata + results) and writes "
        "Tournament, Player and TournamentResult directly to the database."
    )

    def add_arguments(self, parser):
        parser.add_argument("url", type=str, help="URL страницы турнира на mahjong-europe.org")
        parser.add_argument(
            "--tournament-id",
            type=int,
            default=None,
            help="ID уже существующего турнира в базе. Если не указан — ищем/создаём по ema_id со страницы.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать, что было бы сделано, без записи в базу.",
        )

    def handle(self, *args, **options):
        url = options["url"]
        explicit_tournament_id = options["tournament_id"]
        dry_run = options["dry_run"]

        # a Windows console in cp1251/cp866 can't print names like "Ę" or "ß" —
        # replace such characters in the output instead of crashing mid-import
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")

        self.stdout.write("Скачиваю: {}".format(url))
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        tournament_info = parse_tournament_info(soup)
        data_rows = find_result_rows(soup)
        self.stdout.write("Турнир: {} (ema_id={})".format(tournament_info["name"], tournament_info["number"]))
        self.stdout.write("Найдено строк результатов: {}".format(len(data_rows)))

        # the page gives either a 2-letter flag code (Country.code2) or a 3-letter
        # EMA code from the country link (Country.code, e.g. "POR")
        country_lookup = {}
        for c in Country.objects.all():
            for key in (c.code, c.code2):
                if key:
                    country_lookup.setdefault(key.upper(), c)
        # EMA uses the ISO flag "GB", while this database stores United Kingdom as code2="UK"
        for alias, real in COUNTRY_ALIASES.items():
            if alias not in country_lookup and real in country_lookup:
                country_lookup[alias] = country_lookup[real]
        player_lookup = {name_key(p.first_name, p.last_name): p for p in Player.objects.all()}

        # --- турнир: либо явно указанный id, либо поиск/создание по ema_id ---
        tournament = None
        if explicit_tournament_id:
            try:
                tournament = Tournament.objects.get(id=explicit_tournament_id)
            except Tournament.DoesNotExist:
                raise CommandError("Tournament with id={} does not exist".format(explicit_tournament_id))
        elif tournament_info["number"]:
            tournament = Tournament.objects.filter(ema_id=tournament_info["number"]).first()

        if tournament is None:
            country = country_lookup.get(tournament_info["country_code"].upper())
            if country is None and not dry_run:
                raise CommandError(
                    "Страна '{}' не найдена в базе (Country.code2) — турнир не может быть создан "
                    "без страны (поле обязательное). Добавьте страну вручную и повторите.".format(
                        tournament_info["country_code"]
                    )
                )

            city = City.objects.filter(name__iexact=tournament_info["city"]).first() if tournament_info["city"] else None
            start_date, end_date = parse_date_range(tournament_info["date_raw"])
            number_of_players = parse_number(tournament_info["players"]) or 0

            if dry_run:
                self.stdout.write(
                    "  [dry-run] создал бы турнир: '{}' | город={} | страна={} | {} - {} | игроков={}".format(
                        tournament_info["name"], tournament_info["city"] or "—",
                        tournament_info["country_code"] or "—", start_date, end_date, number_of_players,
                    )
                )
                # заглушка только для отображения в dry-run, в базу не сохраняется
                tournament = Tournament(
                    name=tournament_info["name"],
                    ema_id=tournament_info["number"],
                    start_date=start_date,
                    end_date=end_date,
                    number_of_players=number_of_players,
                )
            else:
                if end_date is None:
                    raise CommandError(
                        "Не смог разобрать дату турнира: '{}' — end_date обязателен. "
                        "Создайте турнир вручную через админку.".format(tournament_info["date_raw"])
                    )
                try:
                    tournament = Tournament.objects.create(
                        name=tournament_info["name"],
                        slug=generate_unique_slug(tournament_info["name"]),
                        ema_id=tournament_info["number"],
                        country=country,
                        city=city,
                        start_date=start_date,
                        end_date=end_date,
                        number_of_players=number_of_players,
                        tournament_type=Tournament.EMA,
                    )
                    self.stdout.write(self.style.SUCCESS("Создан турнир: {} (id={})".format(tournament, tournament.id)))
                except IntegrityError as exc:
                    raise CommandError("Не удалось создать турнир: {}".format(exc))
        else:
            self.stdout.write("Турнир уже есть в базе: {} (id={})".format(tournament, tournament.id))

        # --- результаты и игроки ---
        results_created, results_updated = 0, 0
        players_created, ema_ids_filled, countries_filled, errors = [], [], [], []
        substitutes_seen = 0

        with transaction.atomic():
            for cells in data_rows:
                place = parse_number(cells[0].get_text())
                if place is None:
                    continue

                ema_number = parse_ema_number(cells[1])
                last_name = clean_text(cells[2].get_text())
                first_name = clean_text(cells[3].get_text())
                # EMA guests come as first name "- EMA GUEST -" and the full name in the last
                # name column ("GRANT MAHONEY"); their EMA number (24xxxxxx) is real
                is_guest = "EMA GUEST" in first_name.upper()
                if is_guest:
                    first_name, last_name = split_guest_name(last_name)
                country_code = parse_country_code(cells[4])
                scores = parse_number(cells[6].get_text())
                ranking = parse_number(cells[7].get_text())

                # substitute seats ("PLAYER SUBSTITUT", "PLAYER 2 SUBSTITUT", "- -", ...) all go to
                # the shared stubs "PLAYER 1..N SUBSTITUTED": the k-th substitute row on the page
                # (rows are in place order) -> PLAYER k, so re-imports stay stable
                if is_substitute(first_name, last_name):
                    substitutes_seen += 1
                    stub_first = "PLAYER {}".format(substitutes_seen)
                    player = Player.objects.filter(first_name=stub_first, last_name=SUBSTITUTE_LAST_NAME).first()
                    if dry_run:
                        self.stdout.write(
                            "  [dry-run] place={} {} {} -> {} {} scores={} ranking={}".format(
                                place, first_name, last_name, stub_first, SUBSTITUTE_LAST_NAME, scores, ranking
                            )
                        )
                        continue
                    if player is None:
                        player = Player.objects.create(
                            first_name=stub_first,
                            last_name=SUBSTITUTE_LAST_NAME,
                            ema_id="0",
                            is_exclude_from_rating=True,
                            is_replacement=True,
                        )
                        players_created.append("{} (id={})".format(player, player.id))
                    obj, is_created = TournamentResult.objects.update_or_create(
                        tournament=tournament,
                        player=player,
                        defaults={"place": place, "scores": scores, "ranking": ranking},
                    )
                    if is_created:
                        results_created += 1
                    else:
                        results_updated += 1
                    continue

                player = None
                if ema_number and ema_number.isdigit():
                    player = Player.objects.filter(ema_id=ema_number).first()
                if player is None:
                    player = player_lookup.get(name_key(first_name, last_name))
                    # found by name, and the page knows the EMA number we don't have yet
                    if player is not None and ema_number and player.ema_id in (None, "", "0"):
                        if dry_run:
                            self.stdout.write(
                                "  [dry-run] записал бы ema_id={} игроку {} (id={})".format(
                                    ema_number, player, player.id
                                )
                            )
                        else:
                            player.ema_id = ema_number
                            player.save(update_fields=["ema_id"])
                            ema_ids_filled.append("{} (id={}) -> {}".format(player, player.id, ema_number))

                if player is not None and is_guest and not player.is_ema_guest and not dry_run:
                    player.is_ema_guest = True
                    player.save(update_fields=["is_ema_guest"])

                # existing player without a country: take it from the page
                if player is not None and player.country_id is None and country_code and not dry_run:
                    page_country = country_lookup.get(country_code.upper())
                    if page_country is not None:
                        player.country = page_country
                        player.save(update_fields=["country"])
                        countries_filled.append("{} (id={}) -> {}".format(player, player.id, page_country.code2))

                if player is None:
                    country = country_lookup.get(country_code.upper()) if country_code else None

                    if dry_run:
                        self.stdout.write(
                            "  [dry-run] создал бы игрока: {} {} (ema={!r}, country={})".format(
                                first_name, last_name, ema_number, country_code
                            )
                        )
                    else:
                        try:
                            with transaction.atomic():
                                player = Player.objects.create(
                                    first_name=first_name,
                                    last_name=last_name,
                                    # project convention: "0" = player has no EMA number
                                    ema_id=ema_number or "0",
                                    country=country,
                                    is_ema_guest=is_guest,
                                )
                        except IntegrityError as exc:
                            errors.append(
                                "place={} '{} {}' — не удалось создать игрока: {}".format(
                                    place, first_name, last_name, exc
                                )
                            )
                            continue

                        players_created.append("{} {} (id={})".format(first_name, last_name, player.id))
                        player_lookup[name_key(first_name, last_name)] = player

                if dry_run:
                    self.stdout.write(
                        "  [dry-run] place={} {} {} -> scores={} ranking={}".format(
                            place, first_name, last_name, scores, ranking
                        )
                    )
                    continue

                obj, is_created = TournamentResult.objects.update_or_create(
                    tournament=tournament,
                    player=player,
                    defaults={"place": place, "scores": scores, "ranking": ranking},
                )
                if is_created:
                    results_created += 1
                else:
                    results_updated += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN — в базу ничего не записано."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Результатов создано: {}, обновлено: {}".format(results_created, results_updated)
                )
            )
            if players_created:
                self.stdout.write(self.style.SUCCESS("Новых игроков создано: {}".format(len(players_created))))
                for line in players_created:
                    self.stdout.write("  + " + line)
            if ema_ids_filled:
                self.stdout.write(self.style.SUCCESS("Игрокам дописан ema_id: {}".format(len(ema_ids_filled))))
                for line in ema_ids_filled:
                    self.stdout.write("  ~ " + line)
            if countries_filled:
                self.stdout.write(self.style.SUCCESS("Игрокам дописана страна: {}".format(len(countries_filled))))
                for line in countries_filled:
                    self.stdout.write("  ^ " + line)

        if errors:
            self.stdout.write(self.style.ERROR("Ошибок: {}".format(len(errors))))
            for line in errors:
                self.stdout.write("  - " + line)
