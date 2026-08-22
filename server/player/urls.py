# -*- coding: utf-8 -*-

from django.urls import re_path as url

from player.views import (
    player_details,
    player_ms_details,
    player_rating_changes,
    player_rating_details,
    player_tenhou_details,
    player_tournaments,
)

urlpatterns = [
    url(r"^(?P<player_id>\d+)/$", player_details, name="player_details"),
    url(r"^(?P<player_id>\d+)/(?P<year>\d+)/(?P<month>\d+)/(?P<day>\d+)/$", player_details, name="player_details"),
    url(r"^(?P<player_id>\d+)/tenhou/$", player_tenhou_details, name="player_tenhou_details"),
    url(r"^(?P<player_id>\d+)/ms/$", player_ms_details, name="player_ms_details"),
    url(r"^(?P<player_id>\d+)/tournaments/$", player_tournaments, name="player_tournaments"),
    url(r"^(?P<player_id>\d+)/(?P<rating_slug>[\w\-]+)/details/$", player_rating_details, name="player_rating_details"),
    url(
        r"^(?P<player_id>\d+)/(?P<rating_slug>[\w\-]+)/details/(?P<year>\d+)/(?P<month>\d+)/(?P<day>\d+)/$",
        player_rating_details,
        name="player_rating_details",
    ),
    url(r"^(?P<player_id>\d+)/(?P<rating_slug>[\w\-]+)/changes/$", player_rating_changes, name="player_rating_changes"),
    url(
        r"^(?P<player_id>\d+)/(?P<rating_slug>[\w\-]+)/changes/(?P<year>\d+)/(?P<month>\d+)/(?P<day>\d+)/$",
        player_rating_changes,
        name="player_rating_changes",
    ),
]
