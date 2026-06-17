"""
Shot Forest — data pipeline.

Pulls Minnesota Timberwolves field-goal attempts for the 2025-26 season from NBA
Stats (via nba_api) for BOTH the regular season and the playoffs, bins them into a
hex grid, computes league-relative efficiency, and writes one render-ready JSON.

The app exposes a season-type selector: Regular Season / Playoffs / Full (combined).
If the team has no postseason data, the Playoffs option is simply omitted.

RUN THIS ON YOUR OWN COMPUTER (not a server) — NBA Stats blocks most cloud IPs.

    pip install -r requirements.txt
    python build_data.py

Output: ../data/shot-forest.json
"""

import os
import json
import time
import datetime as dt

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- config
TEAM_ID = 1610612750          # Minnesota Timberwolves
SEASON = "2025-26"
HEX_RADIUS = 25.5             # court units (tenths of a foot); tune for density
MIN_ATTEMPTS = 2              # below this a hex is flagged low_volume
XLIM = (-250, 250)
YLIM = (-47.5, 422.5)

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "shot-forest.json")


# ---------------------------------------------------------------- fetch
def _shotchart(player_id, season_type):
    """One ShotChartDetail call (with retries). Returns (shots_df, league_df)."""
    from nba_api.stats.endpoints import shotchartdetail
    last_err = None
    for attempt in range(4):
        try:
            r = shotchartdetail.ShotChartDetail(
                team_id=TEAM_ID,
                player_id=player_id,              # 0 = whole team; else one player
                season_nullable=SEASON,
                season_type_all_star=season_type,   # "Regular Season" | "Playoffs"
                context_measure_simple="FGA",       # FGA = makes AND misses
                timeout=60,
            )
            dfs = r.get_data_frames()
            return dfs[0], dfs[1]
        except Exception as e:                    # noqa: BLE001
            last_err = e
            print(f"  [{season_type} pid={player_id}] attempt {attempt + 1} failed: {e}  (retry 4s)")
            time.sleep(4)
    raise SystemExit(
        f"\nNBA Stats fetch failed for '{season_type}' after several tries.\n"
        "This endpoint blocks servers/VPNs — run on your home network, off any VPN.\n"
        "Last error: " + str(last_err)
    )


def fetch_team(season_type):
    """Team-wide pull (player_id=0). Reliable for the regular season."""
    return _shotchart(0, season_type)


def fetch_playoffs(roster_ids):
    """Postseason pull.

    The team-wide player_id=0 call is unreliable for playoffs (often returns
    empty even when games exist), so we try it first, then fall back to fetching
    each rostered player individually and concatenating.
    """
    shots, league = fetch_team("Playoffs")
    if shots is not None and len(shots) > 0:
        return shots, league

    print("  team-wide playoff query was empty — fetching per player ...")
    frames, lg = [], league
    for pid in roster_ids:
        s, l = _shotchart(int(pid), "Playoffs")
        if s is not None and len(s) > 0:
            frames.append(s)
        if (lg is None or len(lg) == 0) and l is not None and len(l) > 0:
            lg = l
        time.sleep(0.6)                          # be polite to the API
    shots = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return shots, lg


# ---------------------------------------------------------------- geometry
def hex_centers(r):
    dx, dy = r * np.sqrt(3), r * 1.5
    centers, row, y = [], 0, YLIM[0]
    while y <= YLIM[1] + dy:
        offset = (dx / 2) if (row % 2) else 0
        x = XLIM[0] - dx
        while x <= XLIM[1] + dx:
            centers.append((x + offset, y))
            x += dx
        y += dy
        row += 1
    return np.array(centers)


def nearest_center(points, centers):
    pts = points.astype(float)
    out = np.empty(len(pts), dtype=int)
    step = 2000
    for i in range(0, len(pts), step):
        chunk = pts[i:i + step]
        d2 = ((chunk[:, None, 0] - centers[None, :, 0]) ** 2 +
              (chunk[:, None, 1] - centers[None, :, 1]) ** 2)
        out[i:i + step] = d2.argmin(axis=1)
    return out


# ---------------------------------------------------------------- aggregation
def league_lookup(league_df):
    g = league_df.groupby(["SHOT_ZONE_BASIC", "SHOT_ZONE_RANGE"])[["FGM", "FGA"]].sum()
    return (g["FGM"] / g["FGA"].clip(lower=1)).to_dict()


def build_hexes(df, centers, lg):
    df = df.assign(_hex=nearest_center(df[["LOC_X", "LOC_Y"]].values, centers))
    is3 = df["SHOT_TYPE"].str.startswith("3")
    out = []
    for hxi, d in df.groupby("_hex"):
        att = len(d)
        makes = int(d["SHOT_MADE_FLAG"].sum())
        made3 = int((is3.loc[d.index] & (d["SHOT_MADE_FLAG"] == 1)).sum())
        made2 = makes - made3
        lvals = [lg.get((zb, zr), np.nan)
                 for zb, zr in zip(d["SHOT_ZONE_BASIC"], d["SHOT_ZONE_RANGE"])]
        lvals = [v for v in lvals if v == v]
        lg_fg = float(np.mean(lvals)) if lvals else None
        fg = makes / att
        cx, cy = centers[hxi]
        out.append({
            "id": f"h_{int(hxi)}",
            "x": round(float(cx), 1), "y": round(float(cy), 1),
            "att": att, "makes": makes, "fg_pct": round(fg, 3),
            "league_fg_pct": round(lg_fg, 3) if lg_fg is not None else None,
            "vs_league": round((fg - lg_fg) * 100, 1) if lg_fg is not None else None,
            "pps": round((2 * made2 + 3 * made3) / att, 3),
            "efg": round((makes + 0.5 * made3) / att, 3),
            "low_volume": att < MIN_ATTEMPTS,
        })
    return out


def totals(df):
    att = len(df)
    makes = int(df["SHOT_MADE_FLAG"].sum())
    return {"att": att, "makes": makes, "fg_pct": round(makes / max(att, 1), 3)}


def build_dataset(shots, centers, lg):
    """One season type -> {players: [...], scopes: {TEAM, <pid>: ...}}."""
    scopes = {"TEAM": {"label": "All Wolves", "totals": totals(shots),
                       "hexes": build_hexes(shots, centers, lg)}}
    counts = (shots.groupby(["PLAYER_ID", "PLAYER_NAME"]).size()
              .reset_index(name="att").sort_values("att", ascending=False))
    players = []
    for _, p in counts.iterrows():
        pid, name = int(p["PLAYER_ID"]), p["PLAYER_NAME"]
        d = shots[shots["PLAYER_ID"] == pid]
        scopes[str(pid)] = {
            "label": name,
            "headshot": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png",
            "totals": totals(d),
            "hexes": build_hexes(d, centers, lg),
        }
        players.append({"id": pid, "name": name, "att": int(p["att"])})
    return {"players": players, "scopes": scopes}


def compute_ranges(datasets):
    allh = [h for ds in datasets.values() for s in ds["scopes"].values() for h in s["hexes"]]
    def rng(key):
        vals = [h[key] for h in allh if h.get(key) is not None]
        if not vals:
            return [0, 1]
        a = np.array(vals, float)
        return [round(float(a.min()), 3), round(float(np.percentile(a, 95)), 3)]
    return {k: rng(k) for k in ("att", "fg_pct", "vs_league", "pps", "efg")}


def clean(df):
    return df[df["LOC_X"].between(*XLIM) & df["LOC_Y"].between(*YLIM)].copy()


# ---------------------------------------------------------------- main
def main():
    centers = hex_centers(HEX_RADIUS)

    print("Fetching regular season ...")
    reg_shots, reg_league = fetch_team("Regular Season")
    reg_shots = clean(reg_shots)
    reg_lg = league_lookup(reg_league)
    print(f"  {len(reg_shots)} regular-season shots")

    roster_ids = reg_shots["PLAYER_ID"].unique()
    print("Fetching playoffs ...")
    pl_shots, pl_league = fetch_playoffs(roster_ids)
    pl_shots = clean(pl_shots) if pl_shots is not None else pd.DataFrame()
    has_playoffs = len(pl_shots) > 0
    print(f"  {len(pl_shots)} playoff shots"
          + ("" if has_playoffs else "  (no postseason data — Playoffs option will be omitted)"))

    datasets = {"regular": build_dataset(reg_shots, centers, reg_lg)}
    season_types = [{"key": "regular", "label": "Regular Season"}]

    if has_playoffs:
        pl_lg = league_lookup(pl_league)
        datasets["playoffs"] = build_dataset(pl_shots, centers, pl_lg)
        # Full = regular + playoffs combined; baseline = regular-season league avgs
        full_shots = pd.concat([reg_shots, pl_shots], ignore_index=True)
        datasets["full"] = build_dataset(full_shots, centers, reg_lg)
        season_types += [{"key": "playoffs", "label": "Playoffs"},
                         {"key": "full", "label": "Full Season"}]

    out = {
        "meta": {
            "team": "Minnesota Timberwolves", "season": SEASON,
            "source": "NBA Stats via nba_api (ShotChartDetail)",
            "pulled_at": dt.date.today().isoformat(),
            "hex_radius_units": HEX_RADIUS, "min_attempts": MIN_ATTEMPTS,
            "default_season_type": "regular",
            "season_types": season_types,
            "ranges": compute_ranges(datasets),
            "notes": "Playoff hexes use playoff league averages; Full uses regular-season league averages as the baseline.",
        },
        "data": datasets,
    }

    os.makedirs(os.path.dirname(os.path.abspath(OUT_PATH)), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)

    print(f"\nDone. Wrote {os.path.abspath(OUT_PATH)}")
    print("  season types:", ", ".join(s["key"] for s in season_types))
    reg = datasets["regular"]
    print(f"  regular: {len(reg['players'])} players · {reg['scopes']['TEAM']['totals']['att']} attempts")
    print("  top 5:", ", ".join(f"{p['name']} ({p['att']})" for p in reg["players"][:5]))
    if has_playoffs:
        pl = datasets["playoffs"]
        print(f"  playoffs: {len(pl['players'])} players · {pl['scopes']['TEAM']['totals']['att']} attempts")


if __name__ == "__main__":
    main()
