# -*- coding: utf-8 -*-

from django import forms
from django.contrib import admin
from django.utils.text import slugify

from player.models import Player, PlayerQuotaEvent, PlayerTitle
from settings.models import Country

from player.tenhou.models import TenhouNickname

from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget
from import_export.formats import base_formats
from import_export.forms import ImportForm, ConfirmImportForm


class PlayerImportForm(ImportForm):
    only_new = forms.BooleanField(
        required=False,
        initial=False,
        label="Импортировать только новых игроков",
        help_text="Существующие игроки (найденные по slug) будут пропущены, а не обновлены.",
    )


class PlayerConfirmImportForm(ConfirmImportForm):
    only_new = forms.BooleanField(required=False, widget=forms.HiddenInput)

class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        exclude = ["first_name", "last_name"]


class TenhouNicknameInline(admin.TabularInline):
    model = TenhouNickname
    extra = 1

class PlayerResource(resources.ModelResource):
    country = fields.Field(
        column_name='country',
        attribute='country',
        widget=ForeignKeyWidget(Country, field='code2')
    )

    def __init__(self, only_new=False, **kwargs):
        super().__init__(**kwargs)
        self.only_new = only_new

    class Meta:
        model = Player
        fields = ('ema_id', 'first_name', 'last_name', 'country')
        import_id_fields = ('first_name', 'last_name')

    def before_import_row(self, row, **kwargs):
        row['first_name'] = str(row.get('first_name') or '').strip()
        row['last_name'] = str(row.get('last_name') or '').strip()

    def get_or_init_instance(self, instance_loader, row):
        first_name = row.get('first_name', '')
        last_name = row.get('last_name', '')
        try:
            instance = Player.objects.get(first_name=first_name, last_name=last_name)
            return instance, False
        except Player.DoesNotExist:
            return self.init_instance(row), True

    def skip_row(self, instance, original, row, import_validation_errors=None):
        if self.only_new and original.pk:
            return True
        return super().skip_row(instance, original, row, import_validation_errors)
    
#@admin.register(Player)
class PlayerAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_classes = [PlayerResource]
     #   list_display = ('ema_id', 'first_name', 'last_name','country')
    form = PlayerForm
    inlines = [TenhouNicknameInline]

    import_form_class = PlayerImportForm
    confirm_form_class = PlayerConfirmImportForm

    list_display = ["ema_id", "first_name","last_name", "city", "pantheon_id"]
    list_filter = ["is_hide", "is_ema_guest", "country"]
    search_fields = ["first_name_ru", "first_name_en", "last_name_ru", "last_name_en", "ema_id"]
    
    def get_import_formats(self):
        """Переопределяем разделитель для CSV формата на ';'"""
        formats = super().get_import_formats()
        for fmt in formats:
            if isinstance(fmt, base_formats.CSV):
                # Меняем разделитель. По умолчанию библиотека использует openpyxl/csv-пакет
                fmt.kwargs = {'delimiter': ';'}  
        return formats
    
    def get_queryset(self, request):
        return Player.objects.all()

    # --- переносим значение чекбокса с шага "выбор файла" на шаг "подтверждение" ---
    def get_confirm_form_initial(self, request, import_form):
        initial = super().get_confirm_form_initial(request, import_form)
        if import_form:
            initial['only_new'] = import_form.cleaned_data.get('only_new', False)
        return initial

    def get_import_resource_kwargs(self, request, *args, **kwargs):
        resource_kwargs = super().get_import_resource_kwargs(request, *args, **kwargs)
        form = kwargs.get('form')
        only_new = False
        if form is not None and hasattr(form, 'cleaned_data'):
            only_new = form.cleaned_data.get('only_new', False)
        resource_kwargs['only_new'] = only_new
        return resource_kwargs   

class PlayerTitleForm(forms.ModelForm):
    class Meta:
        model = Player
        exclude = ["text"]


class PlayerTitleAdmin(admin.ModelAdmin):
    form = PlayerTitleForm

    search_fields = ["player__last_name", "player__first_name"]
    list_display = ["player", "text", "background_color", "text_color"]
    raw_id_fields = ["player"]


class PlayerQuotaEventAdmin(admin.ModelAdmin):
    search_fields = ["player__first_name_ru", "player__first_name_en", "player__last_name_ru", "player__last_name_en"]
    list_display = ["player", "type", "place", "state", "federation_member"]
    list_filter = ["type", "state"]
    raw_id_fields = ["player"]


admin.site.register(Player, PlayerAdmin)
admin.site.register(PlayerQuotaEvent, PlayerQuotaEventAdmin)
admin.site.register(PlayerTitle, PlayerTitleAdmin)

