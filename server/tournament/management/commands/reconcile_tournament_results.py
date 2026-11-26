# -*- coding: utf-8 -*-

from django.core.management.base import BaseCommand, CommandError

from tournament.models import Tournament
from tournament.reconciliation import build_reconciliation_report


class Command(BaseCommand):
    help = (
        "Compares TournamentResult.scores (the final imported total per player) against "
        "the sum of TournamentRoundResult.total (score + uma + penalty) across all rounds, "
        "for the same player, within one tournament. Flags any mismatch."
    )

    def add_arguments(self, parser):
        parser.add_argument("tournament_id", type=int, help="Tournament id to reconcile")

    def handle(self, *args, **options):
        tournament_id = options["tournament_id"]
        try:
            tournament = Tournament.objects.get(id=tournament_id)
        except Tournament.DoesNotExist:
            raise CommandError("Tournament with id={} does not exist".format(tournament_id))

        report = build_reconciliation_report(tournament)

        self.stdout.write("Reconciliation for: {}\n".format(tournament))
        self.stdout.write(
            "{:<32}{:>18}{:>18}{:>10}".format("Player", "TournamentResult", "Sum of rounds", "Diff")
        )
        self.stdout.write("-" * 78)

        for row in report["rows"]:
            player_name = row["player"].full_name if row["player"] else "—"
            scores = row["scores"]

            if not row["has_round_data"]:
                self.stdout.write(
                    self.style.WARNING("{:<32}{:>18}{:>18}".format(player_name, str(scores), "no round data"))
                )
                continue

            line = "{:<32}{:>18}{:>18}{:>10}".format(player_name, str(scores), row["round_sum"], row["diff"])
            if row["mismatch"]:
                self.stdout.write(self.style.ERROR(line + "  <-- MISMATCH"))
            else:
                self.stdout.write(line)

        if report["orphan_rows"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "{} player(s) have round results but no TournamentResult row at all:".format(
                        len(report["orphan_rows"])
                    )
                )
            )
            for row in report["orphan_rows"]:
                self.stdout.write("  - {} (round total: {})".format(row["player"], row["round_sum"]))

        self.stdout.write("")
        self.stdout.write("Checked: {}, Mismatches: {}".format(report["checked_count"], report["mismatches_count"]))
        if report["mismatches_count"]:
            self.stdout.write(self.style.ERROR("RECONCILIATION FAILED — see mismatches above"))
        else:
            self.stdout.write(self.style.SUCCESS("All matched players reconcile correctly"))
