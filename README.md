# Taiwan Economics Collaboration Map

Who works with whom in Taiwan’s economics research community, and how do those connections spread across institutions?

This side project brings together faculty rosters, publication records and research projects to explore that question. It follows two kinds of collaboration from 2015 to 2026: writing a paper together and participating in the same research project. An interactive map connects these networks to the institutions where researchers work.

## Live Demo

[Open the interactive Taiwan Economics Collaboration Map](https://laipohsun.github.io/taiwan-economics-collaboration/)

## Open the map

Download this repository using **Code → Download ZIP**, extract it, and open [`index.html`](index.html) in a browser. You can also open [`html/map_explorer.html`](html/map_explorer.html) directly. No installation, Python environment or server is needed. GitHub’s file viewer displays the HTML source; download the file or use a GitHub Pages deployment to interact with it.

The interface is in Traditional Chinese. Start with these controls:

- Use the two year sliders to select a year or a range within 2015–2026.
- Switch between coauthorship, shared projects and both layers.
- Click a county, institution or researcher to explore its connections.
- Switch from the map to the network view to inspect individual relationships.
- Include external coauthors, filter within or across institutions, and adjust the minimum collaboration count.
- Click a relationship to inspect the publications or projects behind it.

The map includes its display data and geographic boundaries in the HTML file. It does not fetch CSV files or load libraries from a CDN. Links to researcher profiles and source websites require an internet connection.

## Coverage

The starting roster contains **520 researchers across 27 institutions**, including economics, political economy and agricultural economics units, alongside selected Academia Sinica researchers. Of those researchers, 421 have a publication or project record in the study window; 99 have neither in the collected records.

The bundled map contains 421 roster researchers, 4,048 external coauthors, 5,085 publication entries and 1,975 project-year entries. These are counts from the HTML snapshot. The local cleaned publication table contains 5,099 records; the viewer and the full table are not interchangeable exports.

“External” means outside the roster, including collaborators at the same institution. It does not necessarily mean overseas. The roster is a collection-time snapshot, not a reconstruction of every researcher’s employment history. Records for 2026 are incomplete at collection time in September 2026.

## How the records were collected

### Faculty roster and locations

The roster starts from the Ministry of Education’s 114 academic-year institution and program listings. Faculty records were collected from its university directory and supplemented with official institutional pages for units missing from that directory. Names, appointments and institutional affiliations were reconciled into a roster with a stable `teacher_id` for each person. Cross-institution name collisions were reviewed when assigning a primary institution.

Institutional and faculty pages supply profile links, name variants and identifiers used to locate the corresponding NSTC researcher page. Campus coordinates come from the geographic preparation workflow; they represent institutions or campus centers, not researchers’ exact addresses.

### Publications and funded projects

The collaboration records used here come from NSTC researcher profiles. For each resolved profile identifier (`rsNo`), the crawler requests two HTML tables:

| NSTC tab | Fields collected |
| --- | --- |
| Publication list (`initRsm05`) | Publication date, category, title, author list and venue |
| Project overview (`initRsm17new`) | ROC year, grant category, discipline code, project title and role |

The parser identifies columns by their table-header labels. A page with unexpected headers is logged as a parsing problem instead of being treated as an empty record. An explicit “no records” response is handled separately.

Requests are cached on disk and use delays and retries. Each extracted row retains a source record identifier, its roster owner and retrieval time, so the cleaned records can be traced back to the collection step. Departmental and personal publication lists are not added as a second publication corpus in this final dataset.

The initial crawlers live in the local preparation workspace and are not included in this repository. The published pipeline starts from their prepared outputs; it is not a fresh-install crawler for the entire collection process.

### Author and affiliation enrichment

OpenAlex supplies additional author identifiers, publication and citation totals, research fields and affiliation evidence. Candidate author matches are checked against identifiers and appearances in the researcher’s known papers. These totals describe the OpenAlex profile at retrieval time, rather than only the 2015–2026 study window.

External affiliations also use publication metadata, journal PDF author notes and documented source checks. The merge prefers verified corrections, then journal evidence, matched works, last-known OpenAlex affiliation, Crossref metadata and prior evidence. Original affiliation text is retained alongside normalized institution names. Unresolved identities and missing affiliations remain marked as such.

## How the records become networks

### Papers and author sets

Publication records are restricted to 2015–2026. The earliest recorded publication year determines the annual assignment; conflicting year candidates are retained in `year_candidates_json` and flagged with `year_ambiguous`.

The final merge groups records by normalized title and author-node set. Records with the same title and the same authors are merged, with their source identifiers preserved. Matching titles alone do not establish that two papers are identical. Within records already flagged for conflicting author sets, the current rule selects the largest observed set before applying documented author-list corrections.

Author-list repairs address broken separators, surname/initial fragments and incomplete lists. The current build caps lists at the first ten authors in source order. This affects collaboration counts for larger teams. Records with unresolved problems stay in the publication table, but `edge_eligible` and `edge_hold_reason` determine whether they contribute network edges.

Every eligible paper produces an undirected pair for each retained pair of authors. Each row retains `paper_id`, `year`, endpoint identifiers and source references. Repeated collaborations are stored as separate events before aggregation.

### Project years and project families

The source does not provide a shared project identifier. Annual entries are grouped by normalized project title and year, with ROC years converted by adding 1911. Entries with the same normalized title across years are also grouped into a **project family**.

The project network connects roster members in a family in every year that family appears. This can infer a relationship in a year when only one endpoint registered the project. `both_recorded_this_year = 1` identifies the stricter subset where both researchers recorded it that year.

Title matching can join unrelated projects with identical names. It is an explicit construction rule, not proof of a shared grant. This layer only observes roster members who independently recorded a matching project; non-roster project participants are not recoverable from these records.

### Keys, weights and aggregation

| Key | Purpose |
| --- | --- |
| `teacher_id` | Stable roster identity |
| `node_id` | Network identity for roster and external authors; equals `teacher_id` for roster members |
| `paper_id` | Publication and its coauthorship events |
| `project_key` | Annual project record |
| `project_family_key` | Same-title project family across years |
| `source_record_ids_json` | Link back to contributing source rows |

For a team of size `n`, edge tables retain both `weight_1n = 1/n` and `weight_pair = 1/C(n, 2)`. The latter gives each paper or project-year event a total pair weight of one. A time-window network is built by filtering events by year, grouping undirected endpoint pairs within each layer, then counting events or summing the chosen weights.

## How the map is drawn

Python prepares the nodes, event edges, publication lists, simplified county boundaries and a simplified world basemap, then embeds them in a single HTML document. Browser-side JavaScript draws the map and network with SVG and handles filtering and navigation.

At the national scale, researchers are grouped into institutional circles and relationships are aggregated between institutions. Northern Taiwan is dense, so the national view draws smaller circles and hides some institutions: Taipei City and New Taipei City show only National Taiwan University, National Chengchi University, the Institute of Economics at Academia Sinica and National Taipei University, and National Ilan University, Fo Guang University, National Taiwan Ocean University and Ming Chuan University are also hidden. Hidden institutions and their connections appear, and circles return to full size, after selecting a county or zooming in with the scroll wheel or the magnifier buttons at the lower right of the map. Opening an institution expands its researchers. The network view supports force-directed and circular layouts, with label propagation used for community coloring.

The whole map uses one azimuthal equidistant projection centred on Taiwan (23.7°N, 121°E). Distances and bearings measured from Taiwan are to scale, and a straight line leaving Taiwan follows the great-circle route; distances between two places elsewhere are distorted, increasingly so far from Taiwan. The default view frames Taiwan. Zoom out or use **看全世界** to see the rest of the world. Other countries come from Natural Earth 1:50m boundaries and serve only as background: they have no subdivisions and cannot be clicked.

Roster institutions use their campus coordinates. Non-roster institutions, in Taiwan and overseas, are drawn at the institution's own location. Each affiliation is matched to an OpenAlex institution, through the coauthor's OpenAlex affiliations or a reviewed decision table. The map uses the institution's Wikidata coordinate when it lies within 80 km of the OpenAlex city coordinate, and the OpenAlex/ROR city coordinate otherwise; each institution's panel names the source. Coauthors without an affiliation, and affiliations that could not be located, are placed at the North Pole. That position is a placeholder, not a location. Geographic distance should be calculated from coordinates, not measured from the displayed layout.

## Repository and rebuilding

The repository contains the visualization pipeline, the rendered map and this documentation. Raw pages, API caches, CSV tables, spreadsheets and review decisions are excluded by `.gitignore`. **The HTML still contains the records needed to display the map; excluding separate data files does not make those embedded records private.**

| Location | Contents |
| --- | --- |
| `index.html` | Entry point for the interactive map |
| `html/map_explorer.html` | Standalone map snapshot |
| `code/pipeline.py` | Cleaning, network construction, enrichment and rendering |

Viewing the map requires only a browser. Rebuilding requires the excluded input tables, geographic boundaries, caches and review decisions. The current pipeline expects preparation folders such as `faculty_and_map`, `faculty_identity`, `collab_pubs` and `collab_network` beside this repository directory. If your preparation folders live elsewhere, their input paths must be adapted before running the pipeline.

The world basemap (`ne_50m_admin_0_countries.geojson` from Natural Earth) is read from the preparation basemap folder or `basemap copy/`. Institution locations come from `cache/institution_geo.json` and `manual_review/decisions/external_institution_geo.csv`. When online, `--html` fills in institutions missing from the cache with OpenAlex filter queries (1 credit per 50 institutions) and Wikidata's public SPARQL endpoint; with `--offline` it uses the cache only.

With the local inputs restored, the workflow is:

```bash
# Run from the repository root. Requires the private preparation inputs.
python3 -m pip install matplotlib openpyxl pypdf
python3 code/pipeline.py --offline

# Render the viewer to its published location.
python3 code/pipeline.py --html --out "$PWD/html/map_explorer.html"

# Render a static network for a selected time window.
python3 code/pipeline.py --map --layer both --year-from 2020 --year-to 2023
```

The default pipeline runs author-list repair, dataset construction, OpenAlex enrichment, journal affiliation extraction, affiliation merging and review-sheet generation. Crossref enrichment is optional (`--with-crossref`). Offline mode uses existing local inputs and caches; it cannot recreate missing source data. Online OpenAlex requests read `OPENALEX_API_KEY` from the environment or the local key file used by the pipeline.

To publish the viewer with GitHub Pages, upload the contents of this directory as the repository root. In **Settings → Pages**, choose **Deploy from a branch**, select the uploaded branch and **/(root)**. The root `index.html` opens the map. Use the site URL shown by GitHub; no deployment URL is assumed here.

## Reading the results

These are observed records from a defined roster and a set of researcher profiles. Missing records do not establish that someone did no research. Name-only external identities can conflate different people, affiliation coverage is uneven, and current affiliations cannot describe historical moves. The author cap and project-family rules also affect connectivity. Comparisons across years or layers need to account for these collection and construction choices.
