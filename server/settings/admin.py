# -*- coding: utf-8 -*-

from django import forms
from django.contrib import admin

from settings.models import City, Country

# Импортируем компоненты стороннего пакета
from import_export import resources
from import_export.admin import ImportExportModelAdmin

class CountryResource(resources.ModelResource):
    class Meta:
        model = Country
        # Указываем, какие поля импортировать (необязательно, по умолчанию — все)
        fields = ('name',	'code2',	'code',	'iso') 
        # Поле, по которому система поймет: обновить существующую запись или создать новую
        import_id_fields = ('code',)

class CountryAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_classes = [CountryResource]
    
    list_display = ["code2", "code", "name"]


class CityForm(forms.ModelForm):
    class Meta:
        model = City
        exclude = ["name"]


class CityAdmin(admin.ModelAdmin):
    form = CityForm
    list_display = ["name"]
    search_fields = ["name_ru", "name_en"]

    prepopulated_fields = {"slug": ["name_en"]}


admin.site.register(Country, CountryAdmin)
admin.site.register(City, CityAdmin)
