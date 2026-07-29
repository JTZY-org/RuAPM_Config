#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal JSON Inspection and Auto-Repair Tool.

Features:
1. Universal Schema Comparison: Recursively checks missing keys, extra keys, and data type mismatches across any nested JSON structures.
2. Syntax Self-Healing: Automatically cleans up common JSON syntax errors (trailing commas, C-style comments `//`, shell comments `#`).
3. Baseline Pre-Sorting & Full Structure Synchronization (--fix):
   - Sorts the baseline JSON file FIRST before executing comparison/fix operations.
   - Auto-fills missing keys and default values from baseline into target files.
   - Synchronizes values and data types from baseline whenever a key's data type differs.
   - Prunes/removes extra keys in target files that do not exist in the baseline JSON.
4. Alphabetical Key Sorting: Keeps all keys sorted across baseline and target JSON files.
5. Strict Baseline Requirement: A baseline JSON file MUST be explicitly specified.
"""

import json
import os
import sys
import re
import copy
import argparse

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def clean_json_syntax(content):
    """
    Cleans up common JSON syntax errors:
    - Removes single-line comments (// ...) and shell comments (# ...)
    - Removes trailing commas before closing braces/brackets (, } or , ])
    """
    content = re.sub(r'//.*', '', content)
    content = re.sub(r',\s*([\}\]])', r'\1', content)
    return content


def load_json_robust(file_path):
    """
    Robustly loads a JSON file with syntax self-healing fallback.
    Returns (data, is_repaired).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    try:
        data = json.loads(content)
        return data, False
    except Exception:
        cleaned = clean_json_syntax(content)
        try:
            data = json.loads(cleaned)
            return data, True
        except Exception as e:
            raise e


def sort_json_file(file_path):
    """
    Reads a JSON file and rewrites it with alphabetically sorted keys.
    """
    try:
        data, was_repaired = load_json_robust(file_path)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4, sort_keys=True)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to sort {file_path}: {e}")
        return False


def get_all_paths(data, path=""):
    """
    Recursively extracts all key paths and their data type names from any JSON structure.
    """
    paths = {}
    if isinstance(data, dict):
        for k, v in data.items():
            current_path = f"{path}.{k}" if path else k
            paths[current_path] = type(v).__name__
            paths.update(get_all_paths(v, current_path))
    elif isinstance(data, list):
        paths[f"{path}[]_len"] = len(data)
        for i, item in enumerate(data):
            current_path = f"{path}[{i}]"
            paths[current_path] = type(item).__name__
            paths.update(get_all_paths(item, current_path))
    return paths


def get_schema_keys(data, path=""):
    """
    Extracts generic schema key paths (ignoring array element indices).
    """
    schema = set()
    if isinstance(data, dict):
        for k, v in data.items():
            current_path = f"{path}.{k}" if path else k
            schema.add(current_path)
            schema.update(get_schema_keys(v, current_path))
    elif isinstance(data, list):
        for item in data:
            current_path = f"{path}[*]"
            schema.update(get_schema_keys(item, current_path))
    return schema


def fill_sync_and_prune_keys(ref, tgt):
    """
    Recursively:
    1. Fills missing keys from ref into tgt.
    2. Synchronizes values & types from ref into tgt when types differ.
    3. Prunes/removes extra keys from tgt that do not exist in ref.
    Returns (total_modified_count, filled_keys, synced_type_keys, removed_extra_keys).
    """
    filled_keys = []
    synced_type_keys = []
    removed_extra_keys = []

    def _recursive_sync(r, t, path=""):
        count = 0
        if isinstance(r, dict) and isinstance(t, dict):
            # 1. Prune extra keys in t that do not exist in r
            t_keys_to_remove = [k for k in t.keys() if k not in r]
            for k in t_keys_to_remove:
                curr_path = f"{path}.{k}" if path else k
                del t[k]
                removed_extra_keys.append(curr_path)
                count += 1

            # 2. Fill missing keys & sync type mismatches
            for k, v in r.items():
                curr_path = f"{path}.{k}" if path else k
                if k not in t:
                    t[k] = copy.deepcopy(v)
                    filled_keys.append(curr_path)
                    count += 1
                else:
                    if type(v) != type(t[k]):
                        orig_type = type(t[k]).__name__
                        new_type = type(v).__name__
                        t[k] = copy.deepcopy(v)
                        synced_type_keys.append(f"{curr_path} ({orig_type} -> {new_type})")
                        count += 1
                    else:
                        if isinstance(v, dict) and isinstance(t[k], dict):
                            count += _recursive_sync(v, t[k], curr_path)
                        elif isinstance(v, list) and isinstance(t[k], list):
                            min_len = min(len(v), len(t[k]))
                            for i in range(min_len):
                                if isinstance(v[i], dict) and isinstance(t[k][i], dict):
                                    count += _recursive_sync(v[i], t[k][i], f"{curr_path}[{i}]")
        return count

    count = _recursive_sync(ref, tgt)
    return count, filled_keys, synced_type_keys, removed_extra_keys


def compare_json(ref_data, target_data):
    """
    Compares target JSON data against baseline JSON data generically.
    """
    ref_paths = get_all_paths(ref_data)
    target_paths = get_all_paths(target_data)

    ref_schema = get_schema_keys(ref_data)
    target_schema = get_schema_keys(target_data)

    missing_schema = sorted(list(ref_schema - target_schema))
    extra_schema = sorted(list(target_schema - ref_schema))

    type_mismatches = {}
    for path, ref_type in ref_paths.items():
        if path in target_paths:
            tgt_type = target_paths[path]
            if ref_type != tgt_type:
                type_mismatches[path] = (ref_type, tgt_type)

    array_len_diffs = {}
    for path, val in ref_paths.items():
        if path.endswith("[]_len"):
            tgt_val = target_paths.get(path)
            if tgt_val is not None and val != tgt_val:
                clean_path = path[:-6]
                array_len_diffs[clean_path] = (val, tgt_val)

    return {
        "missing_schema": missing_schema,
        "extra_schema": extra_schema,
        "type_mismatches": type_mismatches,
        "array_len_diffs": array_len_diffs,
    }


def inspect_directory(preset_dir, baseline_name, auto_fix=False, sort_keys=True):
    if os.path.isabs(baseline_name):
        baseline_path = baseline_name
    else:
        baseline_path = os.path.abspath(os.path.join(preset_dir, baseline_name))

    if not os.path.exists(baseline_path):
        print(f"[ERROR] Baseline JSON file not found: {baseline_path}")
        sys.exit(1)

    baseline_basename = os.path.basename(baseline_path)

    # 1. Pre-sort baseline JSON file FIRST when --fix is enabled
    if auto_fix and sort_keys:
        sort_json_file(baseline_path)

    try:
        ref_data, was_repaired = load_json_robust(baseline_path)
        if was_repaired:
            print(f"[NOTE] Baseline file contained malformed syntax and was auto-cleaned in memory.")
    except Exception as e:
        print(f"[ERROR] Failed to parse baseline JSON [{baseline_name}]: {e}")
        sys.exit(1)

    print("=" * 70)
    print(f" Baseline File  : {baseline_basename} (Pre-Sorted)")
    print(f" Working Dir    : {os.path.abspath(preset_dir)}")
    print(f" Auto-Fix Mode  : {'ENABLED (--fix)' if auto_fix else 'DISABLED (pass --fix to enable)'}")
    print("=" * 70)

    target_files = []
    for f in os.listdir(preset_dir):
        if not f.endswith('.json'):
            continue
        full_fpath = os.path.abspath(os.path.join(preset_dir, f))
        if f == baseline_basename or os.path.samefile(full_fpath, baseline_path):
            continue
        target_files.append(f)

    if not target_files:
        print("No target .json files found to check.")
        return

    total_fixed_count = 0

    for fname in sorted(target_files):
        fpath = os.path.join(preset_dir, fname)
        print(f"\n▶ Checking file: [{fname}]")
        print("-" * 50)

        try:
            target_data, was_repaired = load_json_robust(fpath)
            if was_repaired:
                print("  [✔ SYNTAX HEALED] Cleaned malformed JSON syntax (trailing commas/comments).")
        except Exception as e:
            print(f"  [✗ PARSE ERROR] Invalid JSON syntax: {e}")
            continue

        result = compare_json(ref_data, target_data)

        missing = result["missing_schema"]
        extra = result["extra_schema"]
        types_diff = result["type_mismatches"]
        arr_diff = result["array_len_diffs"]

        is_perfect = (not missing and not extra and not types_diff and not arr_diff)

        if is_perfect:
            print("  [✓ PERFECT] Structure, keys, types, and array lengths match baseline 100%.")
            continue

        # Auto-fix mode: Fix missing keys, sync type mismatches, AND prune extra keys not in baseline
        if auto_fix:
            mod_count, filled_keys, synced_types, removed_extras = fill_sync_and_prune_keys(ref_data, target_data)
            if mod_count > 0 or was_repaired:
                try:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        json.dump(target_data, f, ensure_ascii=False, indent=4, sort_keys=sort_keys)
                    
                    if filled_keys:
                        print(f"  [✔ AUTO-FILLED] Filled {len(filled_keys)} missing key(s) into {fname}:")
                        for fk in filled_keys:
                            print(f"      + Filled: {fk}")
                    
                    if synced_types:
                        print(f"  [✔ TYPE-SYNCED] Synchronized {len(synced_types)} baseline value(s) for type mismatch(es):")
                        for st in synced_types:
                            print(f"      ~ Synced: {st}")

                    if removed_extras:
                        print(f"  [✔ EXTRA-REMOVED] Pruned/removed {len(removed_extras)} extra key(s) not in baseline:")
                        for re_key in removed_extras:
                            print(f"      - Removed: {re_key}")

                    total_fixed_count += mod_count
                    # Re-evaluate comparison after fix
                    result = compare_json(ref_data, target_data)
                    missing = result["missing_schema"]
                    extra = result["extra_schema"]
                    types_diff = result["type_mismatches"]
                except Exception as e:
                    print(f"  [✗ WRITE ERROR] Failed to save updated JSON: {e}")

        # Missing keys
        if missing:
            print(f"  [✗ MISSING KEYS] Found {len(missing)} missing key(s) compared to baseline:")
            for m in missing:
                print(f"      - {m}")
            print(f"      💡 Tip: Run 'python check_json.py {baseline_basename} --fix' to auto-repair keys.")
        else:
            print("  [✓ KEYS INTACT] No missing keys.")

        # Extra keys
        if extra:
            print(f"  [! EXTRA KEYS] Found {len(extra)} extra key(s) compared to baseline:")
            for e in extra:
                print(f"      + {e}")

        # Type mismatches
        if types_diff:
            print(f"  [! TYPE MISMATCHES] Found {len(types_diff)} type mismatch(es):")
            for k, (t_ref, t_tgt) in types_diff.items():
                print(f"      ~ {k}: baseline({t_ref}) <--> current({t_tgt})")

        # Array length differences
        if arr_diff:
            print(f"  [* ARRAY LENGTH DIFFS] Found {len(arr_diff)} array size difference(s):")
            for k, (l_ref, l_tgt) in arr_diff.items():
                print(f"      * {k}: baseline has {l_ref} item(s) <--> current has {l_tgt} item(s)")

    print("\n" + "=" * 70)
    if auto_fix:
        print(f" Auto-fix completed. Total modifications made across files: {total_fixed_count}")
    else:
        print(f" Inspection finished. Run with 'python check_json.py {baseline_basename} --fix' to auto-repair.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Universal JSON inspection, syntax self-healing, key auto-repair, type sync, and extra key pruning tool."
    )
    parser.add_argument(
        "baseline_pos",
        nargs="?",
        default=None,
        help="Baseline JSON file name or path (REQUIRED)"
    )
    parser.add_argument(
        "--baseline", "-b",
        default=None,
        help="Baseline JSON file name or path (REQUIRED)"
    )
    parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Directory containing JSON files to check (default: script directory)"
    )
    parser.add_argument(
        "--fix", "-f",
        action="store_true",
        help="Auto-fix mode: auto-fill missing keys, sync baseline types, and prune extra keys"
    )
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="Do not sort keys alphabetically when saving fixed files"
    )

    args = parser.parse_args()

    baseline = args.baseline_pos or args.baseline

    if not baseline:
        print("[ERROR] A baseline JSON file MUST be specified!")
        print("\nUsage:")
        print("  python check_json.py <baseline_json_file> [--fix]")
        print("\nExamples:")
        print("  python check_json.py APSconfigRK3566-7HN.json")
        print("  python check_json.py APSconfigRK3566-9SN.json --fix")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    preset_dir = os.path.abspath(args.dir) if args.dir != "." else script_dir

    inspect_directory(preset_dir, baseline, auto_fix=args.fix, sort_keys=not args.no_sort)


if __name__ == "__main__":
    main()
