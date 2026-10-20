# Merging two public data sources with pandas

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Licence](https://img.shields.io/badge/licence-MIT-green)

A Python script that extracts data from two independent public sources,
builds one DataFrame for each, and merges them on one or several columns.

| Source | Format | Data |
|---|---|---|
| [World Bank API](https://data.worldbank.org) | JSON | GDP per capita (current US$), by country and year |
| [Our World in Data](https://ourworldindata.org/co2-emissions) | CSV | CO₂ emissions per capita (tonnes), by country and year |

Both sources are free and need no API key.

---

## What the script does

```
 World Bank API (JSON)            Our World in Data (CSV)
         │                                  │
         │ 1. EXTRACT                       │ 2. EXTRACT
         ▼                                  ▼
   DataFrame gdp                      DataFrame co2
         │                                  │
         └──────────────┬───────────────────┘
                        │ 3. PREPARE the key columns
                        │    and CHECK they are unique
                        ▼
                        │ 4. MERGE
                        │    a) on country_code + year
                        │    b) on country_code
                        ▼
              merged_gdp_co2.csv
```

---

## Installation and usage

```bash
git clone https://github.com/YOUR-USERNAME/merge-public-data.git
cd merge-public-data
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python merge_public_data.py
```

The result is written to `merged_gdp_co2.csv`, in the folder the script
is run from.

### Settings

At the top of the script:

```python
START_YEAR = 2010
END_YEAR = 2022
OUTPUT_FILE = "merged_gdp_co2.csv"
```

To use another World Bank indicator, change the code at the end of
`WORLD_BANK_URL`, for example `SP.POP.TOTL` for population.

---

## The steps in detail

### Step 1: Extract the World Bank data (JSON)

Function: `extract_world_bank()`

The request asks for GDP per capita for all countries over the period:

```
https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD
    ?format=json&date=2010:2022&per_page=1000&page=1
```

The response is a JSON list of two items:

```json
[
  {"page": 1, "pages": ..., "per_page": 1000, "total": ...},
  [
    {"countryiso3code": "FRA", "country": {"value": "France"},
     "date": "2022", "value": ..., "...": "..."},
    "..."
  ]
]
```

- The first item gives the page number and the total number of pages.
- The second item holds the records.

The API returns at most `per_page` records per call, so the script asks
for page 1, 2, 3... until it reaches the last page. It then keeps four
fields: `country_code`, `country_name`, `year` and `gdp_per_capita`.

### Step 2: Extract the Our World in Data file (CSV)

Function: `extract_owid()`

The CSV file has four columns: `Entity`, `Code`, `Year`, and one value
column with a long descriptive name:

```
Entity,Code,Year,<CO₂ emissions per capita>
France,FRA,2022,...
```

The script renames them `country_name_owid`, `country_code`, `year` and
`co2_per_capita`. The value column is identified as "the column that is
not Entity, Code or Year", so the script keeps working if Our World in
Data renames it.

### Step 3: Prepare the keys

Function: `prepare()`

A merge matches rows whose key values are **exactly** equal. Two values
that look the same to a person can differ for pandas:

| Left | Right | Match? | Why |
|---|---|---|---|
| `2015` (number) | `"2015"` (text) | no | different types |
| `"FRA"` | `"fra"` | no | different case |
| `"FRA"` | `"FRA "` | no | trailing space |

So `prepare()` makes both DataFrames consistent:

- `country_code`: text, spaces removed, capital letters;
- `year`: whole number.

It then drops rows that cannot or should not be merged, and prints how
many it dropped:

- rows without a country code;
- regions in Our World in Data, whose codes start with `OWID_`
  (`OWID_WRL` is the world);
- years outside `START_YEAR`–`END_YEAR`.

Rows with an empty GDP value are also dropped: the newest year is often
not yet published.

### Step 4: Check that the keys are unique

Function: `check_unique()`

Before merging, the script checks that each `country_code` + `year`
pair appears only once in each DataFrame. Otherwise the merge
multiplies rows:

```
left:  FRA 2015 GDP=A      right: FRA 2015 CO2=X
       FRA 2015 GDP=B             FRA 2015 CO2=Y

merged: FRA 2015 A X
        FRA 2015 A Y
        FRA 2015 B X     4 rows instead of 1
        FRA 2015 B Y
```

If a key is duplicated, the script stops and shows an example.

### Step 5: Merge

Function: `merge_frames(left, right, on, how, validate)`

```python
merged = merge_frames(gdp, co2, on=["country_code", "year"],
                      how="inner", validate="one_to_one")
```

#### `on`: the key columns

The columns whose values must be equal for two rows to be joined.

- One column: `on=["country_code"]`
- Several columns: `on=["country_code", "year"]`. Two rows match only
  if **all** the key columns are equal.

#### `how`: which rows to keep

| `how` | Keeps | SQL equivalent |
|---|---|---|
| `"inner"` | rows whose key is in both DataFrames | `INNER JOIN` |
| `"left"` | every left row; right columns empty when no match | `LEFT JOIN` |
| `"right"` | every right row; left columns empty when no match | `RIGHT JOIN` |
| `"outer"` | every row of both | `FULL OUTER JOIN` |

#### `validate`: the expected relationship

pandas raises an error if the data breaks the stated relationship.

| `validate` | Meaning |
|---|---|
| `"one_to_one"` | each key at most once on each side |
| `"many_to_one"` | keys may repeat on the left, at most once on the right |
| `"one_to_many"` | at most once on the left, may repeat on the right |

#### The matching report

`merge_frames()` first runs an outer merge with `indicator=True`. pandas
then adds a `_merge` column saying where each key was found:
`both`, `left_only` or `right_only`. The function prints the counts and
the unmatched country codes:

```
keys ['country_code', 'year']: <n> matched, <n> only in left, <n> only in right
country_code values left_only: AFE, ..., WLD, XKX
```

The unmatched values are worth reading:

- `WLD` (world) and `AFE` (Africa Eastern and Southern) are regional
  aggregates, which only the World Bank provides by these codes.
- `XKX` is Kosovo: the World Bank uses `XKX`, Our World in Data uses
  `OWID_KOS`. Without the report, Kosovo would disappear from the
  result without notice.

The function then keeps the rows required by `how`.

---

## The two merges in the script

### Merge 1: on multiple columns

```python
keys = ["country_code", "year"]
merged = merge_frames(gdp, co2, on=keys, how="inner", validate="one_to_one")
```

One row per country and year, with both values side by side:

| country_code | country_name | year | gdp_per_capita | co2_per_capita |
|---|---|---|---|---|
| FRA | France | 2021 | ... | ... |
| FRA | France | 2022 | ... | ... |

This is the result saved to `merged_gdp_co2.csv`. The script also prints
the correlation between the two columns.

Merging on `country_code` alone would be wrong here: both DataFrames
have one row per year, so each GDP row would be paired with every CO₂
year of the same country. `validate="one_to_one"` would stop it.

### Merge 2: on one column

```python
avg_co2 = co2.groupby("country_code", as_index=False)["co2_per_capita"].mean()
with_avg = merge_frames(gdp, avg_co2, on=["country_code"],
                        how="left", validate="many_to_one")
```

- `avg_co2` has **one row per country**: the average CO₂ over the period.
- Merging on `country_code` attaches that average to every GDP row of
  the country.
- `"many_to_one"`: a country appears many times on the left (once per
  year) and once on the right.
- `how="left"` keeps every GDP row, even for a country without CO₂ data.

**Rule of thumb:** merge on one column when one side has one row per
value of that column. Otherwise, add columns to the key until each row
is identified uniquely.

---

## Adapting the script to other sources

1. Write an `extract_...()` function that returns a DataFrame.
2. Rename its columns so the key columns have the same names on both
   sides.
3. Pass the DataFrame through `prepare()`, or an equivalent that gives
   the keys the same type and format.
4. Call `check_unique()` on the key columns.
5. Call `merge_frames()` with the right `on`, `how` and `validate`.

If the key columns have different names in the two DataFrames,
`pd.merge` also accepts `left_on=` and `right_on=`, for example
`left_on="iso3", right_on="country_code"`.

---

## Project structure

```
merge-public-data/
├── merge_public_data.py    the script
├── requirements.txt        Python dependencies: requests, pandas
├── .gitignore              keeps the output file and .venv out of git
├── LICENSE
└── README.md
```

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `ConnectionError` or `Timeout` | no internet access, or a firewall blocks the site; check the URL in a browser |
| `HTTPError: 404` | the source changed its URL; check the address on its website |
| `ValueError: ... rows share the same ['country_code', 'year']` | a source returned duplicated keys; the message shows an example |
| `MergeError: Merge keys are not unique` | the `validate` argument does not match the data; check which side has repeated keys |
| Fewer merged rows than expected | read the unmatched country codes in the report: they show the coding differences between the two sources |

## Licence

MIT. The data belongs to its publishers: the World Bank (CC BY 4.0) and
Our World in Data (CC BY 4.0). Cite them when you reuse the data.
