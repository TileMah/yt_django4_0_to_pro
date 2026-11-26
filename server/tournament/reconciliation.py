# -*- coding: utf-8 -*-

from tournament.models import TournamentResult, TournamentRoundResult


def build_reconciliation_report(tournament):
    """
    Compares TournamentResult.scores (the final imported total per player) against the
    sum of TournamentRoundResult.total (score + uma + penalty) across all rounds, for the
    same player, within one tournament.
    """
    round_sums = {}
    players_by_id = {}

    round_results = TournamentRoundResult.objects.filter(tournament=tournament).select_related(
        "tournament", "player"
    )
    for round_result in round_results:
        round_sums[round_result.player_id] = round_sums.get(round_result.player_id, 0) + round_result.total
        players_by_id[round_result.player_id] = round_result.player

    results = (
        TournamentResult.objects.filter(tournament=tournament)
        .select_related("player")
        .order_by("place")
    )

    rows = []
    checked_player_ids = set()

    for result in results:
        checked_player_ids.add(result.player_id)
        round_sum = round_sums.get(result.player_id)
        scores = result.scores

        diff = None
        mismatch = False
        if round_sum is not None:
            scores_as_float = float(scores) if scores is not None else 0.0
            diff = scores_as_float - float(round_sum)
            mismatch = diff != 0

        rows.append(
            {
                "player": result.player,
                "scores": scores,
                "round_sum": round_sum,
                "diff": diff,
                "mismatch": mismatch,
                "has_round_data": round_sum is not None,
            }
        )

    orphan_rows = [
        {"player": players_by_id.get(player_id), "round_sum": round_sums[player_id]}
        for player_id in sorted(set(round_sums) - checked_player_ids)
    ]

    return {
        "tournament": tournament,
        "rows": rows,
        "orphan_rows": orphan_rows,
        "checked_count": len(rows),
        "mismatches_count": sum(1 for row in rows if row["mismatch"]),
    }
