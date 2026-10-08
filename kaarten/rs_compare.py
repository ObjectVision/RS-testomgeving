"""
rs_compare.py -- vergelijk de output-artefacten van twee RSopen-runs.

Onderdeel van het commit-vergelijk-instrument (pbl-nl/model-RSopen#16).
Vergelijkt buiten het model om (Python, op geexporteerde bestanden), zodat ook
commits van voor een meet-API-wijziging vergeleken kunnen worden.

Gebruik:
    python rs_compare.py <run_dir_a> <run_dir_b> --out <compare_dir>
                         [--name-a pre508] [--name-b head]
                         [--include-xml] [--max-samples 50] [--report]

Output (in <compare_dir>):
    compare.result.json      -- metingen (geen oordeel; het rapport oordeelt,
                                conform GeoDMS-Test TEST_OUTPUT_STANDARD schema 2)
    artifacts/<naam>_diff.tif        -- alleen geschreven bij verschil
    artifacts/<naam>_confusion.csv   -- categoriale grids: klasse x klasse
    artifacts/<naam>_sample.csv      -- top-N grootste verschillen met coordinaten
    artifacts/<naam>_{a,b,diff}.png  -- thumbnails voor het rapport
"""

import argparse
import csv
import filecmp
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
import tifffile
from PIL import Image

RASTER_EXTS = {".tif", ".tiff"}
TABLE_EXTS = {".csv"}
DEFAULT_EXCLUDES = ["*.xml", "*.tfw", "*/log/*", "*.log", "*.tmp", "*CalcCache*"]
PNG_MAX_DIM = 2400

GDAL_NODATA_TAG = 42113
MODEL_PIXEL_SCALE_TAG = 33550
MODEL_TIEPOINT_TAG = 33922
GEO_TAGS_PASSTHROUGH = (33550, 33922, 34735, 34736, 34737, 42113)


# ---------------------------------------------------------------- discovery

def discover_files(run_dir: str, excludes: list, only: str = None) -> dict:
    """Alle data-bestanden onder run_dir, als {relpath (posix, lowercase-key): relpath}.
    Met `only` doen alleen relpaths mee die dat glob-patroon matchen."""
    found = {}
    for root, _dirs, files in os.walk(run_dir):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, run_dir).replace("\\", "/")
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch("/" + rel, pat)
                   for pat in excludes):
                continue
            if only and not fnmatch.fnmatch(rel, only):
                continue
            found[rel.lower()] = rel
    return found


# ---------------------------------------------------------------- raster IO

def read_raster(path: str):
    """Lees eerste page van een (geo)tiff: (array, nodata, geo) met
    geo = (pixel_size_x, pixel_size_y, origin_x, origin_y) of None."""
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        arr = page.asarray()
        nodata = None
        tag = page.tags.get(GDAL_NODATA_TAG)
        if tag is not None:
            try:
                nodata = float(str(tag.value).strip())
            except ValueError:
                nodata = None
        geo = None
        scale = page.tags.get(MODEL_PIXEL_SCALE_TAG)
        tiepoint = page.tags.get(MODEL_TIEPOINT_TAG)
        if scale is not None and tiepoint is not None:
            sx, sy = scale.value[0], scale.value[1]
            # tiepoint: (i, j, k, x, y, z) -- pixel (i,j) ligt op wereld (x,y)
            tp = tiepoint.value
            origin_x = tp[3] - tp[0] * sx
            origin_y = tp[4] + tp[1] * sy
            geo = (sx, sy, origin_x, origin_y)
        extratags = []
        for code in GEO_TAGS_PASSTHROUGH:
            t = page.tags.get(code)
            if t is not None:
                extratags.append((code, t.dtype, t.count, t.value, False))
    return arr, nodata, geo, extratags


def valid_mask(arr: np.ndarray, nodata) -> np.ndarray:
    mask = np.ones(arr.shape, dtype=bool)
    if np.issubdtype(arr.dtype, np.floating):
        mask &= ~np.isnan(arr)
    if nodata is not None:
        if np.issubdtype(arr.dtype, np.floating) and np.isnan(nodata):
            pass  # al afgevangen
        else:
            mask &= arr != np.asarray(nodata).astype(arr.dtype)
    return mask


def is_categorical(arr_a: np.ndarray, arr_b: np.ndarray) -> bool:
    return np.issubdtype(arr_a.dtype, np.integer) and np.issubdtype(arr_b.dtype, np.integer)


# ---------------------------------------------------------------- thumbnails

def _downsample(arr: np.ndarray) -> np.ndarray:
    step = max(1, int(np.ceil(max(arr.shape) / PNG_MAX_DIM)))
    return arr[::step, ::step]


def _stable_palette(values: np.ndarray) -> dict:
    """Deterministische kleur per klassewaarde (zelfde kleur in run A en B)."""
    palette = {}
    for v in values:
        h = (int(v) * 2654435761) & 0xFFFFFF  # Knuth multiplicative hash
        r, g, b = (h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF
        palette[int(v)] = (64 + r // 2, 64 + g // 2, 64 + b // 2)
    return palette


def write_png_categorical(arr, mask, path: str, palette: dict):
    small, msmall = _downsample(arr), _downsample(mask)
    rgb = np.full(small.shape + (3,), 245, dtype=np.uint8)
    for v, col in palette.items():
        sel = msmall & (small == v)
        rgb[sel] = col
    Image.fromarray(rgb).save(path)


def write_png_numeric(arr, mask, path: str, lo=None, hi=None):
    small, msmall = _downsample(arr), _downsample(mask)
    vals = small[msmall]
    if vals.size == 0:
        lo, hi = 0.0, 1.0
    else:
        lo = float(np.percentile(vals, 2)) if lo is None else lo
        hi = float(np.percentile(vals, 98)) if hi is None else hi
    if hi <= lo:
        hi = lo + 1.0
    norm = np.nan_to_num(np.clip((small.astype(np.float64) - lo) / (hi - lo), 0, 1))
    gray = (255 - norm * 200).astype(np.uint8)  # donker = hoog
    rgb = np.stack([gray, gray, gray], axis=-1)
    rgb[~msmall] = (245, 245, 245)
    Image.fromarray(rgb).save(path)
    return lo, hi


def write_png_diffmask(base_arr, base_mask, diffmask, path: str):
    """Grijswaarde-achtergrond van run A met verschilcellen in rood."""
    small = _downsample(base_arr).astype(np.float64)
    msmall = _downsample(base_mask)
    dsmall = _downsample(diffmask)
    vals = small[msmall]
    lo, hi = (np.percentile(vals, 2), np.percentile(vals, 98)) if vals.size else (0, 1)
    if hi <= lo:
        hi = lo + 1
    norm = np.nan_to_num(np.clip((small - lo) / (hi - lo), 0, 1))
    gray = (235 - norm * 90).astype(np.uint8)
    rgb = np.stack([gray, gray, gray], axis=-1)
    rgb[~msmall] = (248, 248, 248)
    rgb[dsmall] = (214, 69, 61)
    Image.fromarray(rgb).save(path)


# ---------------------------------------------------------------- vergelijkers

def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def class_label(v: int, dtype) -> str:
    """GeoDMS schrijft null als maxwaarde van het integer-type (uint8: 255, uint16:
    65535, ...) zonder nodata-tag; -1 is onze eigen leeg-marker na aggregatie."""
    if v < 0 or (np.issubdtype(dtype, np.unsignedinteger)
                 and v == np.iinfo(dtype).max):
        return "geen"
    return str(int(v))


def rc_to_xy(rows, cols, geo):
    if geo is None:
        return [None] * len(rows), [None] * len(rows)
    sx, sy, ox, oy = geo
    x = ox + (np.asarray(cols) + 0.5) * sx
    y = oy - (np.asarray(rows) + 0.5) * sy
    return x, y


def compare_rasters(path_a, path_b, rel, art_dir, art_rel, max_samples):
    """Vergelijk twee rasters; retourneer comparison-dict (schema 2 metrics/artifacts)."""
    arr_a, nodata_a, geo_a, extratags_a = read_raster(path_a)
    arr_b, nodata_b, geo_b, _ = read_raster(path_b)
    comp = {"name": rel, "compare": None, "metrics": [], "artifacts": [], "notes": []}

    misaligned = (arr_a.shape != arr_b.shape
                  or (geo_a is not None and geo_b is not None
                      and not np.allclose(geo_a, geo_b)))
    if misaligned:
        if geo_a is None or geo_b is None:
            comp["compare"] = "cell"
            comp["notes"].append(f"shape mismatch zonder georeferentie: A={arr_a.shape} B={arr_b.shape}")
            comp["metrics"].append({"name": "shape_equal", "value": 0})
            return comp
        return compare_rasters_misaligned(arr_a, nodata_a, geo_a, arr_b, nodata_b, geo_b,
                                          rel, art_dir, art_rel, comp)

    mask_a, mask_b = valid_mask(arr_a, nodata_a), valid_mask(arr_b, nodata_b)
    both, either = mask_a & mask_b, mask_a | mask_b
    nodata_mismatch = int(np.count_nonzero(mask_a != mask_b))
    n_total = int(np.count_nonzero(either))
    base = sanitize(rel)

    if is_categorical(arr_a, arr_b):
        comp["compare"] = "cell_categorical"
        diff = both & (arr_a != arr_b)
        n_diff = int(np.count_nonzero(diff)) + nodata_mismatch
        comp["metrics"].append({"name": "cells", "unit": "cells",
                                "n_total": n_total, "n_diff": n_diff})
        if nodata_mismatch:
            comp["metrics"].append({"name": "nodata_mismatch", "unit": "cells",
                                    "n_total": n_total, "n_diff": nodata_mismatch})
        if n_diff:
            # confusion matrix (alleen cellen waar beide een waarde hebben)
            a_vals, b_vals = arr_a[diff], arr_b[diff]
            pairs, counts = np.unique(
                np.stack([a_vals, b_vals], axis=1), axis=0, return_counts=True)
            order = np.argsort(-counts)
            conf_fn = os.path.join(art_dir, f"{base}_confusion.csv")
            with open(conf_fn, "w", newline="", encoding="utf8") as f:
                w = csv.writer(f)
                w.writerow(["class_a", "class_b", "n_cells"])
                for i in order:
                    w.writerow([class_label(int(pairs[i][0]), arr_a.dtype),
                                class_label(int(pairs[i][1]), arr_b.dtype), int(counts[i])])
            comp["artifacts"].append({"kind": "confusion", "path": f"{art_rel}/{base}_confusion.csv"})

            diff_full = diff | (mask_a != mask_b)
            _write_diff_tif(art_dir, art_rel, base, diff_full.astype(np.uint8), extratags_a, comp)
            _write_sample_csv(art_dir, art_rel, base, diff_full, arr_a, arr_b,
                              mask_a, mask_b, geo_a or geo_b, max_samples, comp,
                              categorical=True)
            _thumbs_categorical(arr_a, mask_a, arr_b, mask_b, diff_full,
                                art_dir, art_rel, base, comp)
    else:
        comp["compare"] = "cell_numeric"
        fa = arr_a.astype(np.float64, copy=False)
        fb = arr_b.astype(np.float64, copy=False)
        delta = np.where(both, fb - fa, 0.0)
        diff = both & (delta != 0.0)
        n_diff = int(np.count_nonzero(diff)) + nodata_mismatch
        sum_a = float(np.sum(fa[mask_a])) if n_total else 0.0
        sum_b = float(np.sum(fb[mask_b])) if n_total else 0.0
        comp["metrics"].append({"name": "cells", "unit": "cells",
                                "n_total": n_total, "n_diff": n_diff})
        comp["metrics"].append({"name": "sum_a", "value": sum_a})
        comp["metrics"].append({"name": "sum_b", "value": sum_b})
        if nodata_mismatch:
            comp["metrics"].append({"name": "nodata_mismatch", "unit": "cells",
                                    "n_total": n_total, "n_diff": nodata_mismatch})
        if n_diff:
            absdelta = np.abs(delta)
            comp["metrics"].append({"name": "max_abs_diff", "value": float(absdelta.max())})
            comp["metrics"].append({"name": "mean_abs_diff_changed",
                                    "value": float(absdelta[diff].mean()) if diff.any() else 0.0})
            diff_full = diff | (mask_a != mask_b)
            _write_diff_tif(art_dir, art_rel, base, delta.astype(np.float32), extratags_a, comp)
            _write_sample_csv(art_dir, art_rel, base, diff_full, arr_a, arr_b,
                              mask_a, mask_b, geo_a or geo_b, max_samples, comp,
                              categorical=False)
            _thumbs_numeric(fa, mask_a, fb, mask_b, diff_full,
                            art_dir, art_rel, base, comp)
    return comp


# Gemeenschappelijk raster voor grids die onderling verschoven liggen (bijv. door
# gewijzigde studygebied-bbox tussen commits). Aggregatie betekent detailverlies
# t.o.v. de bron-resolutie: dit is een fallback, geen gelijkwaardige vergelijking.
# Zuiverder: bron-grids gelijk trekken en op eigen resolutie vergelijken.
ALIGN_GRID = 100.0  # m


def _aggregate_to_grid(arr, mask, geo, x0, y0, cell, nx, ny):
    """Som bronwaarden per doelcel via celcentrum-toewijzing; behoudt totalen."""
    rows, cols = np.nonzero(mask)
    vals = arr[rows, cols].astype(np.float64)
    sx, sy, ox, oy = geo
    xc = ox + (cols + 0.5) * sx
    yc = oy - (rows + 0.5) * sy
    ix = np.floor((xc - x0) / cell).astype(np.int64)
    iy = np.floor((y0 - yc) / cell).astype(np.int64)
    ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
    out = np.zeros((ny, nx), dtype=np.float64)
    cnt = np.zeros((ny, nx), dtype=np.int32)
    np.add.at(out, (iy[ok], ix[ok]), vals[ok])
    np.add.at(cnt, (iy[ok], ix[ok]), 1)
    return out, cnt


def _mode_to_grid(arr, mask, geo, x0, y0, cell, nx, ny):
    """Modus (meest voorkomende klasse) per doelcel via celcentrum-toewijzing.
    Retourneert int64-grid; -1 = geen data."""
    rows, cols = np.nonzero(mask)
    vals = arr[rows, cols].astype(np.int64)
    sx, sy, ox, oy = geo
    xc = ox + (cols + 0.5) * sx
    yc = oy - (rows + 0.5) * sy
    ix = np.floor((xc - x0) / cell).astype(np.int64)
    iy = np.floor((y0 - yc) / cell).astype(np.int64)
    ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
    out = np.full(ny * nx, -1, dtype=np.int64)
    if not ok.any():
        return out.reshape(ny, nx)
    cell_idx = iy[ok] * nx + ix[ok]
    v = vals[ok]
    k = int(v.max()) + 1
    key = cell_idx * k + v
    uniq, counts = np.unique(key, return_counts=True)
    u_cell, u_val = uniq // k, uniq % k
    order = np.lexsort((counts, u_cell))  # per cel oplopend in count
    u_cell, u_val = u_cell[order], u_val[order]
    last = np.r_[u_cell[1:] != u_cell[:-1], True]  # laatste per cel = hoogste count
    out[u_cell[last]] = u_val[last]
    return out.reshape(ny, nx)


def compare_rasters_misaligned(arr_a, nodata_a, geo_a, arr_b, nodata_b, geo_b,
                               rel, art_dir, art_rel, comp):
    """Grids met verschillende omvang/oorsprong: numeriek vergelijken als som per
    gemeenschappelijke ALIGN_GRID-cel (celcentrum-toewijzing, totalen blijven exact);
    categoriaal alleen als side-by-side beeld."""
    base = sanitize(rel)
    mask_a, mask_b = valid_mask(arr_a, nodata_a), valid_mask(arr_b, nodata_b)
    note = (f"grids onderling verschoven (A origin {geo_a[2]:.1f},{geo_a[3]:.1f} vs "
            f"B {geo_b[2]:.1f},{geo_b[3]:.1f}): celvergelijking op bronresolutie onmogelijk; "
            f"vergeleken als som per {ALIGN_GRID:.0f}m-cel (detailverlies)")

    cell = ALIGN_GRID
    west = max(geo_a[2], geo_b[2])
    north = min(geo_a[3], geo_b[3])
    east = min(geo_a[2] + arr_a.shape[1] * geo_a[0], geo_b[2] + arr_b.shape[1] * geo_b[0])
    south = max(geo_a[3] - arr_a.shape[0] * geo_a[1], geo_b[3] - arr_b.shape[0] * geo_b[1])
    x0 = np.floor(west / cell) * cell
    y0 = np.ceil(north / cell) * cell
    nx = int(np.ceil((east - x0) / cell))
    ny = int(np.ceil((y0 - south) / cell))

    if is_categorical(arr_a, arr_b):
        comp["compare"] = "cell_categorical_aggregated"
        comp["notes"].append(note.replace("som per", "modus per"))
        mode_a = _mode_to_grid(arr_a, mask_a, geo_a, x0, y0, cell, nx, ny)
        mode_b = _mode_to_grid(arr_b, mask_b, geo_b, x0, y0, cell, nx, ny)
        def_a, def_b = mode_a >= 0, mode_b >= 0
        both, either = def_a & def_b, def_a | def_b
        diff = both & (mode_a != mode_b)
        n_total = int(np.count_nonzero(either))
        coverage_mismatch = int(np.count_nonzero(def_a != def_b))
        n_diff = int(np.count_nonzero(diff)) + coverage_mismatch
        comp["metrics"].append({"name": "cells", "unit": f"{cell:.0f}m cells",
                                "n_total": n_total, "n_diff": n_diff})
        if coverage_mismatch:
            comp["metrics"].append({"name": "coverage_mismatch", "unit": f"{cell:.0f}m cells",
                                    "n_total": n_total, "n_diff": coverage_mismatch})
        if n_diff:
            a_vals, b_vals = mode_a[diff], mode_b[diff]
            pairs, counts = np.unique(np.stack([a_vals, b_vals], axis=1), axis=0,
                                      return_counts=True)
            order = np.argsort(-counts)
            conf_fn = os.path.join(art_dir, f"{base}_confusion.csv")
            with open(conf_fn, "w", newline="", encoding="utf8") as f:
                w = csv.writer(f)
                w.writerow(["class_a", "class_b", "n_cells"])
                for i in order:
                    w.writerow([class_label(int(pairs[i][0]), arr_a.dtype),
                                class_label(int(pairs[i][1]), arr_b.dtype), int(counts[i])])
            comp["artifacts"].append({"kind": "confusion", "path": f"{art_rel}/{base}_confusion.csv"})
            diff_full = diff | (def_a != def_b)
            # A/B op bronresolutie (scherpte), diff op het gemeenschappelijke raster
            vals = np.unique(np.concatenate([np.unique(arr_a[mask_a]), np.unique(arr_b[mask_b])]))
            if vals.size <= 512:
                palette = _stable_palette(vals)
                for tag, arr, mask in (("a", arr_a, mask_a), ("b", arr_b, mask_b)):
                    fn = os.path.join(art_dir, f"{base}_{tag}.png")
                    write_png_categorical(arr, mask, fn, palette)
                    comp["artifacts"].append({"kind": f"png_{tag}", "path": f"{art_rel}/{base}_{tag}.png"})
                fn = os.path.join(art_dir, f"{base}_diff.png")
                write_png_diffmask(np.zeros_like(mode_a, dtype=np.float64), either, diff_full, fn)
                comp["artifacts"].append({"kind": "png_diff", "path": f"{art_rel}/{base}_diff.png"})
        return comp

    comp["compare"] = "cell_numeric_aggregated"
    comp["notes"].append(note)
    agg_a, cnt_a = _aggregate_to_grid(arr_a, mask_a, geo_a, x0, y0, cell, nx, ny)
    agg_b, cnt_b = _aggregate_to_grid(arr_b, mask_b, geo_b, x0, y0, cell, nx, ny)
    both = (cnt_a > 0) & (cnt_b > 0)
    either = (cnt_a > 0) | (cnt_b > 0)
    delta = np.where(both, agg_b - agg_a, 0.0)
    diff = both & (np.abs(delta) > 1e-9)
    n_total = int(np.count_nonzero(either))
    coverage_mismatch = int(np.count_nonzero((cnt_a > 0) != (cnt_b > 0)))
    sum_a = float(agg_a[cnt_a > 0].sum())
    sum_b = float(agg_b[cnt_b > 0].sum())
    comp["metrics"].append({"name": "cells", "unit": f"{cell:.0f}m cells",
                            "n_total": n_total, "n_diff": int(np.count_nonzero(diff))})
    comp["metrics"].append({"name": "sum_a", "value": sum_a})
    comp["metrics"].append({"name": "sum_b", "value": sum_b})
    if coverage_mismatch:
        comp["metrics"].append({"name": "coverage_mismatch", "unit": f"{cell:.0f}m cells",
                                "n_total": n_total, "n_diff": coverage_mismatch})
    if diff.any():
        absdelta = np.abs(delta)
        comp["metrics"].append({"name": "max_abs_diff", "value": float(absdelta.max())})
        comp["metrics"].append({"name": "mean_abs_diff_changed", "value": float(absdelta[diff].mean())})
        agg_geo_tags = [
            (33550, 12, 3, (cell, cell, 0.0), False),
            (33922, 12, 6, (0.0, 0.0, 0.0, float(x0), float(y0), 0.0), False),
        ]
        _write_diff_tif(art_dir, art_rel, base, delta.astype(np.float32), agg_geo_tags, comp)
        agg_geo = (cell, cell, float(x0), float(y0))
        _write_sample_csv(art_dir, art_rel, base, diff, agg_a, agg_b,
                          cnt_a > 0, cnt_b > 0, agg_geo, 50, comp, categorical=False)
        # A/B op bronresolutie (zelfde stretch), diff op het gemeenschappelijke raster
        fn_a = os.path.join(art_dir, f"{base}_a.png")
        lo, hi = write_png_numeric(arr_a.astype(np.float64), mask_a, fn_a)
        comp["artifacts"].append({"kind": "png_a", "path": f"{art_rel}/{base}_a.png"})
        fn_b = os.path.join(art_dir, f"{base}_b.png")
        write_png_numeric(arr_b.astype(np.float64), mask_b, fn_b, lo, hi)
        comp["artifacts"].append({"kind": "png_b", "path": f"{art_rel}/{base}_b.png"})
        fn_d = os.path.join(art_dir, f"{base}_diff.png")
        write_png_diffmask(agg_a, cnt_a > 0, diff, fn_d)
        comp["artifacts"].append({"kind": "png_diff", "path": f"{art_rel}/{base}_diff.png"})
    return comp


def _write_diff_tif(art_dir, art_rel, base, data, extratags, comp):
    fn = os.path.join(art_dir, f"{base}_diff.tif")
    try:
        tifffile.imwrite(fn, data, extratags=extratags or None)
    except Exception:
        tifffile.imwrite(fn, data)
    comp["artifacts"].append({"kind": "diff_raster", "path": f"{art_rel}/{base}_diff.tif"})


def _write_sample_csv(art_dir, art_rel, base, diffmask, arr_a, arr_b,
                      mask_a, mask_b, geo, max_samples, comp, categorical):
    rows, cols = np.nonzero(diffmask)
    if rows.size == 0:
        return
    if categorical:
        take = slice(0, max_samples)
        order = np.arange(rows.size)
    else:
        fa = arr_a[rows, cols].astype(np.float64)
        fb = arr_b[rows, cols].astype(np.float64)
        order = np.argsort(-np.abs(np.where(np.isnan(fb - fa), np.inf, fb - fa)))
        take = slice(0, max_samples)
    sel = order[take]
    x, y = rc_to_xy(rows[sel], cols[sel], geo)
    fn = os.path.join(art_dir, f"{base}_sample.csv")
    with open(fn, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["row", "col", "x", "y", "value_a", "value_b"])
        for i, idx in enumerate(sel):
            r, c = int(rows[idx]), int(cols[idx])
            va = arr_a[r, c] if mask_a[r, c] else ""
            vb = arr_b[r, c] if mask_b[r, c] else ""
            w.writerow([r, c,
                        "" if x[i] is None else f"{x[i]:.1f}",
                        "" if y[i] is None else f"{y[i]:.1f}",
                        va, vb])
    comp["artifacts"].append({"kind": "sample", "path": f"{art_rel}/{base}_sample.csv"})


def _thumbs_categorical(arr_a, mask_a, arr_b, mask_b, diffmask, art_dir, art_rel, base, comp):
    vals = np.unique(np.concatenate([np.unique(arr_a[mask_a]), np.unique(arr_b[mask_b])]))
    if vals.size > 512:  # geen zinvol klassenbeeld
        return
    palette = _stable_palette(vals)
    for tag, arr, mask in (("a", arr_a, mask_a), ("b", arr_b, mask_b)):
        fn = os.path.join(art_dir, f"{base}_{tag}.png")
        write_png_categorical(arr, mask, fn, palette)
        comp["artifacts"].append({"kind": f"png_{tag}", "path": f"{art_rel}/{base}_{tag}.png"})
    fn = os.path.join(art_dir, f"{base}_diff.png")
    write_png_diffmask(arr_a.astype(np.float64), mask_a, diffmask, fn)
    comp["artifacts"].append({"kind": "png_diff", "path": f"{art_rel}/{base}_diff.png"})


def _thumbs_numeric(fa, mask_a, fb, mask_b, diffmask, art_dir, art_rel, base, comp):
    fn_a = os.path.join(art_dir, f"{base}_a.png")
    lo, hi = write_png_numeric(fa, mask_a, fn_a)  # zelfde stretch voor B
    comp["artifacts"].append({"kind": "png_a", "path": f"{art_rel}/{base}_a.png"})
    fn_b = os.path.join(art_dir, f"{base}_b.png")
    write_png_numeric(fb, mask_b, fn_b, lo, hi)
    comp["artifacts"].append({"kind": "png_b", "path": f"{art_rel}/{base}_b.png"})
    fn_d = os.path.join(art_dir, f"{base}_diff.png")
    write_png_diffmask(fa, mask_a, diffmask, fn_d)
    comp["artifacts"].append({"kind": "png_diff", "path": f"{art_rel}/{base}_diff.png"})


def compare_tables(path_a, path_b, rel):
    comp = {"name": rel, "compare": "table", "metrics": [], "artifacts": [], "notes": []}
    with open(path_a, newline="", encoding="utf8", errors="replace") as f:
        rows_a = list(csv.reader(f, delimiter=_sniff_delim(f)))
    with open(path_b, newline="", encoding="utf8", errors="replace") as f:
        rows_b = list(csv.reader(f, delimiter=_sniff_delim(f)))
    if not rows_a or not rows_b or rows_a[0] != rows_b[0] or len(rows_a) != len(rows_b):
        comp["notes"].append(
            f"structure differs: A={len(rows_a)} rijen, B={len(rows_b)} rijen"
            + ("" if rows_a and rows_b and rows_a[0] == rows_b[0] else ", header verschilt"))
        comp["metrics"].append({"name": "structure_equal", "value": 0})
        return comp
    n_total = sum(len(r) for r in rows_a[1:])
    n_diff = sum(1 for ra, rb in zip(rows_a[1:], rows_b[1:])
                 for ca, cb in zip(ra, rb) if not _cell_eq(ca, cb))
    comp["metrics"].append({"name": "cells", "unit": "cells",
                            "n_total": n_total, "n_diff": n_diff})
    return comp


def _sniff_delim(f):
    pos = f.tell()
    head = f.read(4096)
    f.seek(pos)
    return ";" if head.count(";") > head.count(",") else ","


def _cell_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return float(a.replace(",", ".")) == float(b.replace(",", "."))
    except ValueError:
        return False


def compare_binary(path_a, path_b, rel):
    equal = filecmp.cmp(path_a, path_b, shallow=False)
    return {"name": rel, "compare": "binary_file", "artifacts": [], "notes": [],
            "metrics": [{"name": "file_equal", "value": 1 if equal else 0}]}


# ---------------------------------------------------------------- hoofdloop

def run_compare(dir_a, dir_b, out_dir, name_a, name_b, excludes, max_samples, only=None):
    os.makedirs(out_dir, exist_ok=True)
    art_rel = "artifacts"
    art_dir = os.path.join(out_dir, art_rel)
    os.makedirs(art_dir, exist_ok=True)

    files_a = discover_files(dir_a, excludes, only)
    files_b = discover_files(dir_b, excludes, only)
    keys_common = sorted(set(files_a) & set(files_b))
    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))

    comparisons = []
    for key in keys_common:
        rel = files_a[key]
        pa, pb = os.path.join(dir_a, files_a[key]), os.path.join(dir_b, files_b[key])
        ext = os.path.splitext(rel)[1].lower()
        print(f"[*] {rel}")
        try:
            if ext in RASTER_EXTS:
                comp = compare_rasters(pa, pb, rel, art_dir, art_rel, max_samples)
            elif ext in TABLE_EXTS:
                comp = compare_tables(pa, pb, rel)
            else:
                comp = compare_binary(pa, pb, rel)
        except Exception as e:  # meting mislukt: eerlijk rapporteren, nooit stil overslaan
            comp = {"name": rel, "compare": "error", "metrics": [],
                    "artifacts": [], "notes": [f"comparison error: {e}"]}
        comparisons.append(comp)

    result = {
        "schema": 2,
        "kind": "run_comparison",
        "title": f"RSopen run comparison: {name_a} vs {name_b}",
        "run_a": {"name": name_a, "path": os.path.abspath(dir_a)},
        "run_b": {"name": name_b, "path": os.path.abspath(dir_b)},
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "comparisons": comparisons,
        "only_in_a": [files_a[k] for k in only_a],
        "only_in_b": [files_b[k] for k in only_b],
    }
    result_fn = os.path.join(out_dir, "compare.result.json")
    with open(result_fn, "w", encoding="utf8") as f:
        json.dump(result, f, indent=1)
    print(f"[+] {len(comparisons)} vergelijkingen, {len(only_a)} alleen in A, "
          f"{len(only_b)} alleen in B -> {result_fn}")
    return result_fn


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("dir_a")
    ap.add_argument("dir_b")
    ap.add_argument("--out", required=True, help="outputmap voor json + artifacts")
    ap.add_argument("--name-a", default=None, help="label run A (default: mapnaam)")
    ap.add_argument("--name-b", default=None, help="label run B (default: mapnaam)")
    ap.add_argument("--include-xml", action="store_true",
                    help="ook .xml vergelijken (audit trails geven doorgaans ruis)")
    ap.add_argument("--only", default=None,
                    help="glob op relatief pad; alleen matchende bestanden vergelijken")
    ap.add_argument("--max-samples", type=int, default=50)
    ap.add_argument("--report", action="store_true",
                    help="genereer direct ook het HTML-rapport")
    args = ap.parse_args(argv)

    excludes = [p for p in DEFAULT_EXCLUDES if not (args.include_xml and p == "*.xml")]
    name_a = args.name_a or os.path.basename(os.path.normpath(args.dir_a))
    name_b = args.name_b or os.path.basename(os.path.normpath(args.dir_b))
    result_fn = run_compare(args.dir_a, args.dir_b, args.out,
                            name_a, name_b, excludes, args.max_samples, args.only)
    if args.report:
        import rs_report
        rs_report.main([result_fn])


if __name__ == "__main__":
    main()
