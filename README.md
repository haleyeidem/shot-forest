# Shot Forest

An interactive shot chart for the 2025–26 Minnesota Timberwolves — planted as a forest.

Each tree grows where someone takes a shot. The bigger the tree, the more frequent the shot. The brighter the tree, the better that shot goes down compared to the rest of the league.

🌲 **[Live demo →](https://haleyeidem.github.io/shot-forest/)**

---

## How to read it

- **Tree size** = shot volume from that hex (square-root scale so the rim doesn't drown the rest of the forest).
- **Tree color** = the player's FG% from that hex vs. the league's FG% from the *same hex* — a spatial comparison, not a zone-level one.
- **Hex grid** = the same bins as a Goldsberry-style hex chart, rendered as the iconic Timberwolves pine.

The toggle next to the player switcher flips between **Regular Season**, **Playoffs**, and **Full Season** (whichever the latest data pull contains).

---

## Run it locally

It's a single static HTML page. No build step.

```bash
git clone git@github.com:haleyeidem/shot-forest.git
cd shot-forest
python3 -m http.server 8000        # any static server works
open http://localhost:8000
```

---

## Regenerate the data

Shots come from the NBA Stats `ShotChartDetail` endpoint via [nba_api](https://github.com/swar/nba_api). NBA Stats blocks most cloud IPs, so this script must run on your home network (no VPN).

```bash
cd tools
pip install -r requirements.txt
python build_data.py
```

This writes `data/shot-forest.json` with regular-season, playoff, and full-season scopes (whichever exist). The UI picks them up automatically — `meta.season_types` drives the season toggle.

---

## Deploy to GitHub Pages

Repository → Settings → Pages → Source: **`main`** branch, **`/ (root)`**. Save. The site comes up at `https://haleyeidem.github.io/shot-forest/` within a minute or two.

---

## Methodology

- **Source.** NBA Stats `ShotChartDetail` via `nba_api`, season `2025-26`, team `Minnesota Timberwolves`.
- **Bins.** Hexagonal grid, radius ≈ 2.5 ft (25.5 court units), full half-court.
- **League baseline.** For each hex, the league's FG% is computed across all NBA players' shots in that same hex this season. The "vs league" delta is a spatial comparison — not "all corner threes," not "all paint shots," but *that exact spot*.
- **Low volume.** Hexes with fewer than 2 attempts are dropped to keep the chart honest.
- **Stylization.** The chart raises the visual baseline to sit just behind the rim so trees plant where the eye expects them; all other court proportions remain faithful to NBA dimensions.

---

## Stack

- Static HTML + a tiny in-house runtime that turns one declarative `.dc.html` file into a streaming React component.
- Shot chart is hand-rolled SVG (no D3) so type, glow, and hex-to-tree mapping stay tunable.
- One static JSON file dropped next to the page; fetched on load. No backend, no server.
- Hosted on GitHub Pages.

---

## Credits

- **Data** — NBA Stats via [nba_api](https://github.com/swar/nba_api)
- **Type** — Big Shoulders Display, Roboto Slab, Hanken Grotesk, JetBrains Mono (Google Fonts)
- **Design + build** — Haley Eidem

An independent, unofficial concept. Not affiliated with the Minnesota Timberwolves or the NBA.
