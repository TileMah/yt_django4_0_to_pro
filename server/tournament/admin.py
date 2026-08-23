# -*- coding: utf-8 -*-

from django import forms
from django.contrib import admin
from django.urls import reverse
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
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget
from player.models import Player
from settings.models import Country


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        exclude = ["name", "registration_description", "results_description"]


class TournamentAdmin(admin.ModelAdmin):
    form = TournamentForm

    prepopulated_fields = {"slug": ["name_en"]}
    list_display = ["id", "name", "country", "end_date", "is_upcoming", "export"]
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
        first_name = str(row.get('first_name') or '').strip()
        last_name = str(row.get('last_name') or '').strip()

        player = Player.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name).first()
        if player is None:
            raise ValueError(
                "Player not found: '{} {}' (row will not be imported)".format(first_name, last_name)
            )
        row['first_name'] = player.id

        tournament_raw = row.get('tournament')
        row['tournament'] = int(float(tournament_raw)) if tournament_raw not in (None, '') else 0


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

    def before_import(self, dataset, **kwargs):
        # place is not read from the file — it is computed here, once, for the whole
        # dataset, by ranking players' raw scores within the same tournament+round+table.
        self._place_lookup = {}
        groups = {}

        for row in dataset.dict:
            first_name = str(row.get('first_name') or '').strip()
            last_name = str(row.get('last_name') or '').strip()
            player = Player.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name).first()
            if player is None:
                continue  # a clear error for this will be raised later, in before_import_row

            tournament_raw = row.get('tournament')
            tournament_id = int(float(tournament_raw)) if tournament_raw not in (None, '') else 0

            round_raw = row.get('round_number')
            round_number = int(float(round_raw)) if round_raw not in (None, '') else 0

            table_raw = row.get('table_number')
            table_number = int(float(table_raw)) if table_raw not in (None, '') else 0

            score_raw = row.get('score')
            score = int(float(score_raw)) if score_raw not in (None, '') else 0

            key = (tournament_id, round_number, table_number)
            groups.setdefault(key, []).append((player.id, score))

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
            for index, (player_id, _score) in enumerate(ranked):
                self._place_lookup[(key[0], key[1], key[2], player_id)] = index + 1

    def before_import_row(self, row, **kwargs):
        first_name = str(row.get('first_name') or '').strip()
        last_name = str(row.get('last_name') or '').strip()

        player = Player.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name).first()
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
        if place is None or place not in (1, 2, 3, 4):
            raise ValueError(
                "Could not determine place for player '{} {}' at tournament={}, round={}, table={} "
                "(check that the table has between 1 and 4 players)".format(
                    first_name, last_name, row['tournament'], row['round_number'], row['table_number']
                )
            )
        row['place'] = place

        penalty_raw = row.get('penalty')
        row['penalty'] = int(float(penalty_raw)) if penalty_raw not in (None, '') else 0

        score_raw = row.get('score')
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
