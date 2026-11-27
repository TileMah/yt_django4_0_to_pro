# -*- coding: utf-8 -*-

from django import forms
from django.contrib import admin
from django.contrib.admin.actions import delete_selected
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.safestring import mark_safe

from tournament.models import (
    MsOnlineTournamentRegistration,
    OnlineTournamentConfig,
    OnlineTournamentRegistration,
    Tournament,
    TournamentApplication,
    TournamentRegistration,
    TournamentResult,
    TournamentRoundResult,
)
from tournament.reconciliation import build_reconciliation_report
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget
from player.models import Player
from settings.models import Country

import unicodedata


def normalize_name(value):
    value = str(value or '').strip().upper()
    value = value.replace('-', ' ')
    # Dutch "LAST, VAN" form: "MEER, VAN DER" must match "VAN DER MEER"
    value = value.replace(',', ' ')
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(c for c in value if not unicodedata.combining(c))
    value = ' '.join(value.split())  # collapse repeated/leading/trailing whitespace
    return value


def name_key(first_name, last_name):
    # matches on the SET of words in the full name, not the (first, last) pair as such —
    # this makes matching immune to inconsistent splitting between first/last name across
    # different files/sheets (e.g. "HANG LEE" / "YAT" vs "LEE" / "YAT HANG" for the same
    # person), as long as every word of the name is present in both places.
    combined = normalize_name(first_name) + ' ' + normalize_name(last_name)
    return ' '.join(sorted(combined.split()))


def clean_number(value):
    # strips regular spaces AND non-breaking spaces (\xa0) sometimes used as thousands
    # separators when numbers are copy-pasted from web pages / other spreadsheets —
    # Decimal()/int() can't parse "\xa0206\xa0900" directly without this.
    #
    # Also treats anything that isn't actually a number after cleaning (a lone "-" used
    # to mean "no value", stray text, etc.) as None rather than passing it through and
    # letting Decimal()/int() blow up on it later.
    if value in (None, ''):
        return None
    text = str(value).replace('\xa0', '').replace(' ', '').strip()
    if not text:
        return None
    core = text[1:] if text[0] in '+-' else text
    if not core or not core.replace('.', '', 1).isdigit():
        return None
    return text


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        exclude = ["name", "registration_description", "results_description"]


class TournamentAdmin(admin.ModelAdmin):
    form = TournamentForm

    prepopulated_fields = {"slug": ["name_en"]}
    list_display = ["id", "name", "country", "end_date", "is_upcoming", "export", "reconcile"]
    list_filter = ["is_event", "tournament_type", "russian_cup", "country"]
    search_fields = ["name_ru", "name_en"]

    ordering = ["-end_date"]

    filter_horizontal = ["clubs"]

    def export(self, obj):
        return mark_safe(
            '<a href="{}">Export to EMA</a>'.format(
                reverse("export_tournament_results", kwargs={"tournament_id": obj.id})
            )
        )

    def reconcile(self, obj):
        return mark_safe(
            '<a href="{}">Reconcile</a>'.format(
                reverse("admin:tournament_reconcile", kwargs={"tournament_id": obj.id})
            )
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:tournament_id>/reconcile/",
                self.admin_site.admin_view(self.reconcile_view),
                name="tournament_reconcile",
            ),
        ]
        return custom_urls + urls

    def reconcile_view(self, request, tournament_id):
        tournament = get_object_or_404(Tournament, id=tournament_id)
        report = build_reconciliation_report(tournament)
        context = dict(
            self.admin_site.each_context(request),
            tournament=tournament,
            report=report,
        )
        return TemplateResponse(request, "admin/tournament/reconcile.html", context)


class TournamentRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "is_approved",
        "tournament",
        "first_name",
        "last_name",
        "city",
        "phone",
        "player",
        "city_object",
        "allow_to_save_data",
    ]

    raw_id_fields = ["tournament", "player", "city_object"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter]]


class OnlineTournamentRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "is_approved",
        "tournament",
        "first_name",
        "last_name",
        "city",
        "tenhou_nickname",
        "contact",
        "player",
        "city_object",
        "allow_to_save_data",
    ]

    raw_id_fields = ["tournament", "player", "city_object", "user"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter]]


class MsOnlineTournamentRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "is_approved",
        "tournament",
        "first_name",
        "last_name",
        "city",
        "ms_friend_id",
        "ms_nickname",
        "contact",
        "player",
        "city_object",
        "allow_to_save_data",
    ]

    raw_id_fields = ["tournament", "player", "city_object", "user"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter]]


class TournamentApplicationAdmin(admin.ModelAdmin):
    list_display = ["tournament_name", "city", "start_date", "created_on"]


class TournamentResultResource(resources.ModelResource):
    player = fields.Field(
        column_name='first_name',
        attribute='player',
        widget=ForeignKeyWidget(Player, field='id')
    )
    tournament = fields.Field(
        column_name='tournament',
        attribute='tournament',
        widget=ForeignKeyWidget(Tournament, field='id')
    )

    class Meta:
        model = TournamentResult
        fields = ('place', 'scores', 'ranking', 'player', 'tournament')
        import_id_fields = ('player', 'tournament')

    def before_import_row(self, row, **kwargs):
        first_name = row.get('first_name')
        last_name = row.get('last_name')

        player = None
        ema_id_raw = clean_number(row.get('ema_id'))
        if ema_id_raw and ema_id_raw.isdigit() and ema_id_raw != '0':
            player = Player.objects.filter(ema_id=ema_id_raw).first()

        if player is None:
            # ema_id missing/zero, or not found by ema_id — fall back to name matching
            player = Player.objects.filter(
                first_name__iexact=str(first_name or '').strip(),
                last_name__iexact=str(last_name or '').strip(),
            ).first()

        if player is None:
            raise ValueError(
                "Player not found: ema_id={!r}, name='{} {}' (row will not be imported)".format(
                    row.get('ema_id'), first_name, last_name
                )
            )
        row['first_name'] = player.id

        tournament_raw = row.get('tournament')
        row['tournament'] = int(float(tournament_raw)) if tournament_raw not in (None, '') else 0

        scores_raw = clean_number(row.get('scores'))
        row['scores'] = scores_raw

        ranking_raw = clean_number(row.get('ranking'))
        row['ranking'] = ranking_raw


class TournamentResultAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_classes = [TournamentResultResource]
    list_display = ["tournament", "player", "place", "scores"]
    search_fields = [
        "tournament__name",
        "player__last_name_ru",
        "player__first_name_ru",
        "player__last_name_en",
        "player__first_name_en",
    ]
    raw_id_fields = ["tournament", "player"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter]]


class TournamentRoundResultResource(resources.ModelResource):
    player = fields.Field(
        column_name='first_name',
        attribute='player',
        widget=ForeignKeyWidget(Player, field='id')
    )
    tournament = fields.Field(
        column_name='tournament',
        attribute='tournament',
        widget=ForeignKeyWidget(Tournament, field='id')
    )

    class Meta:
        model = TournamentRoundResult
        fields = ('round_number', 'table_number', 'score', 'penalty', 'place', 'player', 'tournament')
        import_id_fields = ('player', 'tournament', 'round_number')

    def _build_player_lookup(self):
        # built once per import, not once per row — word-set name key -> Player
        lookup = {}
        for player in Player.objects.all():
            key = name_key(player.first_name, player.last_name)
            lookup[key] = player
        return lookup

    def before_import(self, dataset, **kwargs):
        # place is not read from the file — it is computed here, once, for the whole
        # dataset, by ranking players' raw score (only) within the same
        # tournament+round+table. Both uma and penalty are added afterwards, once place
        # is known — uma because it's derived FROM place (including it here would be
        # circular), and penalty because it's a separate, later adjustment to the
        # player's final total rather than part of how the table's raw result is ranked.
        #
        # Every row counts toward the "4 players per table" check and toward the score
        # ranking — including substitute-placeholder rows and rows whose player can't be
        # matched — because a real game was still played with 4 people at that table, and
        # everyone's relative placement depends on everyone's score, even if one of them
        # won't end up being saved (no Player to attach to).
        self._player_lookup = self._build_player_lookup()
        self._place_lookup = {}
        groups = {}

        for row in dataset.dict:
            first_name = row.get('first_name')
            last_name = row.get('last_name')

            player = self._player_lookup.get(name_key(first_name, last_name))
            player_id = player.id if player else None  # None here surfaces as a clear error per-row later

            tournament_raw = row.get('tournament')
            tournament_id = int(float(tournament_raw)) if tournament_raw not in (None, '') else 0

            round_raw = row.get('round_number')
            round_number = int(float(round_raw)) if round_raw not in (None, '') else 0

            table_raw = row.get('table_number')
            table_number = int(float(table_raw)) if table_raw not in (None, '') else 0

            score_raw = clean_number(row.get('score'))
            score = int(float(score_raw)) if score_raw not in (None, '') else 0

            key = (tournament_id, round_number, table_number)
            groups.setdefault(key, []).append((player_id, score))

        invalid_tables = [
            "tournament={}, round={}, table={}: found {} players (expected 4)".format(
                key[0], key[1], key[2], len(players)
            )
            for key, players in groups.items()
            if len(players) != 4
        ]
        if invalid_tables:
            raise ValueError(
                "Some tables do not have exactly 4 players:\n" + "\n".join(invalid_tables)
            )

        for key, players in groups.items():
            ranked = sorted(players, key=lambda item: item[1], reverse=True)

            # players tied on score all get the SAME (best) place — this is what lets the
            # model's `uma` property detect the tie (by counting siblings with the same
            # place at the same table) and split the uma for the occupied range evenly.
            i = 0
            while i < len(ranked):
                j = i
                while j + 1 < len(ranked) and ranked[j + 1][1] == ranked[i][1]:
                    j += 1
                # average of the whole occupied range, e.g. a 2-way tie for 2nd-3rd place
                # gets place = (2 + 3) / 2 = 2.5 for both players in the tie.
                group_place = ((i + 1) + (j + 1)) / 2
                for k in range(i, j + 1):
                    player_id, _score = ranked[k]
                    if player_id is not None:
                        self._place_lookup[(key[0], key[1], key[2], player_id)] = group_place
                i = j + 1

    def before_import_row(self, row, **kwargs):
        first_name = row.get('first_name')
        last_name = row.get('last_name')

        player = self._player_lookup.get(name_key(first_name, last_name))
        if player is None:
            raise ValueError(
                "Player not found: '{} {}' (row will not be imported)".format(first_name, last_name)
            )
        row['first_name'] = player.id

        tournament_raw = row.get('tournament')
        row['tournament'] = int(float(tournament_raw)) if tournament_raw not in (None, '') else 0

        round_raw = row.get('round_number')
        row['round_number'] = int(float(round_raw)) if round_raw not in (None, '') else 0

        table_raw = row.get('table_number')
        if table_raw in (None, ''):
            raise ValueError("table_number is required and cannot be empty")
        table_number = int(float(table_raw))
        if table_number <= 0:
            raise ValueError("table_number must be greater than 0, got {}".format(table_number))
        row['table_number'] = table_number

        place = self._place_lookup.get((row['tournament'], row['round_number'], row['table_number'], player.id))
        if place is None or not (1 <= place <= 4):
            raise ValueError(
                "Could not determine place for player '{} {}' at tournament={}, round={}, table={} "
                "(check that the table has between 1 and 4 players)".format(
                    first_name, last_name, row['tournament'], row['round_number'], row['table_number']
                )
            )
        row['place'] = place

        penalty_raw = clean_number(row.get('penalty', row.get('Penalty')))
        row['penalty'] = int(float(penalty_raw)) if penalty_raw not in (None, '') else 0

        score_raw = clean_number(row.get('score'))
        row['score'] = int(float(score_raw)) if score_raw not in (None, '') else 0


class TournamentRoundResultAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_classes = [TournamentRoundResultResource]
    list_display = ["tournament", "round_number", "table_number", "player", "score", "uma", "penalty", "total", "place"]
    list_display_links = ["tournament"]
    list_editable = ["round_number", "table_number", "player", "score", "penalty", "place"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter], "round_number", "table_number"]
    search_fields = [
        "player__first_name_ru", "player__first_name_en",
        "player__last_name_ru", "player__last_name_en",
    ]
    ordering = ["tournament", "round_number", "table_number", "-score"]
    actions = ["delete_all_matching_filter"]

    def delete_all_matching_filter(self, request, queryset):
        # Deliberately does NOT reconstruct the queryset itself (that caused an earlier
        # bug that deleted everything, ignoring the filter). Instead it just reuses
        # Django's own built-in delete_selected action, which already receives a
        # correctly filtered `queryset` here — either the checked rows, or, if you use
        # the "Select all N items matching your search" link that appears after checking
        # the header checkbox, the FULL filtered set across all pages. It also keeps
        # Django's standard confirmation page, since this is a destructive bulk delete.
        return delete_selected(self, request, queryset)

    delete_all_matching_filter.short_description = (
        "Delete selected — or use 'Select all N items matching your search' first to delete everything matching the current filter"
    )


class OnlineTournamentConfigAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "token",
        "online_config",
    ]


admin.site.register(Tournament, TournamentAdmin)
admin.site.register(OnlineTournamentConfig, OnlineTournamentConfigAdmin)
admin.site.register(TournamentRegistration, TournamentRegistrationAdmin)
admin.site.register(OnlineTournamentRegistration, OnlineTournamentRegistrationAdmin)
admin.site.register(MsOnlineTournamentRegistration, MsOnlineTournamentRegistrationAdmin)
admin.site.register(TournamentApplication, TournamentApplicationAdmin)
admin.site.register(TournamentResult, TournamentResultAdmin)
admin.site.register(TournamentRoundResult, TournamentRoundResultAdmin)
