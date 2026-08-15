# -*- coding: utf-8 -*-

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.text import slugify

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
    list_display = ["name", "country", "end_date", "is_upcoming", "export"]
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
        column_name='player',
        attribute='player',
        widget=ForeignKeyWidget(Player, field='slug')
    )
    country = fields.Field(
        column_name='country',
        attribute='country',
        widget=ForeignKeyWidget(Country, field='code2')
    )
    tournament = fields.Field(
        column_name='tournament',
        attribute='tournament',
        widget=ForeignKeyWidget(Tournament, field='id')
    )

    class Meta:
        model = TournamentResult
        fields = ('place', 'country', 'scores', 'ranking', 'player', 'tournament')
        import_id_fields = ('player', 'tournament')

    def before_import_row(self, row, **kwargs):
        first_name = str(row.get('first_name') or '').strip()
        last_name = str(row.get('last_name') or '').strip()
        row['player'] = slugify("{} {}".format(first_name, last_name))

        tournament_raw = row.get('tournament')
        row['tournament'] = int(float(tournament_raw)) if tournament_raw not in (None, '') else 0

    def before_save_instance(self, instance, row, **kwargs):
        instance.slug = "{}-{}".format(instance.player.slug, instance.tournament_id)

class TournamentResultAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_classes = [TournamentResultResource]
    list_display = ["tournament", "player", "place", "scores", "country"]
    prepopulated_fields = {"slug": ["player", "tournament"]}
    search_fields = [
        "tournament__name",
        "player__last_name_ru",
        "player__first_name_ru",
        "player__last_name_en",
        "player__first_name_en",
        "player",
    ]
    raw_id_fields = ["tournament", "player"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter]]


class OnlineTournamentConfigAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "token",
        "online_config",
    ]

class TournamentRoundResultAdmin(admin.ModelAdmin):
    list_display = ["tournament", "round_number", "player", "score", "place"]
    list_display_links = ["tournament"]
    list_editable = ["round_number", "player", "score", "place"]
    list_filter = [["tournament", admin.RelatedOnlyFieldListFilter], "round_number"]
    search_fields = [
        "player__first_name_ru", "player__first_name_en",
        "player__last_name_ru", "player__last_name_en",
    ]
    ordering = ["tournament", "round_number", "-score"]


admin.site.register(TournamentRoundResult, TournamentRoundResultAdmin)
admin.site.register(Tournament, TournamentAdmin)
admin.site.register(OnlineTournamentConfig, OnlineTournamentConfigAdmin)
admin.site.register(TournamentRegistration, TournamentRegistrationAdmin)
admin.site.register(OnlineTournamentRegistration, OnlineTournamentRegistrationAdmin)
admin.site.register(MsOnlineTournamentRegistration, MsOnlineTournamentRegistrationAdmin)
admin.site.register(TournamentApplication, TournamentApplicationAdmin)
admin.site.register(TournamentResult, TournamentResultAdmin)
