#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clean JSON Differences Comparison Report Tool with Row Value Group Palette Highlighting.

Focuses on parameters across JSON files with neatly formatted ASCII tables.
Values on the same row are grouped by value:
- Identical values on the same row share the SAME distinct color.
- Different value groups on the same row receive DIFFERENT colors from a palette.
"""

import json
import os
import sys
import re
import argparse

# Enable ANSI terminal color support on Windows
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        os.system("")

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ANSI Color Palette for distinct value groups on the same row
COLOR_PALETTE = [
    "\033[92m",  # Bright Green (Value Group 1)
    "\033[96m",  # Bright Cyan  (Value Group 2)
    "\033[93m",  # Bright Yellow(Value Group 3)
    "\033[95m",  # Bright Magenta(Value Group 4)
    "\033[94m",  # Bright Blue  (Value Group 5)
    "\033[97m",  # Bright White (Value Group 6)
]
COLOR_RED = "\033[91m"     # Red for <MISSING>
COLOR_RESET = "\033[0m"

ANSI_REGEX = re.compile(r'\033\[[0-9;]*m')


def visible_len(s):
    """
    Returns string length excluding invisible ANSI color escape codes.
    """
    return len(ANSI_REGEX.sub('', str(s)))


def load_json_files(preset_dir):
    files = sorted([f for f in os.listdir(preset_dir) if f.endswith('.json')])
    data = {}
    for f in files:
        fpath = os.path.join(preset_dir, f)
        try:
            with open(fpath, 'r', encoding='utf-8') as fp:
                data[f] = json.load(fp)
        except Exception:
            pass
    return data


def extract_sections(data_dict):
    sections = {}

    def _traverse(obj, section_path):
        if isinstance(obj, dict):
            has_leaf = any(not isinstance(v, (dict, list)) for v in obj.values())
            has_list = any(isinstance(v, list) for v in obj.values())

            if has_leaf or has_list:
                if section_path not in sections:
                    sections[section_path] = set()
                for k in obj.keys():
                    if not isinstance(obj[k], dict):
                        sections[section_path].add(k)

            for k, v in obj.items():
                if isinstance(v, dict):
                    sub_path = f"{section_path}.{k}" if section_path else k
                    _traverse(v, sub_path)

    for f_data in data_dict.values():
        _traverse(f_data, "")

    return sections


def format_value_clean(val, max_len=30):
    """
    Summarizes complex lists/dicts to prevent wide text wrapping in terminal tables.
    """
    if val == "<MISSING>":
        return "<MISSING>"

    if isinstance(val, list):
        if val and isinstance(val[0], dict) and "DevicePATH" in val[0]:
            paths = [d.get("DevicePATH", "") for d in val if isinstance(d, dict)]
            summary = f"[{len(val)} devs: {', '.join(paths)}]"
            if len(summary) > max_len:
                return f"[{len(val)} devices]"
            return summary

        s = json.dumps(val, ensure_ascii=False)
        if len(s) > max_len:
            return f"List[{len(val)} items]"
        return s

    if isinstance(val, dict):
        return f"Dict[{len(val)} keys]"

    s = str(val)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


def get_nested_raw_val(data, section_path, key):
    parts = [p for p in section_path.split('.') if p]
    curr = data
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return "<MISSING>"
    if isinstance(curr, dict) and key in curr:
        return curr[key]
    return "<MISSING>"


def pad_cell(cell, width):
    vlen = visible_len(cell)
    padding = " " * max(0, width - vlen)
    return str(cell) + padding


def format_table(header, rows, col_widths):
    top_line = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
    header_line = "│ " + " │ ".join(pad_cell(h, w) for h, w in zip(header, col_widths)) + " │"
    mid_line = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
    bot_line = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

    lines = [top_line, header_line, mid_line]
    for row in rows:
        row_str = "│ " + " │ ".join(pad_cell(cell, w) for cell, w in zip(row, col_widths)) + " │"
        lines.append(row_str)
    lines.append(bot_line)
    return "\n".join(lines)


def colorize_row_values(clean_vals):
    """
    Groups unique values on the same row and assigns a distinct color to each value group.
    - Equal values share the exact same color.
    - Different value groups receive distinct colors from the palette.
    """
    unique_vals = []
    for v in clean_vals:
        if v not in unique_vals:
            unique_vals.append(v)

    val_to_color = {}
    for idx, u_val in enumerate(unique_vals):
        if u_val == "<MISSING>":
            val_to_color[u_val] = COLOR_RED
        else:
            val_to_color[u_val] = COLOR_PALETTE[idx % len(COLOR_PALETTE)]

    colored_vals = []
    for v in clean_vals:
        color = val_to_color[v]
        colored_vals.append(f"{color}{v}{COLOR_RESET}")

    return colored_vals


def run_comparison(preset_dir, show_all=False):
    data_dict = load_json_files(preset_dir)
    file_names = list(data_dict.keys())

    if not file_names:
        print("[ERROR] No JSON files found in directory.")
        return

    sections = extract_sections(data_dict)
    short_headers = [os.path.splitext(fn)[0].replace("APSconfig", "") for fn in file_names]

    print("\n" + "=" * 80)
    print(f" DIFFERENCES COMPARISON REPORT (ROW VALUE GROUP COLORING)")
    print(f" Working Directory : {os.path.abspath(preset_dir)}")
    print(f" Preset Files      : {', '.join(short_headers)}")
    print(f" Color Legend      : Equal values on the same row share the SAME distinct color group.")
    print("=" * 80)

    total_diff_keys = 0
    total_matching_sections = 0
    diff_sections_count = 0

    for section_path in sorted(sections.keys()):
        keys = sorted(list(sections[section_path]))
        diff_rows = []

        for k in keys:
            raw_vals = [get_nested_raw_val(data_dict[fn], section_path, k) for fn in file_names]
            str_vals = [json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v) for v in raw_vals]
            all_same = len(set(str_vals)) == 1

            if not all_same:
                clean_vals = [format_value_clean(v) for v in raw_vals]
                colored_vals = colorize_row_values(clean_vals)
                diff_rows.append(([k] + clean_vals, [k] + colored_vals))
                total_diff_keys += 1

        if not diff_rows:
            total_matching_sections += 1
            if show_all:
                print(f"\n✓ Section [{section_path}]: All {len(keys)} parameters match 100%.")
            continue

        diff_sections_count += 1
        print(f"\n📌 DIFFERENCES IN [{section_path}]  ({len(diff_rows)} differing parameter(s)):")

        headers = ["Parameter Key"] + short_headers
        col_widths = [len(h) for h in headers]

        # Calculate widths based on uncolored values
        for raw_row, _ in diff_rows:
            for i, val in enumerate(raw_row):
                col_widths[i] = max(col_widths[i], visible_len(val))

        col_widths[0] = max(col_widths[0], 25)
        for i in range(1, len(col_widths)):
            col_widths[i] = max(col_widths[i], 18)

        display_rows = [colored_row for _, colored_row in diff_rows]
        table_str = format_table(headers, display_rows, col_widths)
        print(table_str)

    print("\n" + "=" * 80)
    print(f" SUMMARY:")
    print(f"  - Sections with Differences : {diff_sections_count}")
    print(f"  - Total Differing Parameters: {total_diff_keys}")
    print(f"  - Sections 100% Identical   : {total_matching_sections}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Clean comparison script with row-level distinct value group color highlighting."
    )
    parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Directory containing JSON files to compare (default: current script directory)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Show status for all sections including 100% matching sections"
    )

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    preset_dir = os.path.abspath(args.dir) if args.dir != "." else script_dir

    run_comparison(preset_dir, show_all=args.all)


if __name__ == "__main__":
    main()
